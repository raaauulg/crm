"""Servidor MCP (stdio) para consultar y actualizar el CRM desde Claude.

Usa la misma capa `services` que la web. Las escrituras quedan con el autor `mcp`.
Prohibido en esta versión: borrar, enviar correos o mensajes y registrar facturas.

SDK: paquete `mcp` 2.x (`MCPServer`, antes llamado `FastMCP`).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from sqlalchemy.orm import Session, sessionmaker

from crm.db import default_session_factory, session_scope
from crm.models import Channel, Company, Phase
from crm.services import clients, companies, dashboard
from crm.services.clock import today
from crm.services.companies import CompanyInput, InteractionInput
from crm.services.errors import ServiceError
from crm.services.validation import validate
from crm.web.formatting import euros

MCP_ACTOR = "mcp"
READ_ONLY = ToolAnnotations(read_only_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False)

INSTRUCTIONS = (
    "CRM comercial de una consultoría de IA. Fases: "
    + ", ".join(p.value for p in Phase)
    + ". Importes en euros (también en céntimos en los campos *_cents). "
    "No se puede borrar, enviar mensajes ni registrar facturas desde aquí."
)


@contextmanager
def _session(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Sesión con commit/rollback. Un `ServiceError` se convierte en `ToolError`, para que
    Claude reciba el mensaje (cualquier otra excepción solo muestra un error genérico)."""
    try:
        with session_scope(factory) as session:
            yield session
    except ServiceError as exc:
        raise ToolError(str(exc)) from exc


def _date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ServiceError(f"Fecha no válida (usa AAAA-MM-DD): {text!r}") from exc


def _company_summary(c: Company) -> dict[str, Any]:
    return {
        "id": c.id,
        "nombre": c.name,
        "fase": c.phase,
        "sector": c.sector,
        "municipio": c.municipality,
        "valor_estimado": euros(c.estimated_value_cents),
        "proximo_paso": c.next_step,
        "fecha_proximo_paso": c.next_step_date.isoformat() if c.next_step_date else None,
    }


def build_server(factory: sessionmaker[Session] | None = None) -> MCPServer:
    """Crea el servidor con sus herramientas. `factory` permite usar otra BD en los tests."""
    session_factory = factory or default_session_factory()
    server = MCPServer(name="crm", instructions=INSTRUCTIONS)

    # --- Lectura -------------------------------------------------------------------------

    @server.tool(annotations=READ_ONLY)
    def buscar_empresas(
        texto: str = "", fase: str = "", grupo: str = "", limite: int = 20
    ) -> list[dict[str, Any]]:
        """Busca empresas por texto (nombre, notas, sector, municipio; sin importar tildes).

        `fase`: una fase exacta (p. ej. "3-Reunión"). `grupo`: "potenciales" o "clientes".
        """
        with _session(session_factory) as session:
            found = companies.search_companies(session, text=texto, phase=fase, group=grupo)
            return [_company_summary(c) for c in found[: max(1, min(limite, 100))]]

    @server.tool(annotations=READ_ONLY)
    def ver_empresa(empresa_id: int) -> dict[str, Any]:
        """Ficha completa: datos, notas, contactos, últimas 10 interacciones y, si es
        cliente, contratos y facturas."""
        with _session(session_factory) as session:
            c = companies.get_company(session, empresa_id)
            on = today()
            return {
                **_company_summary(c),
                "web": c.website,
                "telefono": c.phone,
                "origen": c.source,
                "servicio_interes": c.service.name if c.service else None,
                "cuota_estimada": euros(c.estimated_fee_cents),
                "puntuacion_dolor": c.pain_score,
                "notas": c.notes,
                "contactos": [
                    {
                        "nombre": k.name,
                        "cargo": k.role,
                        "telefono": k.phone,
                        "email": k.email,
                        "principal": k.is_primary,
                    }
                    for k in c.contacts
                ],
                "interacciones": [
                    {
                        "fecha": i.occurred_on.isoformat(),
                        "canal": i.channel,
                        "resumen": i.summary,
                        "resultado": i.result,
                        "autor": i.created_by,
                    }
                    for i in c.interactions[:10]
                ],
                "contratos": [
                    {
                        "servicio": k.service.name,
                        "cuota_mensual": euros(k.monthly_fee_cents),
                        "inicio": k.start_date.isoformat(),
                        "fin": k.end_date.isoformat() if k.end_date else None,
                        "activo": clients.contract_is_active(k, on),
                    }
                    for k in c.contracts
                ],
                "facturas": [
                    {
                        "numero": f.number,
                        "emision": f.issue_date.isoformat(),
                        "vencimiento": f.due_date.isoformat(),
                        "total": euros(f.total_cents),
                        "estado": clients.invoice_status(f, on).value,
                    }
                    for f in c.invoices
                ],
            }

    @server.tool(annotations=READ_ONLY)
    def proximos_pasos(dias: int = 7) -> dict[str, Any]:
        """Seguimientos vencidos y los de los próximos `dias` días (empresas no perdidas)."""
        with _session(session_factory) as session:
            on = today()
            items = companies.upcoming_steps(session, on + timedelta(days=max(0, min(dias, 365))))
            # upcoming_steps solo devuelve empresas con fecha; `or on` es para el tipado.
            overdue = [c for c in items if (c.next_step_date or on) < on]
            return {
                "hoy": on.isoformat(),
                "vencidos": [_company_summary(c) for c in overdue],
                "proximos": [_company_summary(c) for c in items if c not in overdue],
            }

    @server.tool(annotations=READ_ONLY)
    def resumen_pipeline() -> dict[str, Any]:
        """Empresas por fase, € en juego (fases 1-5), seguimientos vencidos e interacciones
        de esta semana."""
        with _session(session_factory) as session:
            p = dashboard.pipeline_summary(session)
            return {
                "empresas_por_fase": p.count_by_phase,
                "en_juego": euros(p.in_play_cents),
                "en_juego_cents": p.in_play_cents,
                "seguimientos_vencidos": len(p.overdue_steps),
                "seguimientos_proximos_7_dias": len(p.upcoming_steps),
                "interacciones_esta_semana": p.interactions_this_week,
            }

    @server.tool(annotations=READ_ONLY)
    def resumen_clientes() -> dict[str, Any]:
        """Nº de clientes, MRR, facturado del mes y del año (bases), pendiente y vencido
        (con IVA) y las facturas vencidas."""
        with _session(session_factory) as session:
            k = dashboard.clients_summary(session)
            return {
                "clientes": k.client_count,
                "mrr": euros(k.mrr_cents),
                "mrr_cents": k.mrr_cents,
                "facturado_mes": euros(k.invoiced_month_cents),
                "facturado_anio": euros(k.invoiced_year_cents),
                "pendiente_cobro": euros(k.pending_cents),
                "vencido": euros(k.overdue_cents),
                "facturas_vencidas": [
                    {
                        "empresa": i.company.name,
                        "numero": i.number,
                        "vencimiento": i.due_date.isoformat(),
                        "total": euros(i.total_cents),
                    }
                    for i in k.overdue_invoices
                ],
            }

    # --- Escritura (autor "mcp") ---------------------------------------------------------

    @server.tool(annotations=WRITE)
    def crear_empresa(
        nombre: str,
        sector: str = "",
        municipio: str = "",
        web: str = "",
        telefono: str = "",
        origen: str = "",
        notas: str = "",
        fase: str = Phase.IDENTIFIED.value,
    ) -> dict[str, Any]:
        """Da de alta una empresa potencial. Falla si ya existe una con el mismo nombre
        (sin tildes ni mayúsculas). `fase` no puede ser 6-Ganado."""
        with _session(session_factory) as session:
            try:
                phase = Phase(fase)
            except ValueError as exc:
                raise ServiceError(f"Fase desconocida: {fase!r}") from exc
            if phase is Phase.LEAD:
                raise ServiceError("0-Lead es solo para importaciones; usa 1-Identificado.")
            data = validate(
                CompanyInput,
                {
                    "name": nombre,
                    "sector": sector,
                    "municipality": municipio,
                    "website": web,
                    "phone": telefono,
                    "source": origen or "Claude (MCP)",
                    "notes": notas,
                },
            )
            company = companies.create_company(session, data, MCP_ACTOR, phase)
            return _company_summary(company)

    @server.tool(annotations=WRITE)
    def registrar_interaccion(
        empresa_id: int,
        resumen: str,
        canal: str = Channel.CALL.value,
        fecha: str = "",
        resultado: str = "",
    ) -> dict[str, Any]:
        """Apunta una llamada, visita, email, whatsapp, evento u otro. `fecha` en AAAA-MM-DD
        (por defecto, hoy)."""
        with _session(session_factory) as session:
            data = validate(
                InteractionInput,
                {
                    "occurred_on": _date(fecha) or today(),
                    "channel": canal,
                    "summary": resumen,
                    "result": resultado,
                },
            )
            interaction = companies.add_interaction(session, empresa_id, data, MCP_ACTOR)
            return {"id": interaction.id, "empresa_id": empresa_id, "guardado": True}

    @server.tool(annotations=WRITE)
    def cambiar_fase(empresa_id: int, fase: str) -> dict[str, Any]:
        """Mueve una empresa a otra fase (1 a 5 o 7-Perdido). Para 6-Ganado hace falta
        dar de alta el contrato en la web."""
        with _session(session_factory) as session:
            return _company_summary(companies.change_phase(session, empresa_id, fase, MCP_ACTOR))

    @server.tool(annotations=WRITE)
    def fijar_proximo_paso(empresa_id: int, texto: str, fecha: str = "") -> dict[str, Any]:
        """Fija el próximo paso y su fecha (AAAA-MM-DD). Texto vacío y sin fecha lo borra."""
        with _session(session_factory) as session:
            company = companies.set_next_step(session, empresa_id, texto, _date(fecha), MCP_ACTOR)
            return _company_summary(company)

    return server


def main() -> None:
    """Punto de entrada `crm-mcp`: servidor MCP por stdio."""
    build_server().run()


if __name__ == "__main__":
    main()
