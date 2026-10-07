"""Línea de comandos: `uv run crm --help`."""

import logging
from pathlib import Path
from typing import NoReturn

import typer

from crm.config import get_settings
from crm.db import default_session_factory, session_scope
from crm.services import demo, importer, users
from crm.services import export_obsidian as export
from crm.services.errors import ServiceError

app = typer.Typer(help="CRM de la consultoría.", no_args_is_help=True, add_completion=False)


def _fail(message: str) -> NoReturn:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


@app.command("serve")
def serve(
    host: str | None = typer.Option(None, help="Por defecto CRM_HOST (127.0.0.1)."),
    port: int | None = typer.Option(None, help="Por defecto CRM_PORT (8000)."),
    reload: bool = typer.Option(False, help="Recargar al cambiar el código (desarrollo)."),
) -> None:
    """Arranca la web."""
    import uvicorn

    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        "crm.web.main:app",
        host=host or settings.crm_host,
        port=port or settings.crm_port,
        reload=reload,
    )


@app.command("crear-usuario")
def create_user(
    username: str = typer.Argument(..., help="Nombre de usuario."),
    password: str = typer.Option(
        ...,
        prompt="Contraseña",
        hide_input=True,
        confirmation_prompt=True,
        help="Si no se pasa, se pide por teclado (recomendado).",
    ),
) -> None:
    """Crea un usuario para entrar en la web."""
    try:
        with session_scope(default_session_factory()) as session:
            user = users.create_user(session, username, password)
            typer.secho(f"Usuario {user.username!r} creado.", fg=typer.colors.GREEN)
    except ServiceError as exc:
        _fail(str(exc))


@app.command("importar")
def import_csv(
    archivo: Path = typer.Argument(..., exists=True, dir_okay=False, help="CSV a importar."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Enseña qué haría sin escribir."),
    columna: list[str] = typer.Option(
        [], "--columna", help="Mapeo campo=Cabecera, p. ej. --columna name=Razón social."
    ),
) -> None:
    """Importa empresas (y su contacto) desde CSV. Entran en 0-Lead."""
    overrides: dict[str, str] = {}
    for item in columna:
        if "=" not in item:
            _fail(f"--columna debe ser campo=Cabecera, no {item!r}")
        key, header = item.split("=", 1)
        overrides[key.strip()] = header.strip()
    try:
        with session_scope(default_session_factory()) as session:
            report = importer.run_import(
                session, importer.read_csv_text(archivo), overrides, dry_run=dry_run
            )
    except ServiceError as exc:
        _fail(str(exc))
    typer.echo("Columnas: " + ", ".join(f"{k}←{v}" for k, v in report.mapping.items()))
    for row in report.to_create:
        contact = f" (contacto: {row.contact.name})" if row.contact else ""
        typer.echo(f"  + línea {row.line}: {row.company.name}{contact}")
    for line, name, reason in report.duplicates:
        typer.secho(f"  = línea {line}: {name} — {reason}", fg=typer.colors.YELLOW)
    for line, message in report.errors:
        typer.secho(f"  ! línea {line}: {message}", fg=typer.colors.RED)
    verb = "Se crearían" if dry_run else "Creadas"
    typer.secho(
        f"{verb} {len(report.to_create)} empresas en 0-Lead; "
        f"{len(report.duplicates)} duplicadas y {len(report.errors)} con errores (omitidas).",
        fg=typer.colors.GREEN,
    )
    if dry_run:
        typer.echo("Modo --dry-run: no se ha escrito nada.")


@app.command("exportar-obsidian")
def export_obsidian(
    dry_run: bool = typer.Option(False, "--dry-run", help="Enseña la tabla sin escribir."),
) -> None:
    """Escribe la tabla resumen entre los marcadores de negocio/clientes_potenciales.md."""
    vault = get_settings().crm_vault_path
    if vault is None:
        _fail("Falta CRM_VAULT_PATH en el .env (ruta de la bóveda de Obsidian).")
    try:
        with session_scope(default_session_factory()) as session:
            result = export.export_summary(session, vault, dry_run=dry_run)
    except ServiceError as exc:
        _fail(str(exc))
    if dry_run:
        typer.echo(result.summary)
        typer.echo(f"\nModo --dry-run: no se ha escrito {result.path}.")
    elif result.written:
        typer.secho(f"Tabla actualizada en {result.path}.", fg=typer.colors.GREEN)
    else:
        typer.echo("La tabla ya estaba al día; no se ha tocado el archivo.")


@app.command("demo")
def load_demo(
    forzar: bool = typer.Option(False, "--forzar", help="Borra las empresas existentes antes."),
) -> None:
    """Carga empresas, clientes y facturas inventadas para ver el dashboard lleno."""
    if forzar:
        typer.confirm(
            "Se borrarán TODAS las empresas, contactos, interacciones, contratos y facturas. "
            "¿Seguir?",
            abort=True,
        )
    try:
        with session_scope(default_session_factory()) as session:
            created = demo.load_demo(session, force=forzar)
            typer.secho(f"Demo cargada: {created} empresas inventadas.", fg=typer.colors.GREEN)
    except ServiceError as exc:
        _fail(str(exc))
