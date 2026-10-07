"""Dashboard con las pestañas Potenciales y Clientes."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from crm.services import dashboard
from crm.services.dashboard import UPCOMING_DAYS
from crm.web.deps import csrf_protect, get_session, render, require_user

router = APIRouter(dependencies=[Depends(require_user), Depends(csrf_protect)])


@router.get("/")
def home(
    request: Request, tab: str = "potenciales", session: Session = Depends(get_session)
) -> Response:
    tab = tab if tab in ("potenciales", "clientes") else "potenciales"
    context: dict[str, object] = {"tab": tab, "upcoming_days": UPCOMING_DAYS}
    if tab == "potenciales":
        context["pipeline"] = dashboard.pipeline_summary(session)
    else:
        context["clients"] = dashboard.clients_summary(session)
        context["monthly"] = dashboard.monthly_revenue(session)
    return render(request, "dashboard.html", context)
