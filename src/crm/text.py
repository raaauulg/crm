"""Normalización de texto para comparar y buscar sin tildes ni mayúsculas."""

import unicodedata


def fold(text: str | None) -> str:
    """'  Ólvega   Talleres S.L.' -> 'olvega talleres s l'.

    Sin tildes, minúsculas, signos convertidos en espacios y espacios simples. Se usa para
    detectar duplicados y, registrada en SQLite como `crm_fold`, para buscar.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    alnum = "".join(c if c.isalnum() else " " for c in without_accents.lower())
    return " ".join(alnum.split())
