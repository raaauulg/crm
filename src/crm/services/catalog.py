"""Catálogo de servicios."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crm.models import Service
from crm.services.errors import NotFoundError, ServiceError

# (nombre, implantación en céntimos, cuota mensual en céntimos). Fuente: catálogo de entrada.
DEFAULT_SERVICES: list[tuple[str, int, int]] = [
    ("Albaranes y facturas sin teclear", 170_000, 12_000),
    ("Pedidos sin teclear", 200_000, 12_000),
    ("Presupuestos en 5 minutos", 220_000, 9_000),
    ("Parte del lunes", 240_000, 12_000),
    ("Recepcionista virtual", 250_000, 20_000),
    ("Web sencilla", 69_000, 2_500),
    ("Taller IA útil para tu oficina", 120_000, 0),
    ("Paso a programa con Verifactu", 60_000, 0),
    ("Diagnóstico de automatización", 0, 0),
]


def ensure_default_catalog(session: Session) -> int:
    """Carga el catálogo de referencia si la tabla está vacía. Devuelve cuántos ha creado."""
    if session.scalar(select(func.count(Service.id))):
        return 0
    for name, setup, fee in DEFAULT_SERVICES:
        session.add(Service(name=name, setup_price_cents=setup, monthly_fee_cents=fee))
    session.commit()
    return len(DEFAULT_SERVICES)


def list_services(session: Session, only_active: bool = False) -> list[Service]:
    query = select(Service).order_by(Service.name)
    if only_active:
        query = query.where(Service.active.is_(True))
    return list(session.scalars(query))


def get_service(session: Session, service_id: int) -> Service:
    service = session.get(Service, service_id)
    if service is None:
        raise NotFoundError(f"No existe el servicio {service_id}.")
    return service


def save_service(
    session: Session,
    name: str,
    setup_price_cents: int,
    monthly_fee_cents: int,
    active: bool = True,
    service_id: int | None = None,
) -> Service:
    """Crea (sin `service_id`) o actualiza un servicio del catálogo."""
    name = name.strip()
    if not name:
        raise ServiceError("El servicio necesita un nombre.")
    if setup_price_cents < 0 or monthly_fee_cents < 0:
        raise ServiceError("Los precios no pueden ser negativos.")
    clash = session.scalar(select(Service).where(Service.name == name))
    if clash is not None and clash.id != service_id:
        raise ServiceError(f"Ya existe un servicio llamado {name!r}.")
    service = get_service(session, service_id) if service_id else Service(name=name)
    service.name = name
    service.setup_price_cents = setup_price_cents
    service.monthly_fee_cents = monthly_fee_cents
    service.active = active
    session.add(service)
    session.commit()
    return service
