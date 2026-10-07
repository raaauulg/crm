"""Nivel 2: conversión a cliente, contratos, facturas y cobros por la web, catálogo, kanban y
serie mensual de los gráficos."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from crm.models import Phase
from crm.services import catalog, clients, companies, dashboard, demo
from crm.services.clients import ContractInput, InvoiceInput
from crm.services.clock import today
from crm.services.companies import CompanyInput

from .conftest import post_form

TODAY = date(2026, 10, 7)


def _service_id(session: Session) -> int:
    return next(s.id for s in catalog.list_services(session) if s.name == "Parte del lunes")


# --- Servicios ---------------------------------------------------------------------------


def test_monthly_revenue_series(session: Session) -> None:
    company = companies.create_company(session, CompanyInput(name="Serie"), "raul")
    contract = clients.convert_to_client(
        session,
        company.id,
        ContractInput(
            service_id=_service_id(session),
            setup_price_cents=0,
            monthly_fee_cents=12_000,
            start_date=date(2026, 8, 15),
        ),
        "raul",
    )
    clients.register_invoice(
        session,
        company.id,
        InvoiceInput(
            number="S-1",
            contract_id=contract.id,
            issue_date=date(2026, 9, 1),
            base_cents=12_000,
            due_date=date(2026, 9, 30),
        ),
        "raul",
    )
    series = dashboard.monthly_revenue(session, months=4, on=TODAY)
    assert [m.month for m in series] == ["2026-07", "2026-08", "2026-09", "2026-10"]
    assert [m.mrr_cents for m in series] == [0, 12_000, 12_000, 12_000]
    assert [m.invoiced_cents for m in series] == [0, 0, 12_000, 0]

    # Cancelar hoy no cambia el histórico de meses pasados.
    clients.cancel_contract(session, contract.id, TODAY, "raul")
    again = dashboard.monthly_revenue(session, months=4, on=TODAY)
    assert [m.mrr_cents for m in again] == [0, 12_000, 12_000, 12_000]


def _contract(session: Session, end: date | None = None) -> int:
    company = companies.create_company(session, CompanyInput(name="Con contrato"), "raul")
    return clients.convert_to_client(
        session,
        company.id,
        ContractInput(
            service_id=_service_id(session),
            setup_price_cents=0,
            monthly_fee_cents=10_000,
            start_date=date(2026, 1, 1),
            end_date=end,
        ),
        "raul",
    ).id


def test_cancel_can_only_shorten_and_only_once(session: Session) -> None:
    import pytest

    from crm.services.errors import ServiceError

    finished = _contract(session, end=date(2026, 6, 30))
    with pytest.raises(ServiceError, match="posterior"):
        clients.cancel_contract(session, finished, TODAY, "raul")
    contract = clients.cancel_contract(session, finished, date(2026, 5, 31), "raul")
    assert contract.end_date == date(2026, 5, 31)
    with pytest.raises(ServiceError, match="ya está cancelado"):
        clients.cancel_contract(session, finished, date(2026, 5, 1), "raul")


def test_future_payment_dates_are_rejected(session: Session) -> None:
    import pytest

    from crm.services.errors import ServiceError

    contract_id = _contract(session)
    company_id = clients.get_contract(session, contract_id).company_id
    tomorrow = date.fromordinal(today().toordinal() + 1)
    data = InvoiceInput(
        number="FUT-1",
        issue_date=date(2026, 1, 1),
        base_cents=100,
        due_date=date(2026, 2, 1),
        paid_date=tomorrow,
    )
    with pytest.raises(ServiceError, match="futura"):
        clients.register_invoice(session, company_id, data, "raul")
    invoice = clients.register_invoice(
        session, company_id, data.model_copy(update={"paid_date": None}), "raul"
    )
    with pytest.raises(ServiceError, match="futura"):
        clients.register_payment(session, invoice.id, tomorrow, "raul")


def test_search_ignores_accents_and_like_wildcards(session: Session) -> None:
    companies.create_company(session, CompanyInput(name="Panadería Ágreda"), "raul")
    companies.create_company(session, CompanyInput(name="Taller 100% Soria"), "raul")
    assert [c.name for c in companies.search_companies(session, text="panaderia agreda")] == [
        "Panadería Ágreda"
    ]
    assert [c.name for c in companies.search_companies(session, text="ÁGREDA")] == [
        "Panadería Ágreda"
    ]
    # "%" y "_" no son comodines: "_" se ignora como signo, no casa con cualquier letra.
    assert companies.search_companies(session, text="%") == companies.search_companies(session)
    assert companies.search_companies(session, text="p_n") == []


def test_list_invoices_by_status(session: Session) -> None:
    contract_id = _contract(session)
    company_id = clients.get_contract(session, contract_id).company_id
    for number, due, paid in (
        ("A", date(2026, 9, 1), None),
        ("B", date(2026, 12, 1), None),
        ("C", date(2026, 9, 1), date(2026, 9, 2)),
    ):
        clients.register_invoice(
            session,
            company_id,
            InvoiceInput(
                number=number,
                issue_date=date(2026, 8, 1),
                base_cents=1,
                due_date=due,
                paid_date=paid,
            ),
            "raul",
        )
    by = clients.InvoiceStatus
    assert [i.number for i in clients.list_invoices(session, status=by.OVERDUE, on=TODAY)] == ["A"]
    assert [i.number for i in clients.list_invoices(session, status=by.PENDING, on=TODAY)] == ["B"]
    assert [i.number for i in clients.list_invoices(session, status=by.PAID, on=TODAY)] == ["C"]


def test_monthly_revenue_crosses_year_boundary(session: Session) -> None:
    series = dashboard.monthly_revenue(session, months=3, on=date(2027, 1, 10))
    assert [m.month for m in series] == ["2026-11", "2026-12", "2027-01"]


def test_kanban_board_and_neighbours(session: Session) -> None:
    demo.load_demo(session, on=TODAY)
    board = companies.kanban_board(session)
    assert list(board) == [p.value for p in companies.KANBAN_PHASES]
    assert all(c.phase == phase for phase, cards in board.items() for c in cards)
    assert companies.neighbour_phases(Phase.LEAD.value) == (None, Phase.IDENTIFIED)
    assert companies.neighbour_phases(Phase.IDENTIFIED.value) == (None, Phase.CONTACTED)
    assert companies.neighbour_phases(Phase.PROPOSAL_SENT.value) == (Phase.DIAGNOSIS, None)
    assert companies.neighbour_phases(Phase.WON.value) == (None, None)


def test_save_service_creates_updates_and_rejects_duplicates(session: Session) -> None:
    created = catalog.save_service(session, "Servicio nuevo", 10_000, 1_000)
    updated = catalog.save_service(
        session, "Servicio renombrado", 20_000, 0, active=False, service_id=created.id
    )
    assert (updated.name, updated.setup_price_cents, updated.active) == (
        "Servicio renombrado",
        20_000,
        False,
    )
    assert updated not in catalog.list_services(session, only_active=True)
    try:
        catalog.save_service(session, "Web sencilla", 0, 0)
    except ValueError as exc:
        assert "Ya existe" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("debía rechazar el duplicado")


# --- Web ---------------------------------------------------------------------------------


def test_convert_contract_invoice_and_payment_via_web(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as s:
        company = companies.create_company(s, CompanyInput(name="Futuro Cliente"), "raul")
        service_id = _service_id(s)
    url = f"/empresas/{company.id}"

    page = auth_client.get(f"{url}/convertir")
    assert page.status_code == 200
    response = post_form(
        auth_client,
        f"{url}/convertir",
        {
            "service_id": str(service_id),
            "setup_price": "2.400",
            "monthly_fee": "120",
            "start_date": "2026-01-01",
            "commitment_months": "12",
        },
    )
    assert response.status_code == 303

    post_form(
        auth_client,
        f"{url}/facturas/nueva",
        {
            "number": "2026-001",
            "issue_date": "2026-09-01",
            "due_date": "2026-09-30",
            "base": "120",
            "vat_percent": "21",
        },
    )
    with session_factory() as s:
        company_db = companies.get_company(s, company.id)
        assert company_db.phase == Phase.WON.value
        assert company_db.contracts[0].monthly_fee_cents == 12_000
        invoice = company_db.invoices[0]
        assert invoice.total_cents == 14_520
        invoice_id = invoice.id
        contract_id = company_db.contracts[0].id

    detail = auth_client.get(url).text
    assert "2026-001" in detail and "vencida" in detail

    post_form(auth_client, f"/facturas/{invoice_id}/cobro", {})
    post_form(auth_client, f"/contratos/{contract_id}/cancelar", {"end_date": "2026-12-31"})
    with session_factory() as s:
        company_db = companies.get_company(s, company.id)
        assert company_db.invoices[0].paid_date == today()
        assert company_db.contracts[0].end_date == date(2026, 12, 31)


def test_convert_with_invalid_data_shows_error(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as s:
        company = companies.create_company(s, CompanyInput(name="Error"), "raul")
    response = post_form(
        auth_client,
        f"/empresas/{company.id}/convertir",
        {"service_id": "", "setup_price": "x", "monthly_fee": "", "start_date": ""},
    )
    assert response.status_code == 200
    assert "no válid" in response.text.lower()


def test_invoice_list_filters_by_status(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as s:
        demo.load_demo(s)
    for estado in ("", "cobrada", "pendiente", "vencida", "inventado"):
        assert auth_client.get(f"/facturas?estado={estado}").status_code == 200
    assert "DEMO-" in auth_client.get("/facturas?estado=vencida").text


def test_catalog_page_and_edit(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    assert "Albaranes y facturas sin teclear" in auth_client.get("/servicios").text
    post_form(auth_client, "/servicios", {"name": "Bot de WhatsApp", "setup_price": "1.500"})
    with session_factory() as s:
        created = next(x for x in catalog.list_services(s) if x.name == "Bot de WhatsApp")
        assert created.setup_price_cents == 150_000
    post_form(
        auth_client,
        f"/servicios/{created.id}",
        {"name": "Bot de WhatsApp", "setup_price": "1.600", "monthly_fee": "50"},
    )
    with session_factory() as s:
        edited = catalog.get_service(s, created.id)
        assert (edited.setup_price_cents, edited.monthly_fee_cents, edited.active) == (
            160_000,
            5_000,
            False,  # casilla "activo" sin marcar
        )


def test_kanban_renders_and_moves_back_to_kanban(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as s:
        demo.load_demo(s)
        card = companies.kanban_board(s)[Phase.MEETING.value][0]
    page = auth_client.get("/kanban")
    assert page.status_code == 200
    assert card.name in page.text
    response = post_form(
        auth_client,
        f"/empresas/{card.id}/fase",
        {"phase": Phase.DIAGNOSIS.value, "back": "/kanban"},
    )
    assert response.headers["location"] == "/kanban"


def test_dashboard_clients_tab_has_charts(
    auth_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as s:
        demo.load_demo(s)
    html = auth_client.get("/?tab=clientes").text
    assert 'id="mrr-chart"' in html and 'id="revenue-chart"' in html
    assert 'id="funnel-chart"' in auth_client.get("/").text
