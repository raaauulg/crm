"""Login y logout."""

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from crm.services import users
from crm.web.deps import csrf_protect, form_str, get_session, redirect, render, safe_path

router = APIRouter(dependencies=[Depends(csrf_protect)])

# Limiter en memoria: máximo 5 intentos fallidos por IP en 5 minutos
_FAILED_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
MAX_ATTEMPTS = 5
LOCKOUT_WINDOW = 300.0  # 5 minutos


def _get_client_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )


@router.get("/login")
def login_form(request: Request, next: str = "/") -> Response:
    return render(request, "login.html", {"next": safe_path(next), "error": None})


@router.post("/login")
async def login(request: Request, session: Session = Depends(get_session)) -> Response:
    form = await request.form()
    target = safe_path(form_str(form, "next") or "/")
    ip = _get_client_ip(request)
    now_ts = time.time()

    # Limpiar intentos fuera de la ventana
    _FAILED_ATTEMPTS[ip] = [t for t in _FAILED_ATTEMPTS[ip] if now_ts - t < LOCKOUT_WINDOW]
    if len(_FAILED_ATTEMPTS[ip]) >= MAX_ATTEMPTS:
        return render(
            request,
            "login.html",
            {
                "next": target,
                "error": "Demasiados intentos fallidos. Por seguridad, espera 5 minutos.",
            },
            status_code=429,
        )

    user = users.authenticate(session, form_str(form, "username"), form_str(form, "password"))
    if user is None:
        _FAILED_ATTEMPTS[ip].append(now_ts)
        return render(
            request,
            "login.html",
            {"next": target, "error": "Usuario o contraseña incorrectos."},
        )

    # Login correcto: resetear contador
    _FAILED_ATTEMPTS.pop(ip, None)
    request.session.clear()  # sesión nueva al entrar (evita fijación de sesión)
    request.session["user_id"] = user.id
    return redirect(request, target, full_reload=True)


@router.post("/logout")
def logout(request: Request) -> Response:
    request.session.clear()
    return redirect(request, "/login", full_reload=True)
