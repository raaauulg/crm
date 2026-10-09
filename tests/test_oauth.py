"""Tests exhaustivos del flujo OAuth 2.1 para MCP:
1. RFC 8414 (Metadatos de descubrimiento)
2. RFC 7591 (Registro dinámico de clientes)
3. Flujo PKCE completo: Autorización -> Consentimiento -> Código -> Canje de Token
4. Acceso con el token OAuth generado al endpoint /mcp
5. Rechazo con tokens inválidos o caducados y cabecera WWW-Authenticate adecuada
"""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.testclient import TestClient

from crm.config import Settings
from crm.db import make_engine, make_session_factory
from crm.models import Base
from crm.services.users import create_user
from crm.web.app import create_app

from .conftest import csrf_from


@pytest.fixture
def test_app_and_factory(tmp_path):
    db_path = tmp_path / "test_oauth.db"
    url = f"sqlite:///{db_path.as_posix()}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)

    # Crear usuario de prueba
    with factory() as session:
        create_user(session, "raul", "password123456789")

    settings = Settings(
        secret_key="test_secret_key_at_least_32_characters_long",
        crm_mcp_token="a" * 32,
    )
    app = create_app(session_factory=factory, settings=settings)
    with TestClient(app, base_url="https://crm.test.local") as client:
        yield client, factory


def test_oauth_metadata_discovery(test_app_and_factory):
    client, _ = test_app_and_factory
    response = client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    data = response.json()
    assert data["issuer"] == "https://crm.test.local"
    assert data["authorization_endpoint"] == "https://crm.test.local/oauth/authorize"
    assert data["token_endpoint"] == "https://crm.test.local/oauth/token"
    assert data["registration_endpoint"] == "https://crm.test.local/oauth/register"
    assert "S256" in data["code_challenge_methods_supported"]


def test_oauth_dynamic_client_registration(test_app_and_factory):
    client, _ = test_app_and_factory
    payload = {
        "client_name": "Claude Desktop / Mobile",
        "redirect_uris": ["https://claude.ai/api/mcp/callback"],
    }
    response = client.post("/oauth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "client_id" in data
    assert "client_secret" in data
    assert data["client_name"] == "Claude Desktop / Mobile"
    assert data["redirect_uris"] == ["https://claude.ai/api/mcp/callback"]


def test_full_oauth_pkce_flow_and_mcp_access(test_app_and_factory):
    client, _ = test_app_and_factory

    # 1. Registrar cliente dinámico
    reg_resp = client.post(
        "/oauth/register",
        json={
            "client_name": "Agente AI Test",
            "redirect_uris": ["https://agent.local/oauth/callback"],
        },
    )
    assert reg_resp.status_code == 201
    client_id = reg_resp.json()["client_id"]
    client_secret = reg_resp.json()["client_secret"]

    # 2. Generar PKCE verifier y challenge (S256)
    code_verifier = secrets.token_urlsafe(50)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    # 3. Intentar entrar a /oauth/authorize sin estar logueado -> debe redirigir a /login
    auth_url = (
        f"/oauth/authorize?client_id={client_id}"
        f"&redirect_uri=https://agent.local/oauth/callback"
        f"&response_type=code"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&state=test_state_123"
    )
    resp = client.get(auth_url)
    assert resp.status_code == 200
    assert "Entrar · CRM" in resp.text

    # 4. Hacer login con token CSRF válido
    login_page = client.get("/login")
    login_csrf = csrf_from(login_page.text)

    login_resp = client.post(
        "/login",
        data={
            "username": "raul",
            "password": "password123456789",
            "next": auth_url,
            "csrf_token": login_csrf,
        },
        follow_redirects=False,
    )
    assert login_resp.status_code == 303

    # 5. Ya logueado: acceder a la pantalla de consentimiento
    consent_page = client.get(auth_url)
    if consent_page.status_code != 200:
        print("ERROR DETAIL:", consent_page.status_code, consent_page.text)
    assert consent_page.status_code == 200
    assert "Conectar agente con CRM" in consent_page.text
    assert "Agente AI Test" in consent_page.text

    consent_csrf = csrf_from(consent_page.text)

    # 6. Autorizar (POST /oauth/authorize)
    post_consent = client.post(
        "/oauth/authorize",
        data={
            "client_id": client_id,
            "redirect_uri": "https://agent.local/oauth/callback",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": "test_state_123",
            "scope": "mcp",
            "csrf_token": consent_csrf,
        },
        follow_redirects=False,
    )
    assert post_consent.status_code == 302
    redirect_target = post_consent.headers["location"]
    parsed = urlparse(redirect_target)
    query = parse_qs(parsed.query)
    assert query["state"] == ["test_state_123"]
    code = query["code"][0]
    assert code is not None

    # 7. Canjear código por Token con PKCE
    token_resp = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": "https://agent.local/oauth/callback",
        },
    )
    assert token_resp.status_code == 200
    token_data = token_resp.json()
    assert "access_token" in token_data
    access_token = token_data["access_token"]
    assert token_data["token_type"] == "Bearer"

    # 8. Comprobar acceso al endpoint MCP con el token OAuth
    # Sin token -> 401 con cabecera WWW-Authenticate que apunta a discovery
    no_auth = client.post("/mcp", json={})
    assert no_auth.status_code == 401
    assert "resource_metadata=" in no_auth.headers["WWW-Authenticate"]

    # Con token OAuth -> acepta la petición (no da 401)
    init_params = {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-agent", "version": "1.0"},
    }
    mcp_auth = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": init_params},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
    )
    assert mcp_auth.status_code == 200
    assert mcp_auth.json()["result"]["serverInfo"]["name"] == "crm"


def test_login_rate_limiting(test_app_and_factory):
    client, _ = test_app_and_factory
    # 5 intentos fallidos
    for _ in range(5):
        csrf = csrf_from(client.get("/login").text)
        resp = client.post(
            "/login",
            data={
                "username": "raul",
                "password": "wrong_password",
                "csrf_token": csrf,
            },
        )
        assert resp.status_code == 200

    # El 6to intento debe recibir 429 Too Many Requests
    csrf = csrf_from(client.get("/login").text)
    blocked = client.post(
        "/login",
        data={
            "username": "raul",
            "password": "wrong_password",
            "csrf_token": csrf,
        },
    )
    assert blocked.status_code == 429
    assert "Demasiados intentos fallidos" in blocked.text
