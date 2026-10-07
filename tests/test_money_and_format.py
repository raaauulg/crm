from datetime import date

import pytest

from crm.services.errors import ServiceError
from crm.services.money import parse_euros
from crm.web.formatting import euros, euros_input, spanish_date


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("1.700,50", 170_050),
        ("1700,5", 170_050),
        ("1700.5", 170_050),
        ("1.700", 170_000),
        ("1 700 €", 170_000),
        ("120", 12_000),
        ("0,01", 1),
        ("", None),
        (None, None),
    ],
)
def test_parse_euros(text: str | None, cents: int | None) -> None:
    assert parse_euros(text) == cents


@pytest.mark.parametrize("text", ["abc", "1,2,3", "12,345"])
def test_parse_euros_rejects_garbage(text: str) -> None:
    with pytest.raises(ServiceError):
        parse_euros(text)


def test_spanish_formats() -> None:
    assert euros(170_000) == "1.700,00 €"
    assert euros(123_456_789) == "1.234.567,89 €"
    assert euros(-550) == "-5,50 €"
    assert euros(None) == "—"
    assert euros(170_050, decimals=False) == "1.701 €"
    assert euros_input(170_050) == "1700,50"
    assert euros_input(12_000) == "120"
    assert spanish_date(date(2026, 10, 7)) == "07/10/2026"
