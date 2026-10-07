"""Base de los esquemas de entrada y traducción de errores de Pydantic a mensajes legibles."""

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from crm.services.errors import ServiceError


class InputModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


def validate[M: BaseModel](model: type[M], data: dict[str, Any]) -> M:
    """Valida con Pydantic y traduce el error a un ServiceError con un mensaje legible."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'dato'}: {err['msg']}"
            for err in exc.errors()
        )
        raise ServiceError(f"Datos no válidos: {problems}") from exc
