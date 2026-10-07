"""Fábrica de la aplicación FastAPI."""

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from crm.config import Settings, get_settings
from crm.db import default_session_factory
from crm.services.catalog import ensure_default_catalog
from crm.services.errors import NotFoundError
from crm.web.deps import CsrfError, LoginRequired, login_redirect
from crm.web.mcp_http import MCP_PATH, mcp_route
from crm.web.routes import auth, catalog, clients, companies, dashboard, kanban

logger = logging.getLogger(__name__)

SESSION_MAX_AGE = 14 * 24 * 60 * 60  # 14 días


def _secret_key(settings: Settings) -> str:
    if settings.secret_key:
        return settings.secret_key
    logger.warning(
        "SECRET_KEY no está definida: uso una aleatoria. Las sesiones se perderán al reiniciar."
    )
    return secrets.token_urlsafe(48)


def create_app(
    session_factory: sessionmaker[Session] | None = None, settings: Settings | None = None
) -> FastAPI:
    settings = settings or get_settings()
    factory = session_factory or default_session_factory()

    mcp = mcp_route(settings.crm_mcp_token, factory) if settings.crm_mcp_token else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if mcp is None:
            yield
            return
        _route, mcp_lifespan = mcp
        async with mcp_lifespan():
            yield

    app = FastAPI(title="CRM", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.session_factory = factory
    app.add_middleware(
        SessionMiddleware,
        secret_key=_secret_key(settings),
        session_cookie="crm_session",
        max_age=SESSION_MAX_AGE,
        same_site="lax",
        https_only=settings.crm_secure_cookies,
    )

    try:
        with factory() as session:
            ensure_default_catalog(session)
    except OperationalError as exc:
        raise RuntimeError(
            "La base de datos no está creada o está desactualizada. "
            "Ejecuta: uv run alembic upgrade head"
        ) from exc

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, _exc: LoginRequired) -> Response:
        return login_redirect(request)

    @app.exception_handler(CsrfError)
    async def _csrf_error(_request: Request, _exc: CsrfError) -> Response:
        return PlainTextResponse(
            "Formulario caducado o no válido (CSRF). Vuelve atrás y recarga la página.",
            status_code=403,
        )

    @app.exception_handler(NotFoundError)
    async def _not_found(_request: Request, exc: NotFoundError) -> Response:
        return PlainTextResponse(str(exc), status_code=404)

    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(companies.router)
    app.include_router(clients.router)
    app.include_router(kanban.router)
    app.include_router(catalog.router)
    if mcp is not None:
        route, _lifespan = mcp
        app.router.routes.append(route)
        logger.info("MCP por HTTP activo en %s (con token).", MCP_PATH)
    return app
