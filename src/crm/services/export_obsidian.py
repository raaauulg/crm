"""Exportación en un sentido a la bóveda de Obsidian.

Escribe la tabla resumen de potenciales y clientes **solo** entre los marcadores de
`negocio/clientes_potenciales.md`. El resto del archivo queda intacto byte a byte.
"""

import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from crm.models import Company, Phase
from crm.services.clients import company_mrr_cents, contract_is_active
from crm.services.clock import today
from crm.services.errors import ServiceError
from crm.web.formatting import euros, spanish_date

TARGET_NOTE = Path("negocio") / "clientes_potenciales.md"
START_MARKER = "<!-- crm:resumen:inicio -->"
END_MARKER = "<!-- crm:resumen:fin -->"

HOW_TO_ADD_MARKERS = (
    "Añade estas dos líneas en la nota, donde quieras la tabla:\n\n"
    f"{START_MARKER}\n{END_MARKER}\n\n"
    "El CRM solo escribe entre ellas; el resto de la nota no se toca."
)


@dataclass
class ExportResult:
    path: Path
    new_text: str
    summary: str  # la tabla que va entre los marcadores
    changed: bool
    written: bool


def _cell(text: str | None) -> str:
    """Celda de tabla Markdown: sin saltos de línea, con `|` escapado y sin HTML.

    `<` y `>` se escapan para que un texto (importado o escrito por Claude) no pueda colar
    un marcador `<!-- crm:… -->`, un comentario que oculte la nota ni HTML en Obsidian.
    """
    cleaned = (text or "").replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    return cleaned.replace("<", "&lt;").replace(">", "&gt;").strip()


def render_summary(session: Session, on: date | None = None, newline: str = "\n") -> str:
    """Bloque Markdown que va entre los marcadores (sin los marcadores)."""
    on = on or today()
    companies = list(session.scalars(select(Company).order_by(Company.phase, Company.name)))
    potentials = [c for c in companies if c.phase not in (Phase.WON.value, Phase.LOST.value)]
    clients = [c for c in companies if c.phase == Phase.WON.value]

    lines = [
        f"_Generado por el CRM el {spanish_date(on)}. No edites entre los marcadores: "
        "se sobrescribe en cada exportación._",
        "",
        f"### Potenciales ({len(potentials)})",
        "",
        "| Empresa | Fase | Municipio | Valor est. | Próximo paso | Fecha |",
        "|---|---|---|---:|---|---|",
    ]
    for c in potentials:
        lines.append(
            f"| {_cell(c.name)} | {c.phase} | {_cell(c.municipality)} | "
            f"{euros(c.estimated_value_cents, decimals=False)} | {_cell(c.next_step)} | "
            f"{spanish_date(c.next_step_date) if c.next_step_date else ''} |"
        )
    total_mrr = 0
    client_lines = []
    for c in clients:
        mrr = company_mrr_cents(c, on)
        total_mrr += mrr
        active = [k for k in c.contracts if contract_is_active(k, on)]
        services = ", ".join(_cell(k.service.name) for k in active) or "—"
        client_lines.append(f"| {_cell(c.name)} | {services} | {euros(mrr)} |")
    lines += [
        "",
        f"### Clientes ({len(clients)}) · MRR {euros(total_mrr)}",
        "",
        "| Empresa | Servicios activos | Cuota/mes |",
        "|---|---|---:|",
        *client_lines,
    ]
    return newline.join(lines)


def export_summary(
    session: Session, vault: Path, dry_run: bool = False, on: date | None = None
) -> ExportResult:
    """Sustituye lo que hay entre los marcadores. Con `dry_run` no escribe nada."""
    path = vault / TARGET_NOTE
    if not path.is_file():
        raise ServiceError(f"No encuentro la nota {path}. {HOW_TO_ADD_MARKERS}")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ServiceError(f"{path} no está en UTF-8; no la toco.") from exc

    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ServiceError(
            f"La nota {path} no tiene los marcadores bien puestos. {HOW_TO_ADD_MARKERS}"
        )
    if text.count(START_MARKER) > 1 or text.count(END_MARKER) > 1:
        raise ServiceError(f"La nota {path} tiene los marcadores repetidos; deja una sola pareja.")

    newline = "\r\n" if "\r\n" in text else "\n"
    summary = render_summary(session, on, newline)
    block = newline + summary + newline
    head = text[: start + len(START_MARKER)]
    tail = text[end:]
    new_text = head + block + tail
    changed = new_text != text
    if dry_run or not changed:
        return ExportResult(path, new_text, summary, changed, written=False)

    _atomic_write(path, new_text.encode("utf-8"))
    return ExportResult(path, new_text, summary, changed, written=True)


def _atomic_write(path: Path, data: bytes) -> None:
    """Escribe en un temporal de la misma carpeta y lo cambia por el original de golpe."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".crm-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
