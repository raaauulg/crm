"""Login y logout."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from crm.services import users
from crm.web.deps import csrf_protect, form_str, get_session, redirect, render, safe_path

router = APIRouter(dependencies=[Depends(csrf_protect)])


@router.get("/login")
def login_form(request: Request, next: str = "/") -> Response:
    return render(request, "login.html", {"next": safe_path(next), "error": None})


@router.post("/login")
async def login(request: Request, session: Session = Depends(get_session)) -> Response:
    form = await request.form()
    target = safe_path(form_str(form, "next") or "/")
    user = users.authenticate(session, form_str(form, "username"), form_str(form, "password"))
    if user is None:
        return render(
            request,
            "login.html",
            {"next": target, "error": "Usuario o contraseña incorrectos."},
        )
    request.session.clear()  # sesión nueva al entrar (evita fijación de sesión)
    request.session["user_id"] = user.id
    return redirect(request, target, full_reload=True)


@router.post("/logout")
def logout(request: Request) -> Response:
    request.session.clear()
    return redirect(request, "/login", full_reload=True)
