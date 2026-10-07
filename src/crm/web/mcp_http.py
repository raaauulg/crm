"""MCP por HTTP (Streamable HTTP) en `/mcp`, protegido con un token fijo.

Es el mismo servidor que `crm-mcp` (stdio), pero dentro de la web: un único proceso escribe
en SQLite y las herramientas usan la misma fábrica de sesiones que las páginas.
Solo se activa si `CRM_MCP_TOKEN` está definido.
"""

import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from crm.mcp_server import build_server

MCP_PATH = "/mcp"
MIN_TOKEN_LENGTH = 32


class BearerTokenGuard:
    """Middleware ASGI: rechaza con 401 toda petición sin `Authorization: Bearer <token>`."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        sent = Headers(scope=scope).get("authorization", "").encode()
        # compare_digest: tarda lo mismo acierte o no (no da pistas sobre el token).
        if not secrets.compare_digest(sent, self.expected):
            response = PlainTextResponse(
                "Falta el token del MCP o no es válido.",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def mcp_route(
    token: str, session_factory: sessionmaker[Session]
) -> tuple[Route, Callable[[], AbstractAsyncContextManager[None]]]:
    """Devuelve la ruta `/mcp` y el contexto que hay que abrir en el `lifespan` de la app."""
    if len(token) < MIN_TOKEN_LENGTH:
        raise RuntimeError(
            f"CRM_MCP_TOKEN es demasiado corto (mínimo {MIN_TOKEN_LENGTH} caracteres). "
            'Genera uno con: uv run python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    server = build_server(session_factory)
    # Sin estado (`stateless_http`) y con respuestas JSON: cada petición es independiente,
    # así que un reinicio del contenedor no rompe la conexión de Claude.
    # La protección contra DNS rebinding del SDK compara la cabecera Host con una lista; aquí
    # no aporta nada porque el navegador no conoce el token. Se desactiva para no tener que
    # mantener la lista de dominios.
    mcp_app = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @asynccontextmanager
    async def lifespan() -> AsyncIterator[None]:
        async with server.session_manager.run():
            yield

    return Route(MCP_PATH, endpoint=BearerTokenGuard(mcp_app, token)), lifespan
