"""Dinero en céntimos enteros. Nunca `float`."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from crm.services.errors import ServiceError

_EURO_RE = re.compile(r"^-?\d+(\.\d{1,2})?$")
_THOUSANDS_RE = re.compile(r"^\d{1,3}(\.\d{3})+$")


def parse_euros(text: str | None) -> int | None:
    """Convierte lo que escribe una persona ("1.700,50", "1700.5", "1 700 €") en céntimos.

    Devuelve None si el texto está vacío. Formato español: el punto separa miles y la coma
    decimales. Si solo hay un punto seguido de 1 o 2 cifras, se toma como decimal.
    """
    if text is None:
        return None
    cleaned = text.strip().replace("€", "").replace(" ", "").replace(" ", "")
    if not cleaned:
        return None
    if "," in cleaned:
        integer_part = cleaned.split(",")[0].lstrip("-")
        if "." in integer_part and not _THOUSANDS_RE.match(integer_part):
            raise ServiceError(f"Importe no válido: {text!r}")
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") == 1 and len(cleaned.split(".")[1]) in (1, 2):
        pass  # "1700.5" -> decimal
    elif "." in cleaned:
        # Puntos de miles: deben separar grupos de tres cifras ("1.700.000", no "1.70.0").
        if not _THOUSANDS_RE.match(cleaned.lstrip("-")):
            raise ServiceError(f"Importe no válido: {text!r}")
        cleaned = cleaned.replace(".", "")
    if not _EURO_RE.match(cleaned):
        raise ServiceError(f"Importe no válido: {text!r}")
    try:
        return int((Decimal(cleaned) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:  # pragma: no cover - el regex ya lo filtra
        raise ServiceError(f"Importe no válido: {text!r}") from exc


def vat_cents(base_cents: int, vat_percent: int) -> int:
    """IVA redondeado al céntimo (mitad hacia arriba), con aritmética entera."""
    if base_cents < 0 or vat_percent < 0:
        raise ServiceError("La base y el IVA no pueden ser negativos.")
    return (base_cents * vat_percent + 50) // 100


def total_with_vat(base_cents: int, vat_percent: int) -> int:
    return base_cents + vat_cents(base_cents, vat_percent)
