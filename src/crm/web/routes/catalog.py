"""Catálogo de servicios editable."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from crm.services import catalog
from crm.services.errors import ServiceError
from crm.web.deps import (
    csrf_protect,
    flash,
    form_bool,
    form_euros,
    form_str,
    get_session,
    redirect,
    render,
    require_user,
)

router = APIRouter(prefix="/servicios", dependencies=[Depends(require_user), Depends(csrf_protect)])


@router.get("")
def service_list(request: Request, session: Session = Depends(get_session)) -> Response:
    return render(request, "catalog.html", {"services": catalog.list_services(session)})


async def _save(request: Request, session: Session, service_id: int | None) -> Response:
    form = await request.form()
    try:
        setup = form_euros(form, "setup_price")
        fee = form_euros(form, "monthly_fee")
        if service_id and (setup is None or fee is None):
            raise ServiceError("Escribe los dos precios (pon 0 si no hay).")
        service = catalog.save_service(
            session,
            name=form_str(form, "name"),
            setup_price_cents=setup or 0,
            monthly_fee_cents=fee or 0,
            active=form_bool(form, "active") if service_id else True,
            service_id=service_id,
        )
        flash(request, f"Servicio «{service.name}» guardado.")
    except ServiceError as exc:
        session.rollback()
        flash(request, str(exc), "error")
    return redirect(request, "/servicios")


@router.post("")
async def create_service(request: Request, session: Session = Depends(get_session)) -> Response:
    return await _save(request, session, None)


@router.post("/{service_id}")
async def update_service(
    request: Request, service_id: int, session: Session = Depends(get_session)
) -> Response:
    return await _save(request, session, service_id)
