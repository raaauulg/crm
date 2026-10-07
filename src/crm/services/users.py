"""Usuarios y contraseñas (hash argon2 con `argon2-cffi`)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from crm.models import User
from crm.services.errors import ServiceError

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 8


def create_user(session: Session, username: str, password: str) -> User:
    username = username.strip().lower()
    if not username:
        raise ServiceError("El nombre de usuario no puede estar vacío.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ServiceError(f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.")
    if session.scalar(select(User).where(User.username == username)):
        raise ServiceError(f"Ya existe el usuario {username!r}.")
    user = User(username=username, password_hash=_hasher.hash(password))
    session.add(user)
    session.commit()
    return user


def authenticate(session: Session, username: str, password: str) -> User | None:
    """Devuelve el usuario si la contraseña es correcta y está activo; si no, None."""
    user = session.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None or not user.is_active:
        # Calcula un hash igualmente para no revelar por el tiempo si el usuario existe.
        _hasher.hash(password)
        return None
    try:
        _hasher.verify(user.password_hash, password)
    except (VerificationError, InvalidHashError):
        return None
    return user


def get_active_user(session: Session, user_id: int) -> User | None:
    user = session.get(User, user_id)
    return user if user is not None and user.is_active else None
