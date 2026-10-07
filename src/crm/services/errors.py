"""Excepciones de la capa de servicios. El mensaje está pensado para enseñarlo al usuario."""


class ServiceError(ValueError):
    """Operación no válida (dato incorrecto, regla de negocio incumplida)."""


class NotFoundError(ServiceError):
    """El registro pedido no existe."""
