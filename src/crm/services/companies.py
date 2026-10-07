"""Empresas, contactos, interacciones, fases y próximos pasos."""

import unicodedata
from datetime import date

from pydantic import Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from crm.models import Channel, Company, Contact, ContractStatus, Interaction, Phase
from crm.services.errors import NotFoundError, ServiceError
from crm.services.validation import InputModel

POTENTIAL_PHASES: tuple[Phase, ...] = tuple(p for p in Phase if p is not Phase.WON)
# Fases a las que se puede mover una empresa con "cambiar fase". `0-Lead` es solo para
# importaciones y `6-Ganado` se alcanza con "convertir en cliente" (crea el contrato).
PHASE_CHANGE_TARGETS: tuple[Phase, ...] = tuple(
    p for p in Phase if p not in (Phase.LEAD, Phase.WON)
)
SORTABLE_COLUMNS = {
    "name": Company.name,
    "phase": Company.phase,
    "sector": Company.sector,
    "municipality": Company.municipality,
    "value": Company.estimated_value_cents,
    "next_step_date": Company.next_step_date,
    "updated_at": Company.updated_at,
}


class CompanyInput(InputModel):
    name: str = Field(min_length=1, max_length=200)
    sector: str = Field(default="", max_length=100)
    municipality: str = Field(default="", max_length=100)
    website: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=50)
    source: str = Field(default="", max_length=100)
    service_id: int | None = None
    estimated_value_cents: int | None = Field(default=None, ge=0)
    estimated_fee_cents: int | None = Field(default=None, ge=0)
    pain_score: int | None = Field(default=None, ge=0, le=100)
    notes: str = ""
    next_step: str = Field(default="", max_length=300)
    next_step_date: date | None = None


class ContactInput(InputModel):
    name: str = Field(min_length=1, max_length=150)
    role: str = Field(default="", max_length=100)
    phone: str = Field(default="", max_length=50)
    email: str = Field(default="", max_length=150)
    is_primary: bool = False
    data_source: str = Field(default="", max_length=100)
    data_date: date | None = None


class InteractionInput(InputModel):
    occurred_on: date
    channel: Channel
    summary: str = Field(min_length=1)
    result: str = ""


def normalize_name(name: str) -> str:
    """Clave para detectar duplicados: sin tildes, minúsculas, sin signos, espacios simples."""
    decomposed = unicodedata.normalize("NFKD", name)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    alnum = "".join(c if c.isalnum() else " " for c in without_accents.lower())
    return " ".join(alnum.split())


def find_by_normalized_name(session: Session, name: str) -> Company | None:
    key = normalize_name(name)
    for company in session.scalars(select(Company)):
        if normalize_name(company.name) == key:
            return company
    return None


def get_company(session: Session, company_id: int) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise NotFoundError(f"No existe la empresa {company_id}.")
    return company


def create_company(
    session: Session, data: CompanyInput, actor: str, phase: Phase = Phase.IDENTIFIED
) -> Company:
    if phase is Phase.WON:
        raise ServiceError("Una empresa nueva no puede ser cliente: usa 'Convertir en cliente'.")
    existing = find_by_normalized_name(session, data.name)
    if existing is not None:
        raise ServiceError(f"Ya existe una empresa con ese nombre: {existing.name!r}.")
    company = Company(**data.model_dump(), phase=phase.value, created_by=actor, updated_by=actor)
    session.add(company)
    session.commit()
    return company


def update_company(session: Session, company_id: int, data: CompanyInput, actor: str) -> Company:
    """Actualiza los datos de la empresa. La fase no se toca aquí (ver `change_phase`)."""
    company = get_company(session, company_id)
    existing = find_by_normalized_name(session, data.name)
    if existing is not None and existing.id != company.id:
        raise ServiceError(f"Ya existe otra empresa con ese nombre: {existing.name!r}.")
    for field, value in data.model_dump().items():
        setattr(company, field, value)
    company.updated_by = actor
    session.commit()
    return company


def search_companies(
    session: Session,
    text: str = "",
    phase: str = "",
    sector: str = "",
    municipality: str = "",
    group: str = "",
    sort: str = "name",
    descending: bool = False,
) -> list[Company]:
    """Búsqueda para la tabla de empresas. `group` = "potenciales" | "clientes" | ""."""
    query = select(Company)
    if text.strip():
        like = f"%{text.strip()}%"
        query = query.where(
            or_(
                Company.name.ilike(like),
                Company.notes.ilike(like),
                Company.sector.ilike(like),
                Company.municipality.ilike(like),
            )
        )
    if phase:
        query = query.where(Company.phase == phase)
    if sector:
        query = query.where(Company.sector == sector)
    if municipality:
        query = query.where(Company.municipality == municipality)
    if group == "clientes":
        query = query.where(Company.phase == Phase.WON.value)
    elif group == "potenciales":
        query = query.where(Company.phase != Phase.WON.value)
    column = SORTABLE_COLUMNS.get(sort, Company.name)
    order = column.desc() if descending else column.asc()
    query = query.order_by(order.nulls_last(), Company.name)
    return list(session.scalars(query))


def distinct_values(session: Session, field: str) -> list[str]:
    """Valores distintos (no vacíos) de `sector` o `municipality`, para los filtros."""
    if field not in ("sector", "municipality"):
        raise ServiceError(f"Campo no filtrable: {field}")
    column = getattr(Company, field)
    return [v for v in session.scalars(select(column).distinct().order_by(column)) if v]


def change_phase(session: Session, company_id: int, new_phase: str, actor: str) -> Company:
    company = get_company(session, company_id)
    try:
        target = Phase(new_phase)
    except ValueError as exc:
        raise ServiceError(f"Fase desconocida: {new_phase!r}.") from exc
    if target is Phase.WON:
        raise ServiceError("Para pasar a 6-Ganado usa 'Convertir en cliente' (crea el contrato).")
    if target is Phase.LEAD:
        raise ServiceError("0-Lead es solo para empresas importadas sin revisar.")
    if company.phase == target.value:
        raise ServiceError(f"La empresa ya está en {target.value}.")
    if company.phase == Phase.WON.value and any(
        c.status == ContractStatus.ACTIVE.value for c in company.contracts
    ):
        raise ServiceError(
            "La empresa tiene contratos activos: cancélalos antes de cambiar la fase."
        )
    company.phase = target.value
    company.updated_by = actor
    session.commit()
    return company


def set_next_step(
    session: Session, company_id: int, text: str, when: date | None, actor: str
) -> Company:
    company = get_company(session, company_id)
    text = text.strip()
    if when is not None and not text:
        raise ServiceError("Escribe en qué consiste el próximo paso.")
    company.next_step = text
    company.next_step_date = when
    company.updated_by = actor
    session.commit()
    return company


def add_contact(session: Session, company_id: int, data: ContactInput, actor: str) -> Contact:
    company = get_company(session, company_id)
    if data.is_primary:
        for other in company.contacts:
            other.is_primary = False
    contact = Contact(**data.model_dump(), company=company, created_by=actor, updated_by=actor)
    session.add(contact)
    session.commit()
    return contact


def update_contact(session: Session, contact_id: int, data: ContactInput, actor: str) -> Contact:
    contact = session.get(Contact, contact_id)
    if contact is None:
        raise NotFoundError(f"No existe el contacto {contact_id}.")
    if data.is_primary:
        for other in contact.company.contacts:
            if other.id != contact.id:
                other.is_primary = False
    for field, value in data.model_dump().items():
        setattr(contact, field, value)
    contact.updated_by = actor
    session.commit()
    return contact


def get_contact(session: Session, contact_id: int) -> Contact:
    contact = session.get(Contact, contact_id)
    if contact is None:
        raise NotFoundError(f"No existe el contacto {contact_id}.")
    return contact


def add_interaction(
    session: Session, company_id: int, data: InteractionInput, actor: str
) -> Interaction:
    company = get_company(session, company_id)
    interaction = Interaction(
        company=company,
        occurred_on=data.occurred_on,
        channel=data.channel.value,
        summary=data.summary,
        result=data.result,
        created_by=actor,
    )
    session.add(interaction)
    session.commit()
    return interaction


def upcoming_steps(session: Session, until: date) -> list[Company]:
    """Empresas no perdidas con próximo paso fechado hasta `until` (incluye los vencidos)."""
    query = (
        select(Company)
        .where(Company.next_step_date.is_not(None))
        .where(Company.next_step_date <= until)
        .where(Company.phase != Phase.LOST.value)
        .order_by(Company.next_step_date, Company.name)
    )
    return list(session.scalars(query))
