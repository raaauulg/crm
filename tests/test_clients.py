from datetime import date

import pytest
from sqlalchemy.orm import Session

from crm.models import Phase
from crm.services import catalog, clients, companies
from crm.services.clients import ContractInput, InvoiceInput, InvoiceStatus
from crm.services.companies import CompanyInput
from crm.services.errors import ServiceError

TODAY = date(2026, 10, 7)


def service_id(session: Session, name: str = "Pedidos sin teclear") -> int:
    return next(s.id for s in catalog.list_services(session) if s.name == name)


def new_client(session: Session, name: str = "Cliente Prueba", fee: int = 12_000, **kw) -> int:
    company = companies.create_company(session, CompanyInput(name=name), "raul")
    data = ContractInput(
        service_id=service_id(session),
        setup_price_cents=200_000,
        monthly_fee_cents=fee,
        start_date=kw.get("start", date(2026, 1, 1)),
        end_date=kw.get("end"),
    )
    clients.convert_to_client(session, company.id, data, "raul")
    return company.id


# --- Conversión y MRR --------------------------------------------------------------------


def test_convert_to_client_sets_won_and_creates_contract(session: Session) -> None:
    company_id = new_client(session)
    company = companies.get_company(session, company_id)
    assert company.phase == Phase.WON.value
    assert len(company.contracts) == 1
    assert company.contracts[0].created_by == "raul"


def test_convert_twice_is_an_error(session: Session) -> None:
    company_id = new_client(session)
    data = ContractInput(
        service_id=service_id(session),
        setup_price_cents=0,
        monthly_fee_cents=0,
        start_date=TODAY,
    )
    with pytest.raises(ServiceError):
        clients.convert_to_client(session, company_id, data, "raul")


def test_failed_conversion_leaves_company_untouched(session: Session) -> None:
    company = companies.create_company(session, CompanyInput(name="Sin servicio"), "raul")
    data = ContractInput(
        service_id=9999, setup_price_cents=0, monthly_fee_cents=0, start_date=TODAY
    )
    with pytest.raises(ServiceError):
        clients.convert_to_client(session, company.id, data, "raul")
    session.expire_all()
    assert companies.get_company(session, company.id).phase == Phase.IDENTIFIED.value


def test_mrr_without_contracts_is_zero(session: Session) -> None:
    assert clients.mrr_cents(session, TODAY) == 0


def test_mrr_counts_only_contracts_active_on_the_date(session: Session) -> None:
    new_client(session, "Activo", fee=12_000)
    new_client(session, "Futuro", fee=9_000, start=date(2026, 11, 1))
    new_client(session, "Terminado", fee=20_000, end=date(2026, 10, 6))
    new_client(session, "Termina hoy", fee=2_500, end=TODAY)
    assert clients.mrr_cents(session, TODAY) == 12_000 + 2_500


def test_cancelled_contract_leaves_mrr(session: Session) -> None:
    company_id = new_client(session, fee=12_000)
    contract = companies.get_company(session, company_id).contracts[0]
    clients.cancel_contract(session, contract.id, date(2026, 9, 30), "raul")
    assert clients.mrr_cents(session, TODAY) == 0


def test_client_with_active_contract_cannot_change_phase(session: Session) -> None:
    company_id = new_client(session)
    with pytest.raises(ServiceError, match="contratos activos"):
        companies.change_phase(session, company_id, Phase.LOST.value, "raul")


def test_contract_end_before_start_is_rejected() -> None:
    with pytest.raises(ValueError):
        ContractInput(
            service_id=1,
            setup_price_cents=0,
            monthly_fee_cents=0,
            start_date=TODAY,
            end_date=date(2026, 1, 1),
        )


# --- Facturas ----------------------------------------------------------------------------


def invoice(session: Session, company_id: int, number: str = "F-1", **kw) -> int:
    data = InvoiceInput(
        number=number,
        issue_date=kw.get("issue", date(2026, 9, 1)),
        base_cents=kw.get("base", 12_000),
        vat_percent=kw.get("vat", 21),
        due_date=kw.get("due", date(2026, 10, 1)),
        paid_date=kw.get("paid"),
    )
    return clients.register_invoice(session, company_id, data, "raul").id


@pytest.mark.parametrize(
    ("due", "paid", "expected"),
    [
        (date(2026, 10, 1), None, InvoiceStatus.OVERDUE),
        (TODAY, None, InvoiceStatus.PENDING),  # el día del vencimiento aún no está vencida
        (date(2026, 10, 30), None, InvoiceStatus.PENDING),
        (date(2026, 10, 1), date(2026, 10, 5), InvoiceStatus.PAID),
    ],
)
def test_invoice_status(session: Session, due: date, paid: date | None, expected: str) -> None:
    company_id = new_client(session)
    inv_id = invoice(session, company_id, due=due, paid=paid)
    inv = next(i for i in clients.list_invoices(session) if i.id == inv_id)
    assert clients.invoice_status(inv, TODAY) is expected


@pytest.mark.parametrize(
    ("base", "vat", "total"),
    [(12_000, 21, 14_520), (1, 21, 1), (3, 21, 4), (10_005, 10, 11_006), (999, 0, 999)],
)
def test_invoice_total_rounds_vat_half_up(
    session: Session, base: int, vat: int, total: int
) -> None:
    company_id = new_client(session)
    inv_id = invoice(session, company_id, base=base, vat=vat)
    assert next(i for i in clients.list_invoices(session) if i.id == inv_id).total_cents == total


def test_duplicate_invoice_number_is_rejected(session: Session) -> None:
    company_id = new_client(session)
    invoice(session, company_id, "F-1")
    with pytest.raises(ServiceError):
        invoice(session, company_id, "F-1")


def test_register_payment(session: Session) -> None:
    company_id = new_client(session)
    inv_id = invoice(session, company_id)
    paid = clients.register_payment(session, inv_id, date(2026, 10, 3), "raul")
    assert clients.invoice_status(paid, TODAY) is InvoiceStatus.PAID
    with pytest.raises(ServiceError, match="ya está cobrada"):
        clients.register_payment(session, inv_id, TODAY, "raul")


def test_payment_before_issue_is_rejected(session: Session) -> None:
    company_id = new_client(session)
    inv_id = invoice(session, company_id, issue=date(2026, 9, 1))
    with pytest.raises(ServiceError):
        clients.register_payment(session, inv_id, date(2026, 8, 1), "raul")


def test_invoice_due_before_issue_is_rejected() -> None:
    with pytest.raises(ValueError):
        InvoiceInput(number="X", issue_date=TODAY, base_cents=1, due_date=date(2026, 1, 1))
