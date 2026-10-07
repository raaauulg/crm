"""Empresas: tabla, ficha, formularios, fase, próximo paso, contactos e interacciones."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from crm.models import Channel, Contact, Phase, User
from crm.services import catalog, clients, companies
from crm.services.clock import today
from crm.services.companies import CompanyInput, ContactInput, InteractionInput
from crm.services.errors import NotFoundError, ServiceError
from crm.services.validation import validate
from crm.web.deps import (
    actor,
    csrf_protect,
    flash,
    form_bool,
    form_date,
    form_euros,
    form_int,
    form_str,
    get_session,
    redirect,
    render,
    require_user,
    safe_path,
)

router = APIRouter(prefix="/empresas", dependencies=[Depends(require_user), Depends(csrf_protect)])

COMPANY_TEXT_FIELDS = ("name", "sector", "municipality", "website", "phone", "source", "notes")
CONTACT_TEXT_FIELDS = ("name", "role", "phone", "email", "data_source")


def _company_data(form: FormData) -> CompanyInput:
    data: dict[str, Any] = {field: form_str(form, field) for field in COMPANY_TEXT_FIELDS}
    data.update(
        service_id=form_int(form, "service_id"),
        estimated_value_cents=form_euros(form, "estimated_value"),
        estimated_fee_cents=form_euros(form, "estimated_fee"),
        pain_score=form_int(form, "pain_score"),
        next_step=form_str(form, "next_step"),
        next_step_date=form_date(form, "next_step_date"),
    )
    return validate(CompanyInput, data)


def _contact_data(form: FormData) -> ContactInput:
    data: dict[str, Any] = {field: form_str(form, field) for field in CONTACT_TEXT_FIELDS}
    data.update(is_primary=form_bool(form, "is_primary"), data_date=form_date(form, "data_date"))
    return validate(ContactInput, data)


def _company_contact(session: Session, company_id: int, contact_id: int) -> Contact:
    contact = companies.get_contact(session, contact_id)
    if contact.company_id != company_id:
        raise NotFoundError(f"El contacto {contact_id} no es de esta empresa.")
    return contact


def _filters(request: Request) -> dict[str, str]:
    params = request.query_params
    return {
        "text": params.get("q", ""),
        "phase": params.get("fase", ""),
        "sector": params.get("sector", ""),
        "municipality": params.get("municipio", ""),
        "group": params.get("grupo", ""),
        "sort": params.get("orden", "name"),
        "descending": params.get("dir", "asc"),
    }


@router.get("")
def company_list(request: Request, session: Session = Depends(get_session)) -> Response:
    filters = _filters(request)
    rows = companies.search_companies(
        session,
        text=filters["text"],
        phase=filters["phase"],
        sector=filters["sector"],
        municipality=filters["municipality"],
        group=filters["group"],
        sort=filters["sort"],
        descending=filters["descending"] == "desc",
    )
    context = {
        "companies": rows,
        "filters": filters,
        "phases": list(Phase),
        "sectors": companies.distinct_values(session, "sector"),
        "municipalities": companies.distinct_values(session, "municipality"),
    }
    # Con HTMX (filtros en vivo) solo se devuelve la tabla, no la página entera.
    is_filter_request = request.headers.get("HX-Target") == "company-table"
    template = "companies/_table.html" if is_filter_request else "companies/list.html"
    return render(request, template, context)


def _form_context(session: Session, **extra: Any) -> dict[str, Any]:
    services = catalog.list_services(session, only_active=True)
    company = extra.get("company")
    # Si el servicio de interés se desactivó, se sigue ofreciendo para no perderlo al guardar.
    if company is not None and company.service is not None and company.service not in services:
        services.append(company.service)
    return {"services": services, "error": None, **extra}


@router.get("/nueva")
def new_company_form(request: Request, session: Session = Depends(get_session)) -> Response:
    return render(request, "companies/form.html", _form_context(session, company=None, form={}))


@router.post("/nueva")
async def create_company(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> Response:
    form = await request.form()
    try:
        company = companies.create_company(session, _company_data(form), actor(user))
    except ServiceError as exc:
        session.rollback()
        context = _form_context(session, company=None, form=form, error=str(exc))
        return render(request, "companies/form.html", context)
    flash(request, f"Empresa «{company.name}» creada.")
    return redirect(request, f"/empresas/{company.id}")


@router.get("/{company_id}")
def company_detail(
    request: Request, company_id: int, session: Session = Depends(get_session)
) -> Response:
    company = companies.get_company(session, company_id)
    invoices = [(inv, clients.invoice_status(inv)) for inv in company.invoices]
    context = {
        "company": company,
        "phase_targets": [p for p in companies.PHASE_CHANGE_TARGETS if p.value != company.phase],
        "channels": list(Channel),
        "is_client": company.phase == Phase.WON.value,
        "mrr": clients.company_mrr_cents(company),
        "invoices": invoices,
        "active_contract_ids": {
            c.id for c in company.contracts if clients.contract_is_active(c, today())
        },
    }
    return render(request, "companies/detail.html", context)


@router.get("/{company_id}/editar")
def edit_company_form(
    request: Request, company_id: int, session: Session = Depends(get_session)
) -> Response:
    company = companies.get_company(session, company_id)
    return render(request, "companies/form.html", _form_context(session, company=company, form={}))


@router.post("/{company_id}/editar")
async def update_company(
    request: Request,
    company_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> Response:
    company = companies.get_company(session, company_id)
    form = await request.form()
    try:
        companies.update_company(session, company_id, _company_data(form), actor(user))
    except ServiceError as exc:
        session.rollback()
        context = _form_context(session, company=company, form=form, error=str(exc))
        return render(request, "companies/form.html", context)
    flash(request, "Cambios guardados.")
    return redirect(request, f"/empresas/{company_id}")


@router.post("/{company_id}/fase")
async def change_phase(
    request: Request,
    company_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> Response:
    form = await request.form()
    try:
        company = companies.change_phase(session, company_id, form_str(form, "phase"), actor(user))
        flash(request, f"Fase cambiada a {company.phase}.")
    except ServiceError as exc:
        session.rollback()
        flash(request, str(exc), "error")
    return redirect(request, safe_path(form_str(form, "back"), f"/empresas/{company_id}"))


@router.post("/{company_id}/proximo-paso")
async def set_next_step(
    request: Request,
    company_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> Response:
    form = await request.form()
    try:
        when = form_date(form, "next_step_date")
        companies.set_next_step(session, company_id, form_str(form, "next_step"), when, actor(user))
        flash(request, "Próximo paso guardado.")
    except ServiceError as exc:
        session.rollback()
        flash(request, str(exc), "error")
    return redirect(request, f"/empresas/{company_id}")


@router.post("/{company_id}/interacciones")
async def add_interaction(
    request: Request,
    company_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> Response:
    form = await request.form()
    try:
        data = validate(
            InteractionInput,
            {
                "occurred_on": form_date(form, "occurred_on") or today(),
                "channel": form_str(form, "channel"),
                "summary": form_str(form, "summary"),
                "result": form_str(form, "result"),
            },
        )
        companies.add_interaction(session, company_id, data, actor(user))
        flash(request, "Interacción registrada.")
    except ServiceError as exc:
        session.rollback()
        flash(request, str(exc), "error")
    return redirect(request, f"/empresas/{company_id}#historial")


@router.get("/{company_id}/contactos/nuevo")
def new_contact_form(
    request: Request, company_id: int, session: Session = Depends(get_session)
) -> Response:
    company = companies.get_company(session, company_id)
    context = {"company": company, "contact": None, "form": {}, "error": None}
    return render(request, "companies/contact_form.html", context)


@router.post("/{company_id}/contactos/nuevo")
async def create_contact(
    request: Request,
    company_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> Response:
    company = companies.get_company(session, company_id)
    form = await request.form()
    try:
        companies.add_contact(session, company_id, _contact_data(form), actor(user))
    except ServiceError as exc:
        session.rollback()
        context = {"company": company, "contact": None, "form": form, "error": str(exc)}
        return render(request, "companies/contact_form.html", context)
    flash(request, "Contacto añadido.")
    return redirect(request, f"/empresas/{company_id}")


@router.get("/{company_id}/contactos/{contact_id}/editar")
def edit_contact_form(
    request: Request, company_id: int, contact_id: int, session: Session = Depends(get_session)
) -> Response:
    company = companies.get_company(session, company_id)
    contact = _company_contact(session, company_id, contact_id)
    context = {"company": company, "contact": contact, "form": {}, "error": None}
    return render(request, "companies/contact_form.html", context)


@router.post("/{company_id}/contactos/{contact_id}/editar")
async def update_contact(
    request: Request,
    company_id: int,
    contact_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
) -> Response:
    company = companies.get_company(session, company_id)
    contact = _company_contact(session, company_id, contact_id)
    form = await request.form()
    try:
        companies.update_contact(session, contact_id, _contact_data(form), actor(user))
    except ServiceError as exc:
        session.rollback()
        context = {"company": company, "contact": contact, "form": form, "error": str(exc)}
        return render(request, "companies/contact_form.html", context)
    flash(request, "Contacto actualizado.")
    return redirect(request, f"/empresas/{company_id}")
