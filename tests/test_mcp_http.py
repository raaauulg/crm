"""MCP por HTTP en /mcp: solo con token, mismas herramientas y misma base de datos que la web."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from crm.config import Settings
from crm.services import companies, demo
from crm.web.app import create_app

TOKEN = "token-de-pruebas-" + "x" * 32
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def make_client(factory: sessionmaker[Session], token: str) -> TestClient:
    settings = Settings(_env_file=None, secret_key="clave-de-pruebas", crm_mcp_token=token)
    return TestClient(create_app(factory, settings))


@pytest.fixture
def mcp_client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with session_factory() as s:
        demo.load_demo(s)
    with make_client(session_factory, TOKEN) as client:
        yield client


def rpc(
    client: TestClient, method: str, params: dict[str, Any] | None = None, **headers: str
) -> Any:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/mcp", json=body, headers={**HEADERS, **headers})


def initialize(client: TestClient) -> None:
    params = {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    }
    response = rpc(client, "initialize", params)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("auth", ["", "Bearer ", "Bearer otro-token", f"bearer {TOKEN}x", TOKEN])
def test_without_valid_token_is_rejected(mcp_client: TestClient, auth: str) -> None:
    response = rpc(mcp_client, "tools/list", Authorization=auth)
    assert response.status_code == 401
    assert "token" in response.text


@pytest.mark.parametrize(("method", "path"), [("GET", "/mcp"), ("DELETE", "/mcp")])
def test_every_method_needs_the_token(mcp_client: TestClient, method: str, path: str) -> None:
    assert mcp_client.request(method, path).status_code == 401


def test_trailing_slash_does_not_bypass_the_token(mcp_client: TestClient) -> None:
    # FastAPI redirige /mcp/ → /mcp, que vuelve a pedir el token.
    assert mcp_client.post("/mcp/", json={}).status_code == 401


def test_tools_are_listed_and_work_over_http(
    mcp_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    initialize(mcp_client)
    tools = rpc(mcp_client, "tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} >= {"buscar_empresas", "crear_empresa"}

    response = rpc(
        mcp_client,
        "tools/call",
        {"name": "crear_empresa", "arguments": {"nombre": "Creada Por HTTP"}},
    )
    result = response.json()["result"]
    assert not result.get("isError"), result
    with session_factory() as s:
        company = companies.get_company(s, result["structuredContent"]["id"])
        assert company.created_by == "mcp"


def test_mcp_is_off_without_token(client: TestClient) -> None:
    # El fixture `client` no define CRM_MCP_TOKEN: /mcp no existe.
    assert rpc(client, "tools/list").status_code == 404


def test_short_token_refuses_to_start(session_factory: sessionmaker[Session]) -> None:
    with pytest.raises(RuntimeError, match="demasiado corto"):
        make_client(session_factory, "corto")


def test_web_still_works_with_mcp_on(mcp_client: TestClient) -> None:
    assert mcp_client.get("/login").status_code == 200
