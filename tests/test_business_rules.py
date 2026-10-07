"""Reglas de negocio que faltaban: fases, conversión, MRR, facturas, dinero y demo."""

import re
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from crm.models import Company, Invoice, Phase
from crm.services import catalog, clients, companies, dashboard, demo
from crm.services.clients import ContractInput, InvoiceInput, InvoiceStatus
from crm.services.companies import CompanyInput
from crm.services.errors import NotFoundError, ServiceError
from crm.services.money import parse_euros, total_with_vat, vat_cents

TODAY = date(2026, 10, 7)


def service_id(session: Session, name: str = "Pedidos sin teclear") -> int:
    return next(s.id for s in catalog.list_services(session) if s.name == name)


def contract_data(session: Session, fee: int = 12_000, **kw) -> ContractInput:
    return ContractInput(
        service_id=service_id(session),
        setup_price_cents=200_000,
        monthly_fee_cents=fee,
        start_date=kw.get("start", date(2026, 1, 1)),
        end_date=kw.get("end"),
    )


def new_client(session: Session, name: str = "Quesos Ficticios", fee: int = 12_000, **kw) -> int:
    company = companies.create_company(session, CompanyInput(name=name), "raul")
    clients.convert_to_client(session, company.id, contract_data(session, fee, **kw), "raul")
    return company.id


# --- Fases --------------------------------------------------------------------------------


def test_full_forward_path_through_potential_phases(session: Session) -> None:
    company = companies.create_company(session, CompanyInput(name="Ruta Completa"), "raul")
    for phase in (Phase.CONTACTED, Phase.MEETING, Phase.DIAGNOSIS, Phase.PROPOSAL_SENT):
        assert companies.change_phase(session, company.id, phase.value, "raul").phase == phase


def test_lost_company_can_be_reopened(session: Session) -> None:
    company = companies.create_company(session, CompanyInput(name="Vuelve"), "raul", Phase.LOST)
    reopened = companies.change_phase(session, company.id, Phase.CONTACTED.value, "raul")
    assert reopened.phase == Phase.CONTACTED.value


def test_client_without_active_contracts_can_be_marked_lost(session: Session) -> None:
    company_id = new_client(session)
    contract = companies.get_company(session, company_id).contracts[0]
    clients.cancel_contract(session, contract.id, date(2026, 9, 30), "raul")
    lost = companies.change_phase(session, company_id, Phase.LOST.value, "raul")
    assert lost.phase == Phase.LOST.value


@pytest.mark.parametrize("start", [p for p in Phase if p is not Phase.WON])
def test_convert_to_client_from_any_potential_phase(session: Session, start: Phase) -> None:
    company = companies.create_company(session, CompanyInput(name=f"Conv {start}"), "raul", start)
    contract = clients.convert_to_client(
        session, company.id, contract_data(session, fee=9_000), "lucia"
    )
    session.refresh(company)
    assert company.phase == Phase.WON.value
    assert company.updated_by == "lucia"
    assert contract.company_id == company.id
    assert contract.monthly_fee_cents == 9_000
    assert contract.setup_price_cents == 200_000
    assert contract.service_id == service_id(session)
    assert contract.status == "activo"


def test_create_contract_requires_client_phase(session: Session) -> None:
    company = companies.create_company(session, CompanyInput(name="Aún no cliente"), "raul")
    with pytest.raises(ServiceError, match="6-Ganado"):
        clients.create_contract(session, company.id, contract_data(session), "raul")


# --- MRR ----------------------------------------------------------------------------------


def test_mrr_counts_contract_starting_today_but_not_tomorrow(session: Session) -> None:
    new_client(session, "Empieza hoy", fee=2_500, start=TODAY)
    new_client(session, "Empieza mañana", fee=9_000, start=TODAY + timedelta(days=1))
    assert clients.mrr_cents(session, TODAY) == 2_500
    assert clients.mrr_cents(session, TODAY - timedelta(days=1)) == 0


def test_mrr_sums_several_contracts_and_per_company(session: Session) -> None:
    company_id = new_client(session, fee=12_000)
    clients.create_contract(session, company_id, contract_data(session, fee=2_500), "raul")
    new_client(session, "Otra Empresa Inventada", fee=20_000)
    company = companies.get_company(session, company_id)
    assert clients.company_mrr_cents(company, TODAY) == 14_500
    assert clients.mrr_cents(session, TODAY) == 34_500
    assert isinstance(clients.mrr_cents(session, TODAY), int)


def test_cancelled_contract_with_future_end_keeps_mrr_until_end(session: Session) -> None:
    """Baja avisada hoy con fin el 31/12: el cliente sigue pagando hasta entonces.

    Si falla, el MRR cae a 0 el mismo día en que se registra la baja (ver informe).
    """
    company_id = new_client(session, fee=12_000)
    contract = companies.get_company(session, company_id).contracts[0]
    clients.cancel_contract(session, contract.id, date(2026, 12, 31), "raul")
    assert clients.mrr_cents(session, TODAY) == 12_000
    assert clients.mrr_cents(session, date(2027, 1, 1)) == 0


def test_cancel_contract_before_start_is_rejected(session: Session) -> None:
    company_id = new_client(session, start=date(2026, 6, 1))
    contract = companies.get_company(session, company_id).contracts[0]
    with pytest.raises(ServiceError):
        clients.cancel_contract(session, contract.id, date(2026, 5, 31), "raul")


def test_cancel_unknown_contract_is_not_found(session: Session) -> None:
    with pytest.raises(NotFoundError):
        clients.cancel_contract(session, 999, TODAY, "raul")


# --- Facturas -----------------------------------------------------------------------------


def test_invoice_paid_before_issue_is_rejected_on_register() -> None:
    """`register_payment` lo rechaza; registrar la factura ya cobrada debería ser coherente."""
    with pytest.raises(ValueError):
        InvoiceInput(
            number="F-COBRO-ANTES",
            issue_date=date(2026, 9, 1),
            base_cents=10_000,
            due_date=date(2026, 10, 1),
            paid_date=date(2026, 8, 1),
        )


def test_invoice_due_same_day_as_issue_is_allowed() -> None:
    data = InvoiceInput(number="F-CONTADO", issue_date=TODAY, base_cents=1, due_date=TODAY)
    assert data.due_date == data.issue_date


def test_invoice_with_contract_of_other_company_is_rejected(session: Session) -> None:
    first = new_client(session, "Primera Inventada")
    second = new_client(session, "Segunda Inventada")
    foreign_contract = companies.get_company(session, first).contracts[0].id
    data = InvoiceInput(
        number="F-AJENA",
        contract_id=foreign_contract,
        issue_date=date(2026, 9, 1),
        base_cents=12_000,
        due_date=date(2026, 10, 1),
    )
    with pytest.raises(ServiceError, match="no pertenece"):
        clients.register_invoice(session, second, data, "raul")


def test_register_payment_unknown_invoice_is_not_found(session: Session) -> None:
    with pytest.raises(NotFoundError):
        clients.register_payment(session, 999, TODAY, "raul")


def test_invoice_status_ignores_due_date_once_paid(session: Session) -> None:
    company_id = new_client(session)
    data = InvoiceInput(
        number="F-TARDE",
        issue_date=date(2026, 8, 1),
        base_cents=12_000,
        due_date=date(2026, 9, 1),
        paid_date=date(2026, 10, 6),  # cobrada tarde
    )
    inv = clients.register_invoice(session, company_id, data, "raul")
    assert clients.invoice_status(inv, TODAY) is InvoiceStatus.PAID


def test_clients_summary_due_today_is_pending_and_totals_are_exact(session: Session) -> None:
    company_id = new_client(session)

    def add(number: str, base: int, due: date) -> None:
        data = InvoiceInput(
            number=number, issue_date=date(2026, 9, 1), base_cents=base, due_date=due
        )
        clients.register_invoice(session, company_id, data, "raul")

    # 0,50 € + 21 % = 0,605 -> 0,61 €; con float y redondeo bancario saldría 0,60 €.
    add("F-HOY", 50, TODAY)
    add("F-DIEZ", 10, TODAY)  # 0,10 € + 0,021 € -> 0,12 €
    add("F-VENCIDA", 250, TODAY - timedelta(days=1))  # 2,50 € + 0,525 € -> 3,03 €
    summary = dashboard.clients_summary(session, TODAY)
    assert summary.pending_cents == 61 + 12
    assert summary.overdue_cents == 303
    assert [i.number for i in summary.overdue_invoices] == ["F-VENCIDA"]
    stored = {i.number: i.total_cents for i in session.scalars(select(Invoice))}
    assert stored == {"F-HOY": 61, "F-DIEZ": 12, "F-VENCIDA": 303}


# --- Dinero -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("base", "vat", "expected_vat"),
    [(50, 21, 11), (250, 21, 53), (170_000, 21, 35_700), (1_000_001, 10, 100_000), (99, 4, 4)],
)
def test_vat_rounds_half_up_with_integers(base: int, vat: int, expected_vat: int) -> None:
    assert vat_cents(base, vat) == expected_vat
    assert total_with_vat(base, vat) == base + expected_vat


@pytest.mark.parametrize(("base", "vat"), [(-1, 21), (100, -21)])
def test_vat_rejects_negative(base: int, vat: int) -> None:
    with pytest.raises(ServiceError):
        vat_cents(base, vat)


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("1.234.567,89", 123_456_789),
        ("1.234.567", 123_456_700),
        ("0,10", 10),
        ("2.057,00 €", 205_700),
    ],
)
def test_parse_euros_thousands(text: str, cents: int) -> None:
    assert parse_euros(text) == cents


@pytest.mark.parametrize("text", ["12.34.5", "1.70.0", "0,005", "1,5,0"])
def test_parse_euros_rejects_malformed_groups(text: str) -> None:
    """'1.70.0' no es un importe: hoy se acepta como 1.700 € (ver informe)."""
    with pytest.raises(ServiceError):
        parse_euros(text)


# --- Demo ---------------------------------------------------------------------------------


def test_demo_data_is_fictitious_and_consistent(session: Session) -> None:
    demo.load_demo(session, on=TODAY)
    all_companies = list(session.scalars(select(Company)))
    assert {c.phase for c in all_companies} == {p.value for p in Phase}
    assert all(c.created_by == "demo" for c in all_companies)
    keys = [companies.normalize_name(c.name) for c in all_companies]
    assert len(keys) == len(set(keys))
    phones = [ct.phone for c in all_companies for ct in c.contacts]
    assert phones and all(re.fullmatch(r"600 000 0\d\d", p) for p in phones)
    for inv in session.scalars(select(Invoice)):
        assert inv.total_cents == total_with_vat(inv.base_cents, inv.vat_percent)
        assert inv.paid_date is None or inv.paid_date >= inv.issue_date
    # Todas las empresas en 6-Ganado tienen al menos un contrato.
    assert all(c.contracts for c in all_companies if c.phase == Phase.WON.value)
