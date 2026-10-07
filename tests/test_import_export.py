"""Importación CSV y exportación a Obsidian (siempre con una bóveda temporal)."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from crm.cli import app as cli_app
from crm.config import get_settings
from crm.db import make_engine
from crm.models import Base, Company, Phase
from crm.services import companies, demo, importer
from crm.services import export_obsidian as export
from crm.services.companies import CompanyInput
from crm.services.errors import ServiceError

TODAY = date(2026, 10, 7)

CSV_TEXT = (
    "Razón social;Localidad;Actividad;Contacto;Email\n"
    "Talleres Inventados;Soria;Taller;Ana Prueba;ana@ejemplo.com\n"
    "Bodega Ficticia;Ágreda;Vino;;\n"
    "TALLERES  inventados;Soria;Taller;;\n"  # repetida en el archivo
    "Panadería Existente;Almazán;Pan;;\n"  # ya existe en el CRM (con otras tildes)
    ";Soria;;;\n"  # sin nombre
)


def count(session: Session) -> int:
    return int(session.scalar(select(func.count(Company.id))) or 0)


# --- Importación -------------------------------------------------------------------------


def test_mapping_by_synonyms_and_overrides() -> None:
    headers = ["Razón social", "Localidad", "E-mail", "Otra"]
    mapping = importer.build_mapping(headers)
    assert mapping == {
        "name": "Razón social",
        "municipality": "Localidad",
        "contact_email": "E-mail",
    }
    assert importer.build_mapping(headers, {"notes": "Otra"})["notes"] == "Otra"
    with pytest.raises(ServiceError):
        importer.build_mapping(["Cosa"])
    with pytest.raises(ServiceError):
        importer.build_mapping(headers, {"inventado": "Otra"})
    with pytest.raises(ServiceError):
        importer.build_mapping(headers, {"notes": "No existe"})


def test_dry_run_does_not_write(session: Session) -> None:
    companies.create_company(session, CompanyInput(name="Panaderia existente"), "raul")
    before = count(session)
    report = importer.run_import(session, CSV_TEXT, dry_run=True)
    assert [r.company.name for r in report.to_create] == ["Talleres Inventados", "Bodega Ficticia"]
    assert [d[1] for d in report.duplicates] == ["TALLERES  inventados", "Panadería Existente"]
    assert report.errors == [(6, "Fila sin nombre de empresa.")]
    assert not report.written
    assert count(session) == before


def test_import_creates_leads_with_contact(session: Session) -> None:
    report = importer.run_import(session, CSV_TEXT)
    assert report.written
    company = companies.find_by_normalized_name(session, "talleres inventados")
    assert company is not None
    assert company.phase == Phase.LEAD.value
    assert company.created_by == "importacion"
    assert company.source == "Importación"
    assert company.contacts[0].email == "ana@ejemplo.com"
    assert company.contacts[0].is_primary
    # Volver a importar no duplica nada.
    again = importer.run_import(session, CSV_TEXT)
    assert again.to_create == [] and not again.written


def test_read_csv_falls_back_to_windows_encoding(tmp_path: Path) -> None:
    path = tmp_path / "excel.csv"
    path.write_bytes("Nombre\nÓptica Ñandú\n".encode("cp1252"))
    assert "Óptica Ñandú" in importer.read_csv_text(path)


def test_unknown_encoding_gives_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "raro.csv"
    path.write_bytes(b"Nombre\n\x81\x8d\x8f\n")
    with pytest.raises(ServiceError, match="CSV UTF-8"):
        importer.read_csv_text(path)


def test_company_column_wins_over_person_name_column() -> None:
    mapping = importer.build_mapping(["Empresa", "Nombre", "Teléfono", "Email"])
    assert mapping["name"] == "Empresa"
    assert mapping["contact_name"] == "Nombre"
    # Sin columna de empresa, "Nombre" es el de la empresa y no se reutiliza para el contacto.
    alone = importer.build_mapping(["Nombre", "Email"])
    assert alone["name"] == "Nombre" and "contact_name" not in alone


def test_invalid_row_is_skipped_and_the_rest_imported(session: Session) -> None:
    text = "Empresa;Notas\nBuena Ejemplo;ok\n" + "X" * 250 + ";demasiado largo\nOtra Ejemplo;ok\n"
    report = importer.run_import(session, text)
    assert [r.company.name for r in report.to_create] == ["Buena Ejemplo", "Otra Ejemplo"]
    assert [line for line, _ in report.errors] == [3]
    assert count(session) == 2


def test_import_is_all_or_nothing(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_commit() -> None:
        raise RuntimeError("disco lleno (simulado)")

    monkeypatch.setattr(session, "commit", broken_commit)
    with pytest.raises(RuntimeError):
        importer.run_import(session, CSV_TEXT)
    monkeypatch.undo()
    session.rollback()
    assert count(session) == 0


# --- Exportación a Obsidian --------------------------------------------------------------


def make_vault(tmp_path: Path, body: str, newline: str = "\n") -> Path:
    note = tmp_path / export.TARGET_NOTE
    note.parent.mkdir(parents=True)
    note.write_bytes(body.replace("\n", newline).encode("utf-8"))
    return tmp_path


NOTE = (
    "---\ntipo: pipeline\n---\n# Clientes potenciales\n\nTexto mío antes.\n\n"
    f"{export.START_MARKER}\ncontenido viejo\n{export.END_MARKER}\n\nTexto mío después.\n"
)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_export_only_touches_between_markers(
    session: Session, tmp_path: Path, newline: str
) -> None:
    demo.load_demo(session, on=TODAY)
    vault = make_vault(tmp_path, NOTE, newline)
    note = vault / export.TARGET_NOTE
    original = note.read_bytes()

    result = export.export_summary(session, vault, on=TODAY)
    assert result.written
    new = note.read_bytes()
    start = original.index(export.START_MARKER.encode()) + len(export.START_MARKER)
    end_old = original.index(export.END_MARKER.encode())
    end_new = new.index(export.END_MARKER.encode())
    assert new[:start] == original[:start]  # antes de los marcadores, idéntico byte a byte
    assert new[end_new:] == original[end_old:]  # después, también
    assert b"contenido viejo" not in new
    assert "Carpintería Pino Ficticio".encode() in new
    assert b"07/10/2026" in new
    if newline == "\r\n":
        assert b"\n" not in new.replace(b"\r\n", b"")  # no mezcla finales de línea

    # Segunda exportación igual: no reescribe.
    assert not export.export_summary(session, vault, on=TODAY).written


def test_export_dry_run_does_not_write(session: Session, tmp_path: Path) -> None:
    vault = make_vault(tmp_path, NOTE)
    before = (vault / export.TARGET_NOTE).read_bytes()
    result = export.export_summary(session, vault, dry_run=True, on=TODAY)
    assert result.changed and not result.written
    assert (vault / export.TARGET_NOTE).read_bytes() == before


@pytest.mark.parametrize(
    "body",
    [
        "# Sin marcadores\n",
        f"{export.END_MARKER}\n{export.START_MARKER}\n",  # al revés
        f"{export.START_MARKER}\n{export.END_MARKER}\n{export.START_MARKER}\n{export.END_MARKER}\n",
    ],
)
def test_export_without_valid_markers_writes_nothing(
    session: Session, tmp_path: Path, body: str
) -> None:
    vault = make_vault(tmp_path, body)
    before = (vault / export.TARGET_NOTE).read_bytes()
    with pytest.raises(ServiceError, match="marcadores"):
        export.export_summary(session, vault, on=TODAY)
    assert (vault / export.TARGET_NOTE).read_bytes() == before
    assert list((vault / "negocio").iterdir()) == [vault / export.TARGET_NOTE]  # sin temporales


def test_export_missing_note(session: Session, tmp_path: Path) -> None:
    with pytest.raises(ServiceError, match="No encuentro"):
        export.export_summary(session, tmp_path, on=TODAY)


def test_markers_and_html_in_names_cannot_break_the_note(session: Session, tmp_path: Path) -> None:
    companies.create_company(
        session, CompanyInput(name=f"Trampa {export.END_MARKER} <img src=x>"), "raul"
    )
    vault = make_vault(tmp_path, NOTE)
    export.export_summary(session, vault, on=TODAY)
    text = (vault / export.TARGET_NOTE).read_text("utf-8")
    assert text.count(export.END_MARKER) == 1 and text.count(export.START_MARKER) == 1
    assert "<img" not in text and "&lt;img src=x&gt;" in text
    # Y la siguiente exportación sigue funcionando.
    assert export.export_summary(session, vault, on=TODAY).changed is False


def test_pipe_in_name_is_escaped(session: Session) -> None:
    companies.create_company(session, CompanyInput(name="Uno | Dos"), "raul")
    assert "Uno \\| Dos" in export.render_summary(session, TODAY)


# --- CLI ---------------------------------------------------------------------------------


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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


def test_cli_import_dry_run_and_real(cli_env: Path) -> None:
    csv_path = cli_env / "leads.csv"
    csv_path.write_text(CSV_TEXT, encoding="utf-8")
    runner = CliRunner()
    dry = runner.invoke(cli_app, ["importar", str(csv_path), "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "no se ha escrito nada" in dry.output
    real = runner.invoke(cli_app, ["importar", str(csv_path)])
    assert real.exit_code == 0, real.output
    assert "Creadas 3 empresas" in real.output


def test_cli_export_and_user_and_demo(cli_env: Path) -> None:
    make_vault(cli_env / "vault", NOTE)
    runner = CliRunner()
    result = runner.invoke(
        cli_app, ["crear-usuario", "raul"], input="clave-larga-1\nclave-larga-1\n"
    )
    assert result.exit_code == 0, result.output
    assert runner.invoke(cli_app, ["demo"]).exit_code == 0
    assert runner.invoke(cli_app, ["demo"]).exit_code == 1  # no vacía sin --forzar
    dry = runner.invoke(cli_app, ["exportar-obsidian", "--dry-run"])
    assert dry.exit_code == 0 and "no se ha escrito" in dry.output
    assert "contenido viejo" in (cli_env / "vault" / export.TARGET_NOTE).read_text("utf-8")
    real = runner.invoke(cli_app, ["exportar-obsidian"])
    assert real.exit_code == 0, real.output
    assert "contenido viejo" not in (cli_env / "vault" / export.TARGET_NOTE).read_text("utf-8")
