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
from crm.services import oauth

MCP_PATH = "/mcp"
MIN_TOKEN_LENGTH = 32


class BearerTokenGuard:
    """Middleware ASGI: rechaza con 401 si no hay token Bearer estático o token OAuth válido."""

    def __init__(
        self,
        app: ASGIApp,
        static_token: str | None,
        session_factory: sessionmaker[Session],
    ) -> None:
        self.app = app
        self.static_token_expected = f"Bearer {static_token}".encode() if static_token else None
        self.session_factory = session_factory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        raw_auth = Headers(scope=scope).get("authorization", "")
        sent = raw_auth.encode()

        is_valid = False
        # 1. Comprobar token estático (si está configurado)
        if self.static_token_expected and secrets.compare_digest(sent, self.static_token_expected):
            is_valid = True
        elif raw_auth.startswith("Bearer "):
            # 2. Comprobar token OAuth en la base de datos
            token_candidate = raw_auth[len("Bearer ") :].strip()
            with self.session_factory() as session:
                token_record = oauth.verify_access_token(session, token_candidate)
                if token_record is not None:
                    is_valid = True

        if not is_valid:
            # Obtener el host para formar la cabecera estándar de descubrimiento OAuth
            headers_dict = dict(Headers(scope=scope))
            proto = headers_dict.get(
                "x-forwarded-proto", "https" if scope.get("type") == "https" else "http"
            )
            host = headers_dict.get("x-forwarded-host") or headers_dict.get("host", "127.0.0.1")
            issuer = f"{proto}://{host}".rstrip("/")
            auth_header = (
                f'Bearer realm="CRM MCP", '
                f'resource_metadata="{issuer}/.well-known/oauth-authorization-server"'
            )
            response = PlainTextResponse(
                "Falta el token del MCP o no es válido.",
                status_code=401,
                headers={"WWW-Authenticate": auth_header},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def mcp_route(
    token: str | None, session_factory: sessionmaker[Session]
) -> tuple[Route, Callable[[], AbstractAsyncContextManager[None]]]:
    """Devuelve la ruta `/mcp` y el contexto que hay que abrir en el `lifespan` de la app."""
    if token and len(token) < MIN_TOKEN_LENGTH:
        raise RuntimeError(
            f"CRM_MCP_TOKEN es demasiado corto (mínimo {MIN_TOKEN_LENGTH} caracteres). "
            'Genera uno con: uv run python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    server = build_server(session_factory)
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

    return Route(MCP_PATH, endpoint=BearerTokenGuard(mcp_app, token, session_factory)), lifespan
