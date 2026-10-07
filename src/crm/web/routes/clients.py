"""Clientes: convertir en cliente, contratos, facturas (solo registro) y cobros."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from crm.models import Company, User
from crm.services import catalog, clients, companies
from crm.services.clients import ContractInput, InvoiceInput, InvoiceStatus
from crm.services.clock import today
from crm.services.errors import ServiceError
from crm.services.validation import validate
from crm.web.deps import (
    actor,
    csrf_protect,
    flash,
    form_date,
    form_euros,
    form_int,
    form_str,
    get_session,
    redirect,
    render,
    require_user,
)

router = APIRouter(dependencies=[Depends(require_user), Depends(csrf_protect)])


def _contract_data(form: FormData) -> ContractInput:
    data: dict[str, Any] = {
        "service_id": form_int(form, "service_id"),
        "setup_price_cents": form_euros(form, "setup_price"),
        "monthly_fee_cents": form_euros(form, "monthly_fee"),
        "start_date": form_date(form, "start_date"),
        "commitment_months": form_int(form, "commitment_months") or 0,
        "end_date": form_date(form, "end_date"),
    }
    return validate(ContractInput, data)


def _contract_defaults(company: Company) -> dict[str, Any]:
    """Valores iniciales del formulario: el servicio de interés y sus precios de referencia."""
    service = company.service
    return {
        "service_id": service.id if service else None,
        "setup_price_cents": service.setup_price_cents if service else None,
        "monthly_fee_cents": (
            company.estimated_fee_cents
            if company.estimated_fee_cents is not None
            else (service.monthly_fee_cents if service else None)
        ),
        "start_date": today(),
        "commitment_months": 12,
    }


def _contract_page(
    request: Request,
    session: Session,
    company: Company,
    converting: bool,
    form: FormData | None = None,
    error: str | None = None,
) -> Response:
    context = {
        "company": company,
        "converting": converting,
        "services": catalog.list_services(session, only_active=True),
        "defaults": _contract_defaults(company),
        "form": form or {},
        "error": error,
    }
    return render(request, "clients/contract_form.html", context)


@router.get("/empresas/{company_id}/convertir")
def convert_form(
    request: Request, company_id: int, session: Session = Depends(get_session)
) -> Response:
    company = companies.get_company(session, company_id)
    return _contract_page(request, session, company, converting=True)


@router.post("/empresas/{company_id}/convertir")
async def convert(
    request: Request,
    company_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> Response:
    company = companies.get_company(session, company_id)
    form = await request.form()
    try:
        clients.convert_to_client(session, company_id, _contract_data(form), actor(user))
    except ServiceError as exc:
        session.rollback()
        return _contract_page(request, session, company, True, form, str(exc))
    flash(request, f"¡{company.name} ya es cliente!")
    return redirect(request, f"/empresas/{company_id}")


@router.get("/empresas/{company_id}/contratos/nuevo")
def new_contract_form(
    request: Request, company_id: int, session: Session = Depends(get_session)
) -> Response:
    company = companies.get_company(session, company_id)
    return _contract_page(request, session, company, converting=False)


@router.post("/empresas/{company_id}/contratos/nuevo")
async def create_contract(
    request: Request,
    company_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> Response:
    company = companies.get_company(session, company_id)
    form = await request.form()
    try:
        clients.create_contract(session, company_id, _contract_data(form), actor(user))
    except ServiceError as exc:
        session.rollback()
        return _contract_page(request, session, company, False, form, str(exc))
    flash(request, "Contrato añadido.")
    return redirect(request, f"/empresas/{company_id}")


@router.post("/contratos/{contract_id}/cancelar")
async def cancel_contract(
    request: Request,
    contract_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> Response:
    contract = clients.get_contract(session, contract_id)
    form = await request.form()
    try:
        end = form_date(form, "end_date") or today()
        clients.cancel_contract(session, contract_id, end, actor(user))
        flash(request, "Contrato cancelado.")
    except ServiceError as exc:
        session.rollback()
        flash(request, str(exc), "error")
    return redirect(request, f"/empresas/{contract.company_id}")


def _invoice_page(
    request: Request,
    company: Company,
    form: FormData | None = None,
    error: str | None = None,
) -> Response:
    active = [c for c in company.contracts if clients.contract_is_active(c, today())]
    defaults = {
        "contract_id": active[0].id if active else None,
        "base_cents": active[0].monthly_fee_cents if active else None,
        "issue_date": today(),
    }
    context = {
        "company": company,
        "contracts": company.contracts,
        "defaults": defaults,
        "form": form or {},
        "error": error,
    }
    return render(request, "clients/invoice_form.html", context)


@router.get("/empresas/{company_id}/facturas/nueva")
def new_invoice_form(
    request: Request, company_id: int, session: Session = Depends(get_session)
) -> Response:
    return _invoice_page(request, companies.get_company(session, company_id))


@router.post("/empresas/{company_id}/facturas/nueva")
async def create_invoice(
    request: Request,
    company_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> Response:
    company = companies.get_company(session, company_id)
    form = await request.form()
    try:
        data = validate(
            InvoiceInput,
            {
                "number": form_str(form, "number"),
                "contract_id": form_int(form, "contract_id"),
                "issue_date": form_date(form, "issue_date"),
                "base_cents": form_euros(form, "base"),
                "vat_percent": form_int(form, "vat_percent")
                if form_str(form, "vat_percent")
                else 21,
                "due_date": form_date(form, "due_date"),
                "paid_date": form_date(form, "paid_date"),
            },
        )
        clients.register_invoice(session, company_id, data, actor(user))
    except ServiceError as exc:
        session.rollback()
        return _invoice_page(request, company, form, str(exc))
    flash(request, "Factura registrada.")
    return redirect(request, f"/empresas/{company_id}")


@router.post("/facturas/{invoice_id}/cobro")
async def register_payment(
    request: Request,
    invoice_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> Response:
    invoice = clients.get_invoice(session, invoice_id)
    form = await request.form()
    try:
        paid_on = form_date(form, "paid_date") or today()
        clients.register_payment(session, invoice_id, paid_on, actor(user))
        flash(request, f"Factura {invoice.number} marcada como cobrada.")
    except ServiceError as exc:
        session.rollback()
        flash(request, str(exc), "error")
    back = (
        "/facturas" if form_str(form, "back") == "/facturas" else f"/empresas/{invoice.company_id}"
    )
    return redirect(request, back)


@router.get("/facturas")
def invoice_list(
    request: Request, estado: str = "", session: Session = Depends(get_session)
) -> Response:
    rows = [(inv, clients.invoice_status(inv)) for inv in clients.list_invoices(session)]
    if estado in {s.value for s in InvoiceStatus}:
        rows = [(inv, st) for inv, st in rows if st.value == estado]
    context = {"rows": rows, "estado": estado, "statuses": list(InvoiceStatus)}
    return render(request, "clients/invoices.html", context)
