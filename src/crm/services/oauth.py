"""Lógica de negocio para OAuth 2.1 (RFC 7591 Dynamic Client Registration, PKCE RFC 7636)."""

import base64
import hashlib
import json
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from crm.models import OAuthAccessToken, OAuthAuthorizationCode, OAuthClient, User
from crm.services.clock import now
from crm.services.errors import ServiceError

CODE_LIFETIME = timedelta(minutes=5)
TOKEN_LIFETIME = timedelta(days=30)


def register_client(
    session: Session,
    client_name: str,
    redirect_uris: list[str],
    grant_types: list[str] | None = None,
    response_types: list[str] | None = None,
) -> tuple[OAuthClient, str]:
    """Registra dinámicamente un cliente OAuth (RFC 7591). Devuelve (client, client_secret)."""
    if not client_name.strip():
        raise ServiceError("client_name es obligatorio")
    if not redirect_uris:
        raise ServiceError("Al menos una redirect_uri es obligatoria")

    client_id = secrets.token_urlsafe(24)
    client_secret = secrets.token_urlsafe(36)
    secret_hash = hashlib.sha256(client_secret.encode()).hexdigest()

    client = OAuthClient(
        client_id=client_id,
        client_secret_hash=secret_hash,
        client_name=client_name.strip(),
        redirect_uris=json.dumps(redirect_uris),
        grant_types=",".join(grant_types or ["authorization_code"]),
        response_types=",".join(response_types or ["code"]),
    )
    session.add(client)
    session.commit()
    return client, client_secret


def get_client(session: Session, client_id: str) -> OAuthClient | None:
    return session.get(OAuthClient, client_id)


def validate_redirect_uri(client: OAuthClient, redirect_uri: str) -> bool:
    try:
        allowed = json.loads(client.redirect_uris)
        return redirect_uri in allowed
    except Exception:
        return False


def create_authorization_code(
    session: Session,
    client: OAuthClient,
    user: User,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    scope: str = "mcp",
) -> str:
    """Crea un código de autorización temporal con PKCE."""
    if not validate_redirect_uri(client, redirect_uri):
        raise ServiceError("redirect_uri no permitida para este cliente")
    if code_challenge_method != "S256":
        raise ServiceError("Solo se soporta code_challenge_method=S256")
    if not code_challenge or len(code_challenge) < 40:
        raise ServiceError("code_challenge no válido")

    code = secrets.token_urlsafe(40)
    auth_code = OAuthAuthorizationCode(
        code=code,
        client_id=client.client_id,
        user_id=user.id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        scope=scope,
        expires_at=now() + CODE_LIFETIME,
    )
    session.add(auth_code)
    session.commit()
    return code


def _verify_pkce_s256(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return secrets.compare_digest(computed, challenge.rstrip("="))


def exchange_code_for_token(
    session: Session,
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_secret: str | None = None,
) -> tuple[OAuthAccessToken, int]:
    """Canjea un código de autorización y verifica PKCE. Devuelve (token, expires_in_seconds)."""
    client = get_client(session, client_id)
    if not client:
        raise ServiceError("Cliente no encontrado")

    if client.client_secret_hash and client_secret:
        given_hash = hashlib.sha256(client_secret.encode()).hexdigest()
        if not secrets.compare_digest(client.client_secret_hash, given_hash):
            raise ServiceError("client_secret incorrecto")

    auth_code = session.get(OAuthAuthorizationCode, code)
    if not auth_code:
        raise ServiceError("Código de autorización no válido")
    if auth_code.client_id != client_id:
        raise ServiceError("Código no pertenece a este cliente")
    if auth_code.used_at is not None:
        raise ServiceError("El código ya ha sido utilizado")
    if auth_code.expires_at < now():
        raise ServiceError("El código ha caducado")
    if auth_code.redirect_uri != redirect_uri:
        raise ServiceError("redirect_uri no coincide con la original")

    if not _verify_pkce_s256(code_verifier, auth_code.code_challenge):
        raise ServiceError("PKCE verification failed: code_verifier incorrecto")

    auth_code.used_at = now()

    token_str = secrets.token_urlsafe(48)
    expires_at = now() + TOKEN_LIFETIME
    access_token = OAuthAccessToken(
        token=token_str,
        client_id=client_id,
        user_id=auth_code.user_id,
        scope=auth_code.scope,
        expires_at=expires_at,
    )
    session.add(access_token)
    session.commit()

    expires_in = int(TOKEN_LIFETIME.total_seconds())
    return access_token, expires_in


def verify_access_token(session: Session, token: str) -> OAuthAccessToken | None:
    """Verifica si un token de acceso es válido, está activo y no ha caducado."""
    if not token or len(token) < 20:
        return None
    stmt = select(OAuthAccessToken).where(
        OAuthAccessToken.token == token,
        OAuthAccessToken.revoked_at.is_(None),
        OAuthAccessToken.expires_at > now(),
    )
    return session.scalar(stmt)
