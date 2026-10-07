from datetime import date

import pytest
from sqlalchemy.orm import Session

from crm.models import Channel, Phase
from crm.services import companies
from crm.services.companies import CompanyInput, ContactInput, InteractionInput
from crm.services.errors import NotFoundError, ServiceError


def make_company(session: Session, name: str = "Carpintería Prueba", **kwargs) -> int:
    company = companies.create_company(session, CompanyInput(name=name, **kwargs), "raul")
    return company.id


def test_create_company_defaults_to_identified_and_records_author(session: Session) -> None:
    company = companies.get_company(session, make_company(session))
    assert company.phase == Phase.IDENTIFIED.value
    assert company.created_by == company.updated_by == "raul"


def test_duplicate_name_is_detected_ignoring_case_accents_and_spaces(session: Session) -> None:
    make_company(session, "Carpintería  Pérez")
    with pytest.raises(ServiceError, match="Ya existe"):
        make_company(session, "carpinteria perez")


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("  Ólvega   Talleres ", "olvega talleres"),
        ("Bodega S.L.", "bodega s l"),
        ("ÑANDÚ", "nandu"),
    ],
)
def test_normalize_name(raw: str, normalized: str) -> None:
    assert companies.normalize_name(raw) == normalized


def test_new_company_cannot_start_as_client(session: Session) -> None:
    with pytest.raises(ServiceError):
        companies.create_company(session, CompanyInput(name="X"), "raul", phase=Phase.WON)


def test_change_phase_moves_forward_and_updates_author(session: Session) -> None:
    company_id = make_company(session)
    company = companies.change_phase(session, company_id, Phase.MEETING.value, "otro")
    assert company.phase == Phase.MEETING.value
    assert company.updated_by == "otro"


@pytest.mark.parametrize("start", [p for p in Phase if p not in (Phase.WON, Phase.LOST)])
def test_lost_is_reachable_from_any_potential_phase(session: Session, start: Phase) -> None:
    company = companies.create_company(session, CompanyInput(name=f"E {start}"), "raul", start)
    assert (
        companies.change_phase(session, company.id, Phase.LOST.value, "raul").phase == "7-Perdido"
    )


@pytest.mark.parametrize("target", [Phase.WON.value, Phase.LEAD.value, "9-Inventada"])
def test_change_phase_rejects_won_lead_and_unknown(session: Session, target: str) -> None:
    company_id = make_company(session)
    with pytest.raises(ServiceError):
        companies.change_phase(session, company_id, target, "raul")


def test_change_phase_to_same_phase_is_an_error(session: Session) -> None:
    company_id = make_company(session)
    with pytest.raises(ServiceError, match="ya está"):
        companies.change_phase(session, company_id, Phase.IDENTIFIED.value, "raul")


def test_unknown_company_raises_not_found(session: Session) -> None:
    with pytest.raises(NotFoundError):
        companies.change_phase(session, 999, Phase.MEETING.value, "raul")


def test_update_company_keeps_phase_and_checks_duplicates(session: Session) -> None:
    first = make_company(session, "Uno")
    second = make_company(session, "Dos")
    companies.change_phase(session, first, Phase.CONTACTED.value, "raul")
    updated = companies.update_company(session, first, CompanyInput(name="Uno", sector="Pan"), "b")
    assert updated.phase == Phase.CONTACTED.value
    assert updated.sector == "Pan"
    with pytest.raises(ServiceError):
        companies.update_company(session, second, CompanyInput(name="uno"), "raul")


def test_set_next_step_requires_text_when_dated(session: Session) -> None:
    company_id = make_company(session)
    with pytest.raises(ServiceError):
        companies.set_next_step(session, company_id, "  ", date(2026, 10, 9), "raul")
    company = companies.set_next_step(session, company_id, "Llamar", date(2026, 10, 9), "raul")
    assert (company.next_step, company.next_step_date) == ("Llamar", date(2026, 10, 9))


def test_only_one_primary_contact(session: Session) -> None:
    company_id = make_company(session)
    first = companies.add_contact(session, company_id, ContactInput(name="A", is_primary=True), "r")
    second = companies.add_contact(
        session, company_id, ContactInput(name="B", is_primary=True), "r"
    )
    session.refresh(first)
    assert second.is_primary and not first.is_primary


def test_interactions_are_listed_newest_first(session: Session) -> None:
    company_id = make_company(session)
    for day in (3, 9, 5):
        companies.add_interaction(
            session,
            company_id,
            InteractionInput(occurred_on=date(2026, 10, day), channel=Channel.CALL, summary="x"),
            "raul",
        )
    company = companies.get_company(session, company_id)
    session.refresh(company)
    assert [i.occurred_on.day for i in company.interactions] == [9, 5, 3]


def test_search_filters_and_groups(session: Session) -> None:
    make_company(session, "Panadería Soria", sector="Alimentación", municipality="Soria")
    make_company(session, "Taller Ágreda", sector="Taller", municipality="Ágreda")
    assert [c.name for c in companies.search_companies(session, text="pana")] == ["Panadería Soria"]
    assert [c.name for c in companies.search_companies(session, municipality="Ágreda")] == [
        "Taller Ágreda"
    ]
    assert companies.search_companies(session, group="clientes") == []
    assert len(companies.search_companies(session, group="potenciales")) == 2
    names = [c.name for c in companies.search_companies(session, sort="name", descending=True)]
    assert names == ["Taller Ágreda", "Panadería Soria"]
