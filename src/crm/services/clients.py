"""Clientes: conversión, contratos, MRR, facturas (solo registro) y cobros."""

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from crm.models import Company, Contract, ContractStatus, Invoice, Phase
from crm.services.catalog import get_service
from crm.services.clock import today
from crm.services.companies import get_company
from crm.services.errors import NotFoundError, ServiceError
from crm.services.money import total_with_vat
from crm.services.validation import InputModel


class InvoiceStatus(StrEnum):
    PAID = "cobrada"
    PENDING = "pendiente"
    OVERDUE = "vencida"


class ContractInput(InputModel):
    service_id: int
    setup_price_cents: int = Field(ge=0)
    monthly_fee_cents: int = Field(ge=0)
    start_date: date
    commitment_months: int = Field(default=0, ge=0, le=120)
    end_date: date | None = None

    @model_validator(mode="after")
    def _end_after_start(self) -> "ContractInput":
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("la fecha de fin no puede ser anterior a la de inicio")
        return self


class InvoiceInput(InputModel):
    number: str = Field(min_length=1, max_length=50)
    contract_id: int | None = None
    issue_date: date
    base_cents: int = Field(ge=0)
    vat_percent: int = Field(default=21, ge=0, le=100)
    due_date: date
    paid_date: date | None = None

    @model_validator(mode="after")
    def _due_after_issue(self) -> "InvoiceInput":
        if self.due_date < self.issue_date:
            raise ValueError("el vencimiento no puede ser anterior a la emisión")
        if self.paid_date is not None and self.paid_date < self.issue_date:
            raise ValueError("el cobro no puede ser anterior a la emisión")
        return self


# --- Contratos y MRR -------------------------------------------------------------------


def contract_is_active(contract: Contract, on: date) -> bool:
    """Activo en una fecha = ya empezado y sin terminar (el día de fin aún cuenta).

    Solo mandan las fechas: una baja registrada hoy con fin el 31/12 sigue sumando al MRR
    hasta el 31/12, y el histórico de meses pasados no cambia al cancelar. El estado
    `cancelado` solo indica que la baja ya está registrada (y siempre lleva fecha de fin).
    """
    return contract.start_date <= on and (contract.end_date is None or contract.end_date >= on)


def mrr_cents(session: Session, on: date | None = None) -> int:
    """MRR: suma de las cuotas mensuales de los contratos activos en la fecha (hoy por defecto)."""
    on = on or today()
    contracts = session.scalars(select(Contract))
    return sum(c.monthly_fee_cents for c in contracts if contract_is_active(c, on))


def company_mrr_cents(company: Company, on: date | None = None) -> int:
    on = on or today()
    return sum(c.monthly_fee_cents for c in company.contracts if contract_is_active(c, on))


def create_contract(
    session: Session, company_id: int, data: ContractInput, actor: str, *, commit: bool = True
) -> Contract:
    company = get_company(session, company_id)
    if company.phase != Phase.WON.value:
        raise ServiceError("Solo se pueden dar de alta contratos a clientes (fase 6-Ganado).")
    get_service(session, data.service_id)
    contract = Contract(**data.model_dump(), company=company, created_by=actor, updated_by=actor)
    session.add(contract)
    if commit:
        session.commit()
    return contract


def convert_to_client(
    session: Session, company_id: int, data: ContractInput, actor: str
) -> Contract:
    """Pasa la empresa a 6-Ganado y crea su primer contrato, todo en una transacción."""
    company = get_company(session, company_id)
    if company.phase == Phase.WON.value:
        raise ServiceError("La empresa ya es cliente: añade el contrato desde su ficha.")
    company.phase = Phase.WON.value
    company.updated_by = actor
    try:
        contract = create_contract(session, company_id, data, actor, commit=False)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return contract


def get_contract(session: Session, contract_id: int) -> Contract:
    contract = session.get(Contract, contract_id)
    if contract is None:
        raise NotFoundError(f"No existe el contrato {contract_id}.")
    return contract


def get_invoice(session: Session, invoice_id: int) -> Invoice:
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError(f"No existe la factura {invoice_id}.")
    return invoice


def cancel_contract(session: Session, contract_id: int, end_date: date, actor: str) -> Contract:
    contract = session.get(Contract, contract_id)
    if contract is None:
        raise NotFoundError(f"No existe el contrato {contract_id}.")
    if end_date < contract.start_date:
        raise ServiceError("La fecha de fin no puede ser anterior a la de inicio.")
    contract.status = ContractStatus.CANCELLED.value
    contract.end_date = end_date
    contract.updated_by = actor
    session.commit()
    return contract


# --- Facturas ----------------------------------------------------------------------------


def invoice_status(invoice: Invoice, on: date | None = None) -> InvoiceStatus:
    """Cobrada si tiene fecha de cobro; vencida si no y el vencimiento ya pasó; si no, pendiente.

    El mismo día del vencimiento sigue pendiente.
    """
    on = on or today()
    if invoice.paid_date is not None:
        return InvoiceStatus.PAID
    if invoice.due_date < on:
        return InvoiceStatus.OVERDUE
    return InvoiceStatus.PENDING


def register_invoice(session: Session, company_id: int, data: InvoiceInput, actor: str) -> Invoice:
    company = get_company(session, company_id)
    if data.paid_date is not None and data.paid_date > today():
        raise ServiceError("La fecha de cobro no puede ser futura.")
    if session.scalar(select(Invoice).where(Invoice.number == data.number)):
        raise ServiceError(f"Ya hay una factura con el número {data.number!r}.")
    if data.contract_id is not None:
        contract = session.get(Contract, data.contract_id)
        if contract is None or contract.company_id != company.id:
            raise ServiceError("El contrato no pertenece a esta empresa.")
    invoice = Invoice(
        **data.model_dump(),
        company=company,
        total_cents=total_with_vat(data.base_cents, data.vat_percent),
        created_by=actor,
        updated_by=actor,
    )
    session.add(invoice)
    session.commit()
    return invoice


def register_payment(session: Session, invoice_id: int, paid_on: date, actor: str) -> Invoice:
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError(f"No existe la factura {invoice_id}.")
    if invoice.paid_date is not None:
        raise ServiceError("La factura ya está cobrada.")
    if paid_on > today():
        raise ServiceError("La fecha de cobro no puede ser futura.")
    if paid_on < invoice.issue_date:
        raise ServiceError("La fecha de cobro no puede ser anterior a la de emisión.")
    invoice.paid_date = paid_on
    invoice.updated_by = actor
    session.commit()
    return invoice


def list_invoices(session: Session, company_id: int | None = None) -> list[Invoice]:
    query = select(Invoice).order_by(Invoice.issue_date.desc(), Invoice.id.desc())
    if company_id is not None:
        query = query.where(Invoice.company_id == company_id)
    return list(session.scalars(query))
