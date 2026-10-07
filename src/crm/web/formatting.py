"""Filtros de Jinja2 con formato español (1.700,00 € · 07/10/2026)."""

from datetime import date, datetime

from crm.models import Phase

PHASE_COLORS: dict[str, str] = {
    Phase.LEAD.value: "bg-slate-100 text-slate-700",
    Phase.IDENTIFIED.value: "bg-sky-100 text-sky-800",
    Phase.CONTACTED.value: "bg-cyan-100 text-cyan-800",
    Phase.MEETING.value: "bg-indigo-100 text-indigo-800",
    Phase.DIAGNOSIS.value: "bg-violet-100 text-violet-800",
    Phase.PROPOSAL_SENT.value: "bg-amber-100 text-amber-800",
    Phase.WON.value: "bg-emerald-100 text-emerald-800",
    Phase.LOST.value: "bg-rose-100 text-rose-700",
}

INVOICE_STATUS_COLORS: dict[str, str] = {
    "cobrada": "bg-emerald-100 text-emerald-800",
    "pendiente": "bg-amber-100 text-amber-800",
    "vencida": "bg-rose-100 text-rose-700",
}


def _thousands(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def euros(cents: int | None, decimals: bool = True) -> str:
    """12345678 -> '123.456,78 €'. None -> '—'."""
    if cents is None:
        return "—"
    sign = "-" if cents < 0 else ""
    whole, rest = divmod(abs(cents), 100)
    if not decimals:
        whole = (abs(cents) + 50) // 100
        return f"{sign}{_thousands(whole)} €"
    return f"{sign}{_thousands(whole)},{rest:02d} €"


def euros_input(cents: int | None) -> str:
    """Valor para un <input>: '1700,50' (sin miles ni símbolo, fácil de editar)."""
    if cents is None:
        return ""
    whole, rest = divmod(cents, 100)
    return f"{whole},{rest:02d}" if rest else str(whole)


def spanish_date(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d/%m/%Y")


def phase_label(phase: str) -> str:
    """'3-Reunión' -> 'Reunión'."""
    return phase.split("-", 1)[1] if "-" in phase else phase


def register_filters(env_filters: dict[str, object]) -> None:
    env_filters["euros"] = euros
    env_filters["euros_input"] = euros_input
    env_filters["fecha"] = spanish_date
    env_filters["fase"] = phase_label
    env_filters["fase_color"] = lambda p: PHASE_COLORS.get(p, "bg-slate-100 text-slate-700")
    env_filters["estado_color"] = lambda s: INVOICE_STATUS_COLORS.get(str(s), "")
