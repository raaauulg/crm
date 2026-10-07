"""Tests de humo de la web: login, rutas protegidas, CSRF y páginas principales."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from crm.models import Phase
from crm.services import companies, demo
from crm.services.companies import CompanyInput

from .conftest import csrf_from, login, post_form

PROTECTED = ["/", "/?tab=clientes", "/empresas", "/empresas/nueva"]


@pytest.mark.parametrize("url", PROTECTED)
def test_protected_routes_redirect_to_login(client: TestClient, url: str) -> None:
    response = client.get(url, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_htmx_request_without_session_gets_hx_redirect(client: TestClient) -> None:
    response = client.get("/empresas", headers={"HX-Request": "true"}, follow_redirects=False)
    assert response.headers["HX-Redirect"].startswith("/login")


def test_wrong_password_does_not_log_in(client: TestClient) -> None:
    login(client, password="mala")
    assert client.get("/", follow_redirects=False).status_code == 303


def test_login_and_logout(client: TestClient) -> None:
    login(client)
    assert client.get("/").status_code == 200
    response = post_form(client, "/logout", {})
    assert response.status_code == 303
    assert client.get("/", follow_redirects=False).status_code == 303


def test_login_redirects_only_to_internal_paths(client: TestClient) -> None:
    token = csrf_from(client.get("/login").text)
    response = client.post(
        "/login",
        data={
            "username": "raul",
            "password": "contraseña-de-prueba",
            "csrf_token": token,
            "next": "//malicioso.example",
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/"


def test_post_without_csrf_is_rejected(auth_client: TestClient) -> None:
    response = auth_client.post("/empresas/nueva", data={"name": "Sin token"})
    assert response.status_code == 403


def test_session_cookie_flags(client: TestClient) -> None:
    response = client.get("/login")
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


@pytest.mark.parametrize("url", PROTECTED)
def test_main_pages_render_with_demo_data(
    auth_client: TestClient, session_factory: sessionmaker[Session], url: str
) -> None:
    with session_factory() as s:
        demo.load_demo(s)
    response = auth_client.get(url)
    assert response.status_code == 200
    assert "CRM" in response.text


def test_company_detail_and_edit_render(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as s:
        demo.load_demo(s)
        ids = [c.id for c in companies.search_companies(s)]
    for company_id in ids:
        assert auth_client.get(f"/empresas/{company_id}").status_code == 200
    assert auth_client.get(f"/empresas/{ids[0]}/editar").status_code == 200
    assert auth_client.get("/empresas/99999").status_code == 404


def test_filters_return_only_table_for_htmx(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as s:
        demo.load_demo(s)
    response = auth_client.get(
        "/empresas?fase=6-Ganado", headers={"HX-Request": "true", "HX-Target": "company-table"}
    )
    assert response.status_code == 200
    assert "<html" not in response.text
    assert 'id="company-table"' in response.text


def test_create_company_change_phase_step_and_interaction(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    response = post_form(
        auth_client,
        "/empresas/nueva",
        {"name": "Nueva Prueba", "municipality": "Soria", "estimated_value": "1.700,50"},
    )
    assert response.status_code == 303
    url = response.headers["location"]
    company_id = int(url.rsplit("/", 1)[1])

    post_form(auth_client, f"{url}/fase", {"phase": Phase.MEETING.value})
    post_form(
        auth_client, f"{url}/proximo-paso", {"next_step": "Llamar", "next_step_date": "2026-10-09"}
    )
    post_form(auth_client, f"{url}/interacciones", {"channel": "llamada", "summary": "Hablamos"})
    post_form(auth_client, f"{url}/contactos/nuevo", {"name": "Lucía Ejemplo", "is_primary": "on"})

    with session_factory() as s:
        company = companies.get_company(s, company_id)
        assert company.estimated_value_cents == 170_050
        assert company.phase == Phase.MEETING.value
        assert company.next_step == "Llamar"
        assert company.interactions[0].created_by == "raul"
        assert company.contacts[0].is_primary
    assert "Hablamos" in auth_client.get(url).text


def test_invalid_company_form_shows_error(auth_client: TestClient) -> None:
    response = post_form(auth_client, "/empresas/nueva", {"name": "X", "estimated_value": "abc"})
    assert response.status_code == 200
    assert "Importe no válido" in response.text


def test_duplicate_company_shows_error(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as s:
        companies.create_company(s, CompanyInput(name="Repetida"), "raul")
    response = post_form(auth_client, "/empresas/nueva", {"name": "repetida"})
    assert "Ya existe" in response.text
