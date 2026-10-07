"""Piezas comunes de la web: sesión de BD, login obligatorio, CSRF, plantillas y redirecciones."""

import secrets
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from crm.models import User
from crm.services import users
from crm.services.clock import today
from crm.services.errors import ServiceError
from crm.services.money import parse_euros
from crm.web.formatting import register_filters

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)  # autoescape activado para .html
register_filters(templates.env.filters)

# Menú: (ruta, etiqueta, icono SVG como `d` de un <path>).
templates.env.globals["nav_items"] = [
    ("/", "Inicio", "M3 12l9-8 9 8M5 10v10h14V10"),
    ("/empresas", "Empresas", "M4 21V5a2 2 0 012-2h8a2 2 0 012 2v16M9 7h2m-2 4h2m-2 4h2M2 21h20"),
    ("/kanban", "Kanban", "M4 5h4v14H4zM10 5h4v9h-4zM16 5h4v6h-4z"),
    ("/facturas", "Facturas", "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6"),
    ("/servicios", "Servicios", "M4 6h16M4 12h16M4 18h10"),
]

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


class LoginRequired(Exception):
    """Se lanza cuando una ruta protegida se pide sin sesión; la app redirige a /login."""


class CsrfError(Exception):
    """Token CSRF ausente o incorrecto."""


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return str(token)


async def csrf_protect(request: Request) -> None:
    """En POST/PUT/PATCH/DELETE exige el token de la sesión (campo de formulario o cabecera)."""
    if request.method not in UNSAFE_METHODS:
        return
    expected = request.session.get("csrf")
    if not expected:
        raise CsrfError()
    form = await request.form()
    field_value = form.get(CSRF_FIELD)
    candidates = [request.headers.get(CSRF_HEADER), field_value]
    if not any(
        isinstance(sent, str) and secrets.compare_digest(str(expected), sent) for sent in candidates
    ):
        raise CsrfError()


def require_user(request: Request, session: Session = Depends(get_session)) -> User:
    user_id = request.session.get("user_id")
    user = users.get_active_user(session, int(user_id)) if user_id else None
    if user is None:
        request.session.pop("user_id", None)
        raise LoginRequired()
    request.state.user = user
    return user


def flash(request: Request, message: str, kind: str = "ok") -> None:
    """Mensaje para enseñar en la siguiente página (tras una redirección)."""
    messages = list(request.session.get("flash", []))
    messages.append({"kind": kind, "text": message})
    request.session["flash"] = messages


def render(
    request: Request, name: str, context: dict[str, Any] | None = None, status_code: int = 200
) -> Response:
    ctx: dict[str, Any] = {
        "user": getattr(request.state, "user", None),
        "csrf_token": csrf_token(request),
        "flashes": request.session.pop("flash", []),
        "path": request.url.path,
        "today": today(),
    }
    ctx.update(context or {})
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def redirect(request: Request, url: str, full_reload: bool = False) -> Response:
    """Redirección que entiende HTMX.

    Con HTMX, `HX-Location` navega sin recargar la página; `HX-Redirect` recarga entera
    (necesario al entrar o salir, porque cambia el token CSRF de la página).
    """
    if request.headers.get("HX-Request"):
        header = "HX-Redirect" if full_reload else "HX-Location"
        return Response(status_code=200, headers={header: url})
    return RedirectResponse(url, status_code=303)


def safe_path(target: str, default: str = "/") -> str:
    """Solo rutas internas: evita redirecciones abiertas a otros dominios."""
    has_control = any(ord(c) < 0x20 or ord(c) == 0x7F for c in target)
    is_internal = target.startswith("/") and not target.startswith("//") and "\\" not in target
    if is_internal and not has_control:
        return target
    return default


def login_redirect(request: Request) -> Response:
    # Solo se vuelve a páginas (GET): tras entrar, un POST repetido como GET daría 405.
    target = request.url.path if request.method == "GET" else "/"
    if request.method == "GET" and request.url.query:
        target += "?" + request.url.query
    url = f"/login?next={quote(target)}"
    if request.headers.get("HX-Request"):
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


# --- Lectura de formularios --------------------------------------------------------------


def form_str(form: FormData, key: str) -> str:
    value = form.get(key)
    return value.strip() if isinstance(value, str) else ""


def form_date(form: FormData, key: str) -> date | None:
    text = form_str(form, key)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ServiceError(f"Fecha no válida en {key}: {text!r}") from exc


def form_int(form: FormData, key: str) -> int | None:
    text = form_str(form, key)
    if not text:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise ServiceError(f"Número no válido en {key}: {text!r}") from exc


def form_euros(form: FormData, key: str) -> int | None:
    return parse_euros(form_str(form, key))


def form_bool(form: FormData, key: str) -> bool:
    return form_str(form, key) in {"on", "1", "true", "sí", "si"}


def actor(user: User) -> str:
    return user.username
