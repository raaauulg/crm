"""Servidor MCP: herramientas registradas, lectura sin efectos, escrituras con autor `mcp`
y errores legibles para el modelo."""

import asyncio
import json
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from crm.mcp_server import build_server
from crm.models import Company, Interaction, Phase
from crm.services import companies, demo

READ_TOOLS = {
    "buscar_empresas",
    "ver_empresa",
    "proximos_pasos",
    "resumen_pipeline",
    "resumen_clientes",
}
WRITE_TOOLS = {"crear_empresa", "registrar_interaccion", "cambiar_fase", "fijar_proximo_paso"}


@pytest.fixture
def server(session_factory: sessionmaker[Session]):  # noqa: ANN201
    with session_factory() as s:
        demo.load_demo(s)
    return build_server(session_factory)


def call(server, name: str, args: dict[str, Any] | None = None) -> Any:  # noqa: ANN001
    result = asyncio.run(server.call_tool(name, args or {}))
    assert not result.is_error, result
    data = result.structured_content
    if data is None:
        return json.loads(result.content[0].text)
    # Las listas se envuelven como {"result": [...]} en la salida estructurada.
    return data["result"] if set(data) == {"result"} else data


def snapshot(factory: sessionmaker[Session]) -> tuple:
    with factory() as s:
        return (
            s.scalar(select(func.count(Company.id))),
            s.scalar(select(func.count(Interaction.id))),
            tuple(s.execute(select(Company.id, Company.phase, Company.updated_at)).all()),
        )


def test_only_the_allowed_tools_exist(server) -> None:  # noqa: ANN001
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == READ_TOOLS | WRITE_TOOLS
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is (tool.name in READ_TOOLS)
    names = " ".join(t.name for t in tools)
    for forbidden in ("borrar", "eliminar", "enviar", "factura"):
        assert forbidden not in names


def test_read_tools_do_not_modify(server, session_factory) -> None:  # noqa: ANN001
    before = snapshot(session_factory)
    found = call(server, "buscar_empresas", {"texto": "agreda"})
    assert found and all("Ágreda" in c["municipio"] for c in found)
    detail = call(server, "ver_empresa", {"empresa_id": found[0]["id"]})
    assert detail["nombre"] == found[0]["nombre"]
    assert "vencidos" in call(server, "proximos_pasos", {"dias": 7})
    assert call(server, "resumen_pipeline")["en_juego_cents"] > 0
    clientes = call(server, "resumen_clientes")
    assert clientes["mrr_cents"] > 0 and clientes["facturas_vencidas"]
    assert snapshot(session_factory) == before


def test_write_tools_record_mcp_author(server, session_factory) -> None:  # noqa: ANN001
    created = call(server, "crear_empresa", {"nombre": "Creada Por Claude", "municipio": "Soria"})
    company_id = created["id"]
    call(server, "registrar_interaccion", {"empresa_id": company_id, "resumen": "Llamada"})
    call(server, "cambiar_fase", {"empresa_id": company_id, "fase": Phase.CONTACTED.value})
    call(
        server,
        "fijar_proximo_paso",
        {"empresa_id": company_id, "texto": "Enviar propuesta", "fecha": "2026-10-20"},
    )
    with session_factory() as s:
        company = companies.get_company(s, company_id)
        assert company.created_by == "mcp" and company.updated_by == "mcp"
        assert company.phase == Phase.CONTACTED.value
        assert company.next_step == "Enviar propuesta"
        assert company.interactions[0].created_by == "mcp"


@pytest.mark.parametrize(
    ("tool", "args", "message"),
    [
        ("cambiar_fase", {"empresa_id": 1, "fase": "6-Ganado"}, "Convertir en cliente"),
        ("ver_empresa", {"empresa_id": 99999}, "No existe"),
        ("crear_empresa", {"nombre": "Carpinteria pino ficticio"}, "Ya existe"),
        ("crear_empresa", {"nombre": "Nueva", "fase": "9-Inventada"}, "Fase desconocida"),
        ("fijar_proximo_paso", {"empresa_id": 1, "texto": "x", "fecha": "mañana"}, "Fecha"),
        ("registrar_interaccion", {"empresa_id": 1, "resumen": "x", "canal": "paloma"}, "llamada"),
    ],
)
def test_errors_reach_the_model_with_a_useful_message(
    server,
    tool: str,
    args: dict[str, Any],
    message: str,  # noqa: ANN001
) -> None:
    with pytest.raises(ToolError, match=message) as info:
        asyncio.run(server.call_tool(tool, args))
    assert not isinstance(info.value, UnexpectedToolError)  # error previsto, no un fallo
