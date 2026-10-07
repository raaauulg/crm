"""Línea de comandos: `uv run crm --help`."""

import logging

import typer

from crm.config import get_settings
from crm.db import default_session_factory, session_scope
from crm.services import demo, users
from crm.services.errors import ServiceError

app = typer.Typer(help="CRM de la consultoría.", no_args_is_help=True, add_completion=False)


def _fail(message: str) -> None:
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
