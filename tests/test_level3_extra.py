"""Casos extra del nivel 3: importación CSV, exportación a Obsidian y MCP.

Completa `test_import_export.py` y `test_mcp.py` con lo que faltaba de los casos obligatorios:
normalización de duplicados, BOM y codificaciones de Excel, bytes intactos fuera de los
marcadores con texto no ASCII, lecturas del MCP sin efectos y escrituras con autor `mcp`.
Siempre con base de datos y bóveda temporales; todos los datos son inventados.
"""

import asyncio
import json
import unicodedata
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from crm.cli import app as cli_app
from crm.config import get_settings
from crm.db import make_engine
from crm.mcp_server import build_server
from crm.models import Base, Company, Contact, Phase, Service
from crm.services import clients, companies, demo, importer
from crm.services import export_obsidian as export
from crm.services.clients import ContractInput
from crm.services.clock import today
from crm.services.companies import CompanyInput, InteractionInput
from crm.services.errors import ServiceError
from crm.web.formatting import euros

TODAY = date(2026, 10, 7)
UTF8_BOM = b"\xef\xbb\xbf"


def count(session: Session, model: type[Base]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def dump(factory: sessionmaker[Session]) -> dict[str, list[tuple[Any, ...]]]:
    """Contenido completo de todas las tablas, ordenado por clave primaria."""
    with factory() as s:
        return {
            table.name: [
                tuple(row)
                for row in s.execute(table.select().order_by(*table.primary_key.columns)).all()
            ]
            for table in Base.metadata.sorted_tables
        }


# --- Importación: duplicados por nombre normalizado ----------------------------------------


@pytest.mark.parametrize(
    ("existing", "incoming"),
    [
        ("Óptica Ñandú Soria", "OPTICA ÑANDU SORIA"),  # mayúsculas
        ("Óptica Ñandú Soria", "Optica Nandu Soria"),  # sin tildes ni eñe
        ("Optica Nandu Soria", "Óptica Ñandú Soria"),  # al revés: tildes en el archivo
        ("Óptica Ñandú Soria", "  óptica   ñandú    soria  "),  # espacios sobrantes
        ("Óptica Ñandú Soria", "Óptica Ñandú Soria"),  # espacio duro de Excel
        ("Óptica Ñandú Soria", unicodedata.normalize("NFD", "Óptica Ñandú Soria")),  # macOS
        ("Talleres Inventados, S.L.", "Talleres Inventados S.L."),  # signos
    ],
)
def test_duplicate_against_crm_ignores_case_accents_and_spaces(
    session: Session, existing: str, incoming: str
) -> None:
    companies.create_company(session, CompanyInput(name=existing), "raul")
    report = importer.run_import(session, f"Nombre;Localidad\n{incoming};Soria\n")
    assert report.to_create == []
    assert len(report.duplicates) == 1
    assert existing in report.duplicates[0][2]  # el motivo nombra la empresa del CRM
    assert count(session, Company) == 1


def test_duplicates_inside_the_file_keep_only_the_first(session: Session) -> None:
    text = (
        "Nombre;Localidad\n"
        "Bodega Ficticia del Duero;Almazán\n"
        "BODEGA FICTICIA DEL DUERO;Almazán\n"
        "  Bodéga   ficticia del duero ;Almazán\n"
    )
    report = importer.run_import(session, text)
    assert [r.company.name for r in report.to_create] == ["Bodega Ficticia del Duero"]
    assert [d[0] for d in report.duplicates] == [3, 4]
    assert all("línea 2" in d[2] for d in report.duplicates)
    assert count(session, Company) == 1


def test_duplicate_does_not_touch_the_existing_company(session: Session) -> None:
    existing = companies.create_company(
        session,
        CompanyInput(name="Carpintería Inventada", municipality="Covaleda"),
        "raul",
        Phase.MEETING,
    )
    importer.run_import(session, "Nombre;Localidad\nCARPINTERIA INVENTADA;Soria\n")
    session.expire_all()
    again = companies.get_company(session, existing.id)
    assert again.phase == Phase.MEETING.value  # no vuelve a 0-Lead
    assert again.municipality == "Covaleda"
    assert again.updated_by == "raul"


def test_imported_name_is_stored_trimmed(session: Session) -> None:
    importer.run_import(session, "Nombre;Localidad\n   Talleres Inventados   ;Soria\n")
    assert session.scalars(select(Company.name)).all() == ["Talleres Inventados"]


def test_phase_column_in_file_is_ignored_and_new_rows_enter_as_lead(session: Session) -> None:
    text = "Nombre;Fase\nCliente Inventado Uno;6-Ganado\nOtra Inventada;3-Reunión\n"
    importer.run_import(session, text)
    phases = set(session.scalars(select(Company.phase)))
    assert phases == {Phase.LEAD.value}


def test_dry_run_writes_nothing_seen_from_another_session(
    session: Session, session_factory: sessionmaker[Session]
) -> None:
    text = "Nombre;Contacto;Email\nFerretería Inventada;Luis Prueba;luis@ejemplo.com\n"
    before = dump(session_factory)
    report = importer.run_import(session, text, dry_run=True)
    assert len(report.to_create) == 1 and not report.written
    assert not session.new and not session.dirty
    assert dump(session_factory) == before
    with session_factory() as other:
        assert count(other, Company) == 0
        assert count(other, Contact) == 0


def test_header_only_file_writes_nothing(session: Session) -> None:
    report = importer.run_import(session, "Nombre;Localidad\n")
    assert report.to_create == [] and not report.written
    assert count(session, Company) == 0


# --- Importación: codificación y separadores de Excel --------------------------------------


@pytest.mark.parametrize("separator", [";", ","])
def test_utf8_bom_is_not_part_of_the_first_header(
    session: Session, tmp_path: Path, separator: str
) -> None:
    path = tmp_path / "con_bom.csv"
    body = f"Nombre{separator}Localidad\nCarpintería Ficticia{separator}Ólvega\n"
    path.write_bytes(UTF8_BOM + body.encode("utf-8"))
    text = importer.read_csv_text(path)
    assert not text.startswith("﻿")
    report = importer.run_import(session, text)
    assert report.mapping["name"] == "Nombre"
    company = companies.find_by_normalized_name(session, "carpinteria ficticia")
    assert company is not None
    assert company.municipality == "Ólvega"
    assert company.phase == Phase.LEAD.value


def test_excel_windows_1252_semicolon_file_imports_accents(
    session: Session, tmp_path: Path
) -> None:
    path = tmp_path / "excel.csv"
    path.write_bytes("Nombre;Municipio\nPeluquería Ñandú;Ágreda\n".encode("cp1252"))
    importer.run_import(session, importer.read_csv_text(path))
    company = companies.find_by_normalized_name(session, "peluqueria nandu")
    assert company is not None
    assert company.name == "Peluquería Ñandú"
    assert company.municipality == "Ágreda"


def test_single_column_file_keeps_commas_in_the_name(session: Session) -> None:
    """Excel en español exporta con `;` y no entrecomilla las comas: con una sola columna,
    'Talleres Pérez, S.L.' tiene que entrar entero."""
    text = "Nombre\nTalleres Pérez, S.L.\nBodega Uno Inventada\nCarpintería Dos Inventada\n"
    report = importer.run_import(session, text)
    assert report.errors == []
    assert sorted(session.scalars(select(Company.name))) == [
        "Bodega Uno Inventada",
        "Carpintería Dos Inventada",
        "Talleres Pérez, S.L.",
    ]


# --- Exportación a Obsidian ----------------------------------------------------------------

START = export.START_MARKER
END = export.END_MARKER


def write_note(vault: Path, data: bytes) -> Path:
    note = vault / export.TARGET_NOTE
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_bytes(data)
    return note


NON_ASCII_NOTES = {
    "bom_lf": UTF8_BOM
    + (
        "---\ntipo: pipeline\nactualizado: 2026-10-07\n---\n"
        "# Clientes potenciales — Soria\n\n«Notas mías» con tildes: Ágreda, Ólvega, señal.\n\n"
        f"{START}\nviejo\n{END}\n\nDespués: año, pingüino, café ☕.\n"
    ).encode("utf-8"),
    "crlf_sin_salto_final": (
        f"# Pipeline\r\nAntes ñ é ü\r\n\r\n{START}\r\nviejo\r\n{END}\r\nFin — sin salto"
    ).encode("utf-8"),
    "mixto": (f"línea uno\r\nlínea dos\nñ\r\n{START}\n{END}\r\nfin ñ\n").encode("utf-8"),
    "misma_linea": (f"Antes → {START}{END} después ñ\n").encode("utf-8"),
}


@pytest.mark.parametrize("name", list(NON_ASCII_NOTES))
def test_export_keeps_non_ascii_outside_markers_byte_for_byte(
    session: Session, tmp_path: Path, name: str
) -> None:
    companies.create_company(
        session, CompanyInput(name="Peluquería Ñandú Inventada", municipality="Ágreda"), "raul"
    )
    original = NON_ASCII_NOTES[name]
    note = write_note(tmp_path, original)

    result = export.export_summary(session, tmp_path, on=TODAY)
    assert result.written
    new = note.read_bytes()
    head_len = original.index(START.encode()) + len(START.encode())
    assert new[:head_len] == original[:head_len]
    assert new[new.index(END.encode()) :] == original[original.index(END.encode()) :]
    assert "Peluquería Ñandú Inventada".encode() in new
    new.decode("utf-8")  # sigue siendo UTF-8 válido
    assert list(note.parent.iterdir()) == [note]  # sin temporales


@pytest.mark.parametrize(
    "body",
    [
        f"# Solo inicio\n{START}\n",
        f"# Solo fin\n{END}\n",
        "<!-- crm:resumen:INICIO -->\n<!-- crm:resumen:FIN -->\n",  # marcadores mal escritos
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_export_with_incomplete_markers_writes_nothing(
    session: Session, tmp_path: Path, body: str, dry_run: bool
) -> None:
    note = write_note(tmp_path, body.encode("utf-8"))
    before = note.read_bytes()
    with pytest.raises(ServiceError) as info:
        export.export_summary(session, tmp_path, dry_run=dry_run, on=TODAY)
    assert START in str(info.value) and END in str(info.value)  # explica cómo añadirlos
    assert note.read_bytes() == before
    assert list(note.parent.iterdir()) == [note]


def test_export_refuses_non_utf8_note(session: Session, tmp_path: Path) -> None:
    original = f"Nota en ANSI: año\n{START}\n{END}\n".encode("cp1252")
    note = write_note(tmp_path, original)
    with pytest.raises(ServiceError, match="UTF-8"):
        export.export_summary(session, tmp_path, on=TODAY)
    assert note.read_bytes() == original


def test_export_touches_no_other_file_and_no_database_row(
    session: Session, session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    demo.load_demo(session, on=TODAY)
    write_note(tmp_path, f"# Pipeline\n{START}\n{END}\n".encode())
    other = tmp_path / "negocio" / "otra_nota.md"
    other.write_bytes("No me toques: ñ\r\n".encode())
    home = tmp_path / "00_Inicio.md"
    home.write_bytes(b"# Inicio\n")
    files_before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    db_before = dump(session_factory)

    export.export_summary(session, tmp_path, dry_run=True, on=TODAY)
    files_after_dry = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert files_after_dry == files_before

    export.export_summary(session, tmp_path, on=TODAY)
    files_after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert set(files_after) == set(files_before)
    assert other.read_bytes() == files_before[other]
    assert home.read_bytes() == files_before[home]
    assert dump(session_factory) == db_before


def test_export_mrr_counts_only_active_contracts(session: Session) -> None:
    service_id = session.scalars(select(Service.id).order_by(Service.id)).first()
    assert service_id is not None
    active = companies.create_company(session, CompanyInput(name="Cliente Activo Inventado"), "r")
    ended = companies.create_company(session, CompanyInput(name="Cliente Baja Inventado"), "r")
    clients.convert_to_client(
        session,
        active.id,
        ContractInput(
            service_id=service_id,
            setup_price_cents=170000,
            monthly_fee_cents=12000,
            start_date=date(2026, 3, 1),
        ),
        "r",
    )
    clients.convert_to_client(
        session,
        ended.id,
        ContractInput(
            service_id=service_id,
            setup_price_cents=0,
            monthly_fee_cents=20000,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 6, 30),
        ),
        "r",
    )
    text = export.render_summary(session, TODAY)
    assert f"MRR {euros(12000)}" in text
    assert f"| Cliente Baja Inventado | — | {euros(0)} |" in text
    assert any(
        line.startswith("| Cliente Activo Inventado |") and line.endswith(f"| {euros(12000)} |")
        for line in text.splitlines()
    )


# --- CLI (base de datos y bóveda temporales) -----------------------------------------------


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    db = tmp_path / "cli.db"
    monkeypatch.setenv("CRM_DB_PATH", str(db))
    monkeypatch.setenv("CRM_VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.chdir(tmp_path)  # que no lea el .env del proyecto
    get_settings.cache_clear()
    engine = make_engine(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    yield tmp_path
    get_settings.cache_clear()


def test_cli_import_file_with_bom(cli_env: Path) -> None:
    path = cli_env / "leads.csv"
    path.write_bytes(UTF8_BOM + "Nombre;Localidad\nBar Inventado;Duruelo de la Sierra\n".encode())
    result = CliRunner().invoke(cli_app, ["importar", str(path)])
    assert result.exit_code == 0, result.output
    assert "name←Nombre" in result.output
    assert "Creadas 1 empresas" in result.output


def test_cli_export_without_markers_fails_and_writes_nothing(cli_env: Path) -> None:
    note = write_note(cli_env / "vault", "# Sin marcadores, con tildes: ñ\n".encode())
    before = note.read_bytes()
    result = CliRunner().invoke(cli_app, ["exportar-obsidian"])
    assert result.exit_code == 1
    assert START in result.output
    assert note.read_bytes() == before


# --- MCP -----------------------------------------------------------------------------------


@pytest.fixture
def server(session_factory: sessionmaker[Session]) -> MCPServer:
    with session_factory() as s:
        demo.load_demo(s)
    return build_server(session_factory)


def call(server: MCPServer, name: str, args: dict[str, Any] | None = None) -> Any:
    result = asyncio.run(server.call_tool(name, args or {}))
    assert not result.is_error, result
    data = result.structured_content
    if data is None:
        return json.loads(result.content[0].text)
    return data["result"] if set(data) == {"result"} else data


def all_company_ids(factory: sessionmaker[Session]) -> list[int]:
    with factory() as s:
        return list(s.scalars(select(Company.id).order_by(Company.id)))


def test_read_tools_leave_every_table_identical(
    server: MCPServer, session_factory: sessionmaker[Session]
) -> None:
    before = dump(session_factory)
    for company_id in all_company_ids(session_factory):  # incluye clientes con facturas
        call(server, "ver_empresa", {"empresa_id": company_id})
    for args in ({}, {"grupo": "clientes"}, {"grupo": "potenciales"}, {"fase": "7-Perdido"}):
        call(server, "buscar_empresas", args)
    for dias in (0, 7, 365, -5):
        call(server, "proximos_pasos", {"dias": dias})
    call(server, "resumen_pipeline")
    call(server, "resumen_clientes")
    assert dump(session_factory) == before


def test_ver_empresa_lists_latest_ten_interactions_newest_first(
    session: Session, session_factory: sessionmaker[Session]
) -> None:
    company = companies.create_company(session, CompanyInput(name="Imprenta Inventada"), "raul")
    for day in range(1, 13):
        companies.add_interaction(
            session,
            company.id,
            InteractionInput(
                occurred_on=date(2026, 9, day), channel=Channel.CALL, summary=f"#{day}"
            ),
            "raul",
        )
    detail = call(build_server(session_factory), "ver_empresa", {"empresa_id": company.id})
    dates = [i["fecha"] for i in detail["interacciones"]]
    assert len(dates) == 10
    assert dates[0] == "2026-09-12" and dates[-1] == "2026-09-03"
    assert dates == sorted(dates, reverse=True)


def test_write_tools_on_existing_company_set_updated_by_mcp(
    session: Session, session_factory: sessionmaker[Session]
) -> None:
    company = companies.create_company(
        session, CompanyInput(name="Serrería Inventada"), "raul", Phase.LEAD
    )
    server = build_server(session_factory)
    call(server, "cambiar_fase", {"empresa_id": company.id, "fase": Phase.LOST.value})
    call(server, "fijar_proximo_paso", {"empresa_id": company.id, "texto": "Volver en enero"})
    call(server, "registrar_interaccion", {"empresa_id": company.id, "resumen": "No interesa"})
    with session_factory() as s:
        again = companies.get_company(s, company.id)
        assert again.created_by == "raul"  # el autor original no se pisa
        assert again.updated_by == "mcp"
        assert again.phase == Phase.LOST.value  # 7-Perdido desde 0-Lead
        assert again.next_step == "Volver en enero" and again.next_step_date is None
        [interaction] = again.interactions
        assert interaction.created_by == "mcp"
        assert interaction.occurred_on == today()
        assert interaction.channel == "llamada"


def test_crear_empresa_defaults_and_trimmed_duplicate(
    server: MCPServer, session_factory: sessionmaker[Session]
) -> None:
    created = call(server, "crear_empresa", {"nombre": "  Quesería Inventada  "})
    assert created["nombre"] == "Quesería Inventada"
    assert created["fase"] == Phase.IDENTIFIED.value
    with session_factory() as s:
        company = companies.get_company(s, created["id"])
        assert company.source == "Claude (MCP)"
        assert company.created_by == "mcp"
    with pytest.raises(ToolError, match="Ya existe"):
        asyncio.run(server.call_tool("crear_empresa", {"nombre": "QUESERIA   inventada"}))


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("crear_empresa", {"nombre": "Cliente Directo Inventado", "fase": "6-Ganado"}),
        ("crear_empresa", {"nombre": "Carpintería Pino Ficticio"}),
        ("registrar_interaccion", {"empresa_id": 99999, "resumen": "Llamada"}),
        ("registrar_interaccion", {"empresa_id": 1, "resumen": "  "}),
        ("cambiar_fase", {"empresa_id": 1, "fase": "0-Lead"}),
        ("fijar_proximo_paso", {"empresa_id": 1, "texto": "", "fecha": "2026-11-02"}),
    ],
)
def test_rejected_writes_leave_the_database_unchanged(
    server: MCPServer,
    session_factory: sessionmaker[Session],
    tool: str,
    args: dict[str, Any],
) -> None:
    before = dump(session_factory)
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool(tool, args))
    assert dump(session_factory) == before
