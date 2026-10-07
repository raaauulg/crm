"""Kanban de potenciales por fase."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from crm.services import companies
from crm.web.deps import csrf_protect, get_session, render, require_user

router = APIRouter(dependencies=[Depends(require_user), Depends(csrf_protect)])


@router.get("/kanban")
def kanban(request: Request, session: Session = Depends(get_session)) -> Response:
    board = companies.kanban_board(session)
    neighbours = {
        company.id: companies.neighbour_phases(company.phase)
        for cards in board.values()
        for company in cards
    }
    totals = {
        phase: sum(c.estimated_value_cents or 0 for c in cards) for phase, cards in board.items()
    }
    return render(
        request, "kanban.html", {"board": board, "neighbours": neighbours, "totals": totals}
    )
