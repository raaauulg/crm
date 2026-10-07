"""Web: login, cierre de sesión, rutas protegidas, CSRF, autoescape y humo del dashboard."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from crm.models import Company, Phase, User
from crm.services import catalog, clients, companies
from crm.services.clock import today
from crm.services.companies import CompanyInput, ContactInput
from crm.web.formatting import euros, spanish_date

from .conftest import TEST_PASSWORD, TEST_USER, csrf_from, login, post_form


def company_count(session_factory: sessionmaker[Session]) -> int:
    with session_factory() as s:
        return int(s.scalar(select(func.count(Company.id))) or 0)


# --- Login y logout -----------------------------------------------------------------------


def test_wrong_password_shows_error_and_sets_no_session(client: TestClient) -> None:
    token = csrf_from(client.get("/login").text)
    response = client.post(
        "/login",
        data={"username": TEST_USER, "password": "no-es-esta", "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Usuario o contraseña incorrectos" in response.text
    assert client.get("/", follow_redirects=False).status_code == 303


def test_login_without_csrf_is_rejected(client: TestClient) -> None:
    client.get("/login")
    response = client.post(
        "/login",
        data={"username": TEST_USER, "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert client.get("/", follow_redirects=False).status_code == 303


def test_login_redirects_to_requested_internal_page(client: TestClient) -> None:
    token = csrf_from(client.get("/login?next=/empresas").text)
    response = client.post(
        "/login",
        data={
            "username": TEST_USER,
            "password": TEST_PASSWORD,
            "csrf_token": token,
            "next": "/empresas",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/empresas"


def test_login_with_htmx_uses_full_reload_redirect(client: TestClient) -> None:
    token = csrf_from(client.get("/login").text)
    response = client.post(
        "/login",
        data={"username": TEST_USER, "password": TEST_PASSWORD, "csrf_token": token},
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    assert response.headers["HX-Redirect"] == "/"


def test_backslash_next_is_not_followed(client: TestClient) -> None:
    token = csrf_from(client.get("/login").text)
    response = client.post(
        "/login",
        data={
            "username": TEST_USER,
            "password": TEST_PASSWORD,
            "csrf_token": token,
            "next": "/\\malicioso.example",
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/"


def test_csrf_token_from_before_login_is_not_valid_after_login(client: TestClient) -> None:
    old_token = csrf_from(client.get("/login").text)
    client.post(
        "/login",
        data={"username": TEST_USER, "password": TEST_PASSWORD, "csrf_token": old_token},
        follow_redirects=False,
    )
    response = client.post(
        "/empresas/nueva",
        data={"name": "Token Viejo", "csrf_token": old_token},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_logout_without_csrf_keeps_session(auth_client: TestClient) -> None:
    assert auth_client.post("/logout", data={}, follow_redirects=False).status_code == 403
    assert auth_client.get("/", follow_redirects=False).status_code == 200


def test_logout_redirects_to_login_and_protects_all_pages(auth_client: TestClient) -> None:
    response = post_form(auth_client, "/logout", {})
    assert response.headers["location"] == "/login"
    for url in ("/", "/empresas", "/empresas/nueva"):
        assert auth_client.get(url, follow_redirects=False).status_code == 303


def test_deactivated_user_loses_session(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    assert auth_client.get("/", follow_redirects=False).status_code == 200
    with session_factory() as s:
        user = s.scalar(select(User).where(User.username == TEST_USER))
        assert user is not None
        user.is_active = False
        s.commit()
    assert auth_client.get("/", follow_redirects=False).status_code == 303
    login(auth_client)
    assert auth_client.get("/", follow_redirects=False).status_code == 303


# --- Rutas protegidas y CSRF ---------------------------------------------------------------


def test_post_without_session_redirects_and_writes_nothing(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    response = client.post("/empresas/nueva", data={"name": "Intrusa"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")
    assert company_count(session_factory) == 0


def test_post_with_wrong_csrf_token_is_rejected(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    auth_client.get("/")  # genera el token de la sesión
    response = auth_client.post(
        "/empresas/nueva",
        data={"name": "Token Falso", "csrf_token": "inventado"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert company_count(session_factory) == 0


def test_csrf_token_in_header_is_accepted(auth_client: TestClient) -> None:
    token = csrf_from(auth_client.get("/").text)
    response = auth_client.post(
        "/empresas/nueva",
        data={"name": "Por Cabecera"},
        headers={"X-CSRF-Token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303


# --- Humo de la web con datos ------------------------------------------------------------


def test_company_name_is_escaped_in_html(auth_client: TestClient) -> None:
    response = post_form(
        auth_client, "/empresas/nueva", {"name": "<script>alert('x')</script> Talleres"}
    )
    page = auth_client.get(response.headers["location"]).text
    assert "<script>alert(" not in page
    assert "&lt;script&gt;" in page


def test_web_cannot_jump_to_won_phase(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as s:
        company_id = companies.create_company(s, CompanyInput(name="Sin Contrato"), "raul").id
    post_form(auth_client, f"/empresas/{company_id}/fase", {"phase": Phase.WON.value})
    with session_factory() as s:
        assert companies.get_company(s, company_id).phase == Phase.IDENTIFIED.value


def test_web_writes_record_logged_in_user_as_author(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    response = post_form(auth_client, "/empresas/nueva", {"name": "Autoría Prueba"})
    company_id = int(response.headers["location"].rsplit("/", 1)[1])
    post_form(auth_client, f"/empresas/{company_id}/fase", {"phase": Phase.CONTACTED.value})
    with session_factory() as s:
        company = companies.get_company(s, company_id)
        assert company.created_by == TEST_USER
        assert company.updated_by == TEST_USER


def test_contact_of_other_company_is_not_found(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as s:
        first = companies.create_company(s, CompanyInput(name="Empresa Uno"), "raul").id
        second = companies.create_company(s, CompanyInput(name="Empresa Dos"), "raul").id
        contact = companies.add_contact(s, first, ContactInput(name="Ana Ficticia"), "raul").id
    assert auth_client.get(f"/empresas/{first}/contactos/{contact}/editar").status_code == 200
    assert auth_client.get(f"/empresas/{second}/contactos/{contact}/editar").status_code == 404


def test_convert_button_points_to_existing_page(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """La ficha enseña «Convertir en cliente»: el enlace no puede dar 404."""
    with session_factory() as s:
        company_id = companies.create_company(s, CompanyInput(name="Casi Cliente"), "raul").id
    detail = auth_client.get(f"/empresas/{company_id}").text
    assert f"/empresas/{company_id}/convertir" in detail
    assert auth_client.get(f"/empresas/{company_id}/convertir").status_code == 200


def test_unknown_dashboard_tab_falls_back(auth_client: TestClient) -> None:
    assert auth_client.get("/?tab=inventada").status_code == 200


def test_clients_tab_shows_mrr_and_overdue_invoice_in_spanish_format(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    now = today()
    due = now - timedelta(days=10)
    with session_factory() as s:
        company = companies.create_company(s, CompanyInput(name="Cliente Web Ficticio"), "raul")
        service_id = catalog.list_services(s)[0].id
        clients.convert_to_client(
            s,
            company.id,
            clients.ContractInput(
                service_id=service_id,
                setup_price_cents=0,
                monthly_fee_cents=12_345,
                start_date=date(now.year - 1, 1, 1),
            ),
            "raul",
        )
        clients.register_invoice(
            s,
            company.id,
            clients.InvoiceInput(
                number="F-WEB-1",
                issue_date=due - timedelta(days=30),
                base_cents=12_000,
                due_date=due,
            ),
            "raul",
        )
    page = auth_client.get("/?tab=clientes").text
    assert euros(12_345) in page  # MRR: 123,45 €
    assert "F-WEB-1" in page
    assert spanish_date(due) in page
    assert euros(14_520) in page  # total con IVA de la factura vencida
