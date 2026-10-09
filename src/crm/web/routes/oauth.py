"""Rutas OAuth 2.1 estándar:
RFC 8414 metadata, RFC 7591 dynamic client registration, RFC 7636 PKCE.
"""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from crm.services import oauth
from crm.services.errors import ServiceError
from crm.web.deps import csrf_protect, get_session, render, require_user

router = APIRouter(tags=["oauth"])


def _issuer(request: Request) -> str:
    # Obtener el scheme y host del request o cabeceras del proxy
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    return f"{proto}://{host}".rstrip("/")


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/openid-configuration")
def oauth_metadata(request: Request) -> JSONResponse:
    """RFC 8414: Metadatos para descubrimiento automático por agentes MCP."""
    base = _issuer(request)
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
            "scopes_supported": ["mcp"],
        }
    )


@router.post("/oauth/register")
async def register_client_endpoint(
    request: Request, session: Session = Depends(get_session)
) -> JSONResponse:
    """RFC 7591: Dynamic Client Registration para agentes de IA que se auto-registran."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Cuerpo JSON no válido") from None

    client_name = data.get("client_name", "Agente MCP")
    redirect_uris = data.get("redirect_uris", [])
    grant_types = data.get("grant_types", ["authorization_code"])
    response_types = data.get("response_types", ["code"])

    try:
        client, client_secret = oauth.register_client(
            session,
            client_name=client_name,
            redirect_uris=redirect_uris,
            grant_types=grant_types,
            response_types=response_types,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse(
        {
            "client_id": client.client_id,
            "client_secret": client_secret,
            "client_name": client.client_name,
            "redirect_uris": redirect_uris,
            "grant_types": grant_types,
            "response_types": response_types,
        },
        status_code=201,
    )


@router.get("/oauth/authorize")
def authorize_page(
    request: Request,
    client_id: str = "",
    redirect_uri: str = "",
    code_challenge: str = "",
    response_type: str = "code",
    code_challenge_method: str = "S256",
    state: str = "",
    scope: str = "mcp",
    session: Session = Depends(get_session),
) -> Response:
    """Pantalla de consentimiento OAuth: exige usuario autenticado."""
    user = require_user(request, session)

    if not client_id:
        raise HTTPException(status_code=400, detail="client_id es obligatorio")
    client = oauth.get_client(session, client_id)
    if not client:
        raise HTTPException(status_code=400, detail="client_id no encontrado")
    if not redirect_uri or not oauth.validate_redirect_uri(client, redirect_uri):
        raise HTTPException(status_code=400, detail="redirect_uri no permitida")
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Solo se soporta response_type=code")
    if not code_challenge:
        raise HTTPException(status_code=400, detail="code_challenge es obligatorio (PKCE)")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="Solo se soporta code_challenge_method=S256")

    return render(
        request,
        "oauth_authorize.html",
        {
            "user": user,
            "client": client,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": scope,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        },
    )


@router.post("/oauth/authorize", dependencies=[Depends(csrf_protect)])
def process_authorization(
    request: Request,
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form("S256"),
    state: str = Form(""),
    scope: str = Form("mcp"),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """El usuario pulsa 'Autorizar'."""
    user = require_user(request, session)
    client = oauth.get_client(session, client_id)
    if not client:
        raise HTTPException(status_code=400, detail="client_id no encontrado")

    try:
        code = oauth.create_authorization_code(
            session,
            client=client,
            user=user,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    params = {"code": code}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    target = f"{redirect_uri}{sep}{urlencode(params)}"
    return RedirectResponse(target, status_code=302)


@router.post("/oauth/token")
async def token_endpoint(
    request: Request,
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Canje de código por access_token con validación PKCE."""
    # Los clientes pueden enviar datos como form-urlencoded o JSON
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
    else:
        form = await request.form()
        data = dict(form)

    grant_type = data.get("grant_type")
    if grant_type != "authorization_code":
        return JSONResponse(
            {"error": "unsupported_grant_type", "error_description": "Solo authorization_code"},
            status_code=400,
        )

    client_id = data.get("client_id")
    code = data.get("code")
    redirect_uri = data.get("redirect_uri")
    code_verifier = data.get("code_verifier")
    client_secret = data.get("client_secret")

    if not all([client_id, code, redirect_uri, code_verifier]):
        return JSONResponse(
            {"error": "invalid_request", "error_description": "Faltan parámetros requeridos"},
            status_code=400,
        )

    try:
        access_token, expires_in = oauth.exchange_code_for_token(
            session,
            client_id=str(client_id),
            code=str(code),
            code_verifier=str(code_verifier),
            redirect_uri=str(redirect_uri),
            client_secret=str(client_secret) if client_secret else None,
        )
    except ServiceError as exc:
        return JSONResponse(
            {"error": "invalid_grant", "error_description": str(exc)},
            status_code=400,
        )

    return JSONResponse(
        {
            "access_token": access_token.token,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "scope": access_token.scope,
        }
    )
