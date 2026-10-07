from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crm.models import Company, Interaction, Invoice, Phase, User
from crm.services import catalog, clients, companies, dashboard, demo, users
from crm.services.companies import CompanyInput, InteractionInput
from crm.services.errors import ServiceError

TODAY = date(2026, 10, 7)  # miércoles


def test_pipeline_summary_counts_value_and_follow_ups(session: Session) -> None:
    def add(name: str, phase: Phase, value: int | None, step_in: int | None) -> int:
        when = TODAY + timedelta(days=step_in) if step_in is not None else None
        data = CompanyInput(
            name=name,
            estimated_value_cents=value,
            next_step="x" if when else "",
            next_step_date=when,
        )
        return companies.create_company(session, data, "raul", phase).id

    add("Lead", Phase.LEAD, 50_000, None)  # 0-Lead no suma en juego
    add("Identificada", Phase.IDENTIFIED, 100_000, -1)  # vencido
    add("Propuesta", Phase.PROPOSAL_SENT, 200_000, 0)  # hoy = próximo
    add("Reunión", Phase.MEETING, None, 7)  # dentro de 7 días
    add("Lejos", Phase.CONTACTED, 10_000, 8)  # fuera de la ventana
    add("Perdida", Phase.LOST, 900_000, -10)  # perdidas no cuentan como seguimiento
    company_id = add("Con charla", Phase.CONTACTED, None, None)
    for day in (TODAY - timedelta(days=2), TODAY - timedelta(days=3)):  # lunes y domingo
        companies.add_interaction(
            session,
            company_id,
            InteractionInput(occurred_on=day, channel="llamada", summary="x"),
            "r",
        )

    summary = dashboard.pipeline_summary(session, TODAY)
    assert summary.count_by_phase[Phase.LEAD.value] == 1
    assert summary.count_by_phase[Phase.CONTACTED.value] == 2
    assert Phase.WON.value not in summary.count_by_phase
    assert summary.in_play_cents == 100_000 + 200_000 + 10_000
    assert [c.name for c in summary.overdue_steps] == ["Identificada"]
    assert [c.name for c in summary.upcoming_steps] == ["Propuesta", "Reunión"]
    # Semana desde el lunes 05/10: cuenta el lunes, no el domingo 04/10.
    assert summary.interactions_this_week == 1


def test_clients_summary(session: Session) -> None:
    company = companies.create_company(session, CompanyInput(name="Cliente"), "raul")
    service_id = catalog.list_services(session)[0].id
    clients.convert_to_client(
        session,
        company.id,
        clients.ContractInput(
            service_id=service_id,
            setup_price_cents=0,
            monthly_fee_cents=12_000,
            start_date=date(2026, 1, 1),
        ),
        "raul",
    )

    def inv(number: str, issue: date, base: int, due: date, paid: date | None = None) -> None:
        clients.register_invoice(
            session,
            company.id,
            clients.InvoiceInput(
                number=number, issue_date=issue, base_cents=base, due_date=due, paid_date=paid
            ),
            "raul",
        )

    inv("A", date(2026, 10, 1), 10_000, date(2026, 10, 31))  # este mes, pendiente
    inv("B", date(2026, 8, 1), 20_000, date(2026, 9, 1))  # este año, vencida
    inv("C", date(2025, 12, 1), 40_000, date(2026, 1, 1), date(2026, 1, 2))  # año pasado, cobrada

    summary = dashboard.clients_summary(session, TODAY)
    assert summary.client_count == 1
    assert summary.mrr_cents == 12_000
    assert summary.invoiced_month_cents == 10_000
    assert summary.invoiced_year_cents == 30_000
    assert summary.pending_cents == 12_100
    assert summary.overdue_cents == 24_200
    assert [i.number for i in summary.overdue_invoices] == ["B"]


def test_demo_loads_fictitious_data_with_clients_and_overdue_invoice(session: Session) -> None:
    created = demo.load_demo(session, on=TODAY)
    assert created == session.scalar(select(func.count(Company.id))) >= 20
    summary = dashboard.clients_summary(session, TODAY)
    assert summary.client_count >= 3
    assert summary.mrr_cents > 0
    assert summary.overdue_cents > 0
    assert dashboard.pipeline_summary(session, TODAY).overdue_steps
    emails = [c.email for company in session.scalars(select(Company)) for c in company.contacts]
    assert emails and all(e.endswith("@ejemplo.com") for e in emails)
    assert session.scalar(select(func.count(Interaction.id))) > 0


def test_demo_refuses_non_empty_db_unless_forced(session: Session) -> None:
    users.create_user(session, "raul", "una-contraseña")
    demo.load_demo(session, on=TODAY)
    with pytest.raises(ServiceError, match="--forzar"):
        demo.load_demo(session, on=TODAY)
    demo.load_demo(session, force=True, on=TODAY)
    assert session.scalar(select(func.count(Company.id))) == len(demo.COMPANIES)
    assert session.scalar(select(func.count(User.id))) == 1  # los usuarios no se borran
    numbers = list(session.scalars(select(Invoice.number)))
    assert len(numbers) == len(set(numbers))
