"""Importación de empresas (y su contacto principal) desde CSV.

Las empresas nuevas entran en `0-Lead`. Los duplicados se detectan por nombre normalizado,
contra la base de datos y dentro del propio archivo. Todo o nada: una sola transacción.
"""

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from crm.models import Company, Contact, Phase
from crm.services.companies import CompanyInput, ContactInput
from crm.services.errors import ServiceError
from crm.services.validation import validate
from crm.text import fold

IMPORT_ACTOR = "importacion"

COMPANY_FIELDS = ("name", "sector", "municipality", "website", "phone", "source", "notes")
CONTACT_FIELDS = ("contact_name", "contact_role", "contact_phone", "contact_email")
ALL_FIELDS = COMPANY_FIELDS + CONTACT_FIELDS

# Cabeceras reconocidas sin configurar nada (comparadas sin tildes ni mayúsculas).
HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "name": ("nombre", "empresa", "razon social", "name", "company"),
    "sector": ("sector", "actividad", "industria"),
    "municipality": ("municipio", "localidad", "poblacion", "ciudad", "city"),
    "website": ("web", "website", "url", "pagina web"),
    "phone": ("telefono", "tel", "telefono empresa", "phone"),
    "source": ("origen", "fuente", "source"),
    "notes": ("notas", "observaciones", "comentarios", "notes"),
    "contact_name": ("contacto", "persona de contacto", "nombre contacto", "contact"),
    "contact_role": ("cargo", "puesto", "role"),
    "contact_phone": ("telefono contacto", "movil", "mobile"),
    "contact_email": ("email", "correo", "e mail", "correo electronico", "mail"),
}


@dataclass
class ImportRow:
    line: int
    company: CompanyInput
    contact: ContactInput | None


@dataclass
class ImportReport:
    mapping: dict[str, str]
    to_create: list[ImportRow] = field(default_factory=list)
    duplicates: list[tuple[int, str, str]] = field(default_factory=list)  # línea, nombre, motivo
    errors: list[tuple[int, str]] = field(default_factory=list)
    written: bool = False


def read_csv_text(path: Path) -> str:
    """Lee el CSV como texto: UTF-8 (con o sin BOM) o, si falla, Windows-1252 (Excel)."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def build_mapping(headers: list[str], overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Campo del CRM -> cabecera del archivo. `overrides` manda sobre los sinónimos."""
    by_folded = {fold(h): h for h in headers}
    mapping: dict[str, str] = {}
    for field_name, synonyms in HEADER_SYNONYMS.items():
        for synonym in synonyms:
            if synonym in by_folded and by_folded[synonym] not in mapping.values():
                mapping[field_name] = by_folded[synonym]
                break
    for field_name, header in (overrides or {}).items():
        if field_name not in ALL_FIELDS:
            raise ServiceError(
                f"Campo desconocido: {field_name!r}. Válidos: {', '.join(ALL_FIELDS)}"
            )
        if header not in headers:
            raise ServiceError(f"La columna {header!r} no está en el archivo.")
        mapping[field_name] = header
    if "name" not in mapping:
        raise ServiceError(
            "No encuentro la columna del nombre de la empresa. Indícala con "
            "--columna name=<cabecera>."
        )
    return mapping


def plan_import(
    session: Session, text: str, overrides: dict[str, str] | None = None
) -> ImportReport:
    """Analiza el CSV sin escribir nada."""
    sample = text[:4096]
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h for h in (reader.fieldnames or []) if h]
    report = ImportReport(mapping=build_mapping(headers, overrides))

    existing = {fold(name): name for name in session.scalars(select(Company.name))}
    seen: dict[str, int] = {}
    for line, row in enumerate(reader, start=2):
        values = {f: (row.get(h) or "").strip() for f, h in report.mapping.items()}
        name = values.get("name", "")
        if not name:
            if any(values.values()):
                report.errors.append((line, "Fila sin nombre de empresa."))
            continue
        key = fold(name)
        if key in existing:
            report.duplicates.append((line, name, f"ya existe en el CRM como «{existing[key]}»"))
            continue
        if key in seen:
            report.duplicates.append((line, name, f"repetida en el archivo (línea {seen[key]})"))
            continue
        try:
            company = validate(
                CompanyInput,
                {f: values.get(f, "") for f in COMPANY_FIELDS}
                | {"source": values.get("source") or "Importación"},
            )
            contact = None
            if values.get("contact_name"):
                contact = validate(
                    ContactInput,
                    {
                        "name": values["contact_name"],
                        "role": values.get("contact_role", ""),
                        "phone": values.get("contact_phone", ""),
                        "email": values.get("contact_email", ""),
                        "is_primary": True,
                        "data_source": "Importación",
                    },
                )
        except ServiceError as exc:
            report.errors.append((line, str(exc)))
            continue
        seen[key] = line
        report.to_create.append(ImportRow(line, company, contact))
    return report


def run_import(
    session: Session, text: str, overrides: dict[str, str] | None = None, dry_run: bool = False
) -> ImportReport:
    report = plan_import(session, text, overrides)
    if dry_run or not report.to_create:
        return report
    for row in report.to_create:
        company = Company(
            **row.company.model_dump(),
            phase=Phase.LEAD.value,
            created_by=IMPORT_ACTOR,
            updated_by=IMPORT_ACTOR,
        )
        if row.contact is not None:
            company.contacts.append(
                Contact(
                    **row.contact.model_dump(), created_by=IMPORT_ACTOR, updated_by=IMPORT_ACTOR
                )
            )
        session.add(company)
    session.commit()
    report.written = True
    return report
