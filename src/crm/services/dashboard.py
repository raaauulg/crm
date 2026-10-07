"""Cifras del dashboard: pestañas Potenciales y Clientes."""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crm.models import Company, Contract, Interaction, Invoice, Phase
from crm.services.clients import InvoiceStatus, contract_is_active, invoice_status, mrr_cents
from crm.services.clock import today

# Fases que cuentan para "€ en juego": de identificado a propuesta enviada.
IN_PLAY_PHASES = (
    Phase.IDENTIFIED,
    Phase.CONTACTED,
    Phase.MEETING,
    Phase.DIAGNOSIS,
    Phase.PROPOSAL_SENT,
)
UPCOMING_DAYS = 7


@dataclass
class PipelineSummary:
    count_by_phase: dict[str, int]
    in_play_cents: int
    overdue_steps: list[Company]
    upcoming_steps: list[Company]
    interactions_this_week: int
    total_potential: int


@dataclass
class MonthlyRevenue:
    month: str  # "2026-10"
    invoiced_cents: int
    mrr_cents: int


@dataclass
class ClientsSummary:
    client_count: int
    mrr_cents: int
    invoiced_month_cents: int
    invoiced_year_cents: int
    pending_cents: int
    overdue_cents: int
    overdue_invoices: list[Invoice] = field(default_factory=list)


def pipeline_summary(session: Session, on: date | None = None) -> PipelineSummary:
    on = on or today()
    rows = session.execute(select(Company.phase, func.count()).group_by(Company.phase)).all()
    counts = {phase.value: 0 for phase in Phase if phase is not Phase.WON}
    for phase, count in rows:
        if phase in counts:
            counts[phase] = count

    in_play = session.scalar(
        select(func.coalesce(func.sum(Company.estimated_value_cents), 0)).where(
            Company.phase.in_([p.value for p in IN_PLAY_PHASES])
        )
    )

    with_steps = list(
        session.scalars(
            select(Company)
            .where(Company.next_step_date.is_not(None))
            .where(Company.phase != Phase.LOST.value)
            .order_by(Company.next_step_date, Company.name)
        )
    )
    overdue = [c for c in with_steps if c.next_step_date and c.next_step_date < on]
    limit = on + timedelta(days=UPCOMING_DAYS)
    upcoming = [c for c in with_steps if c.next_step_date and on <= c.next_step_date <= limit]

    week_start = on - timedelta(days=on.weekday())  # lunes
    interactions = session.scalar(
        select(func.count(Interaction.id)).where(
            Interaction.occurred_on >= week_start, Interaction.occurred_on <= on
        )
    )
    return PipelineSummary(
        count_by_phase=counts,
        in_play_cents=int(in_play or 0),
        overdue_steps=overdue,
        upcoming_steps=upcoming,
        interactions_this_week=int(interactions or 0),
        total_potential=sum(counts.values()),
    )


def monthly_revenue(
    session: Session, months: int = 12, on: date | None = None
) -> list[MonthlyRevenue]:
    """Últimos `months` meses (el actual incluido): facturado (bases) y MRR a fin de mes.

    Para el mes en curso, el MRR es el de hoy.
    """
    on = on or today()
    contracts = list(session.scalars(select(Contract)))
    invoices = list(session.scalars(select(Invoice)))
    series: list[MonthlyRevenue] = []
    for back in range(months - 1, -1, -1):
        total = on.year * 12 + (on.month - 1) - back
        year, month = divmod(total, 12)
        month += 1
        next_month_start = date(year + month // 12, month % 12 + 1, 1)
        month_end = min(next_month_start - timedelta(days=1), on)
        invoiced = sum(
            i.base_cents
            for i in invoices
            if (i.issue_date.year, i.issue_date.month) == (year, month)
        )
        mrr = sum(c.monthly_fee_cents for c in contracts if contract_is_active(c, month_end))
        series.append(MonthlyRevenue(f"{year}-{month:02d}", invoiced, mrr))
    return series


def clients_summary(session: Session, on: date | None = None) -> ClientsSummary:
    """Facturado = bases imponibles (sin IVA). Pendiente y vencido = totales con IVA."""
    on = on or today()
    client_count = session.scalar(
        select(func.count(Company.id)).where(Company.phase == Phase.WON.value)
    )
    invoices = list(session.scalars(select(Invoice).order_by(Invoice.due_date)))
    month = [i for i in invoices if (i.issue_date.year, i.issue_date.month) == (on.year, on.month)]
    year = [i for i in invoices if i.issue_date.year == on.year]
    pending = [i for i in invoices if invoice_status(i, on) is InvoiceStatus.PENDING]
    overdue = [i for i in invoices if invoice_status(i, on) is InvoiceStatus.OVERDUE]
    return ClientsSummary(
        client_count=int(client_count or 0),
        mrr_cents=mrr_cents(session, on),
        invoiced_month_cents=sum(i.base_cents for i in month),
        invoiced_year_cents=sum(i.base_cents for i in year),
        pending_cents=sum(i.total_cents for i in pending),
        overdue_cents=sum(i.total_cents for i in overdue),
        overdue_invoices=overdue,
    )
