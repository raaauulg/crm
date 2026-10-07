"""Fecha y hora en Europe/Madrid. Todo el CRM pregunta aquí qué día es hoy."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")


def now() -> datetime:
    """Hora local de Madrid, sin zona (SQLite no guarda zonas horarias)."""
    return datetime.now(TZ).replace(tzinfo=None)


def today() -> date:
    return datetime.now(TZ).date()
