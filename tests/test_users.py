"""Usuarios: alta, hash de contraseña y autenticación."""

import pytest
from sqlalchemy.orm import Session

from crm.services import users
from crm.services.errors import ServiceError


def test_create_user_normalizes_username_and_hashes_password(session: Session) -> None:
    user = users.create_user(session, "  Lucia.Prueba ", "clave-segura-123")
    assert user.username == "lucia.prueba"
    assert user.password_hash != "clave-segura-123"
    assert "clave-segura-123" not in user.password_hash
    assert user.password_hash.startswith("$argon2")
    assert user.is_active


@pytest.mark.parametrize(
    ("username", "password"),
    [("   ", "clave-segura-123"), ("lucia", "corta"), ("lucia", "1234567")],
)
def test_create_user_rejects_empty_name_or_short_password(
    session: Session, username: str, password: str
) -> None:
    with pytest.raises(ServiceError):
        users.create_user(session, username, password)


def test_create_user_rejects_duplicate_ignoring_case(session: Session) -> None:
    users.create_user(session, "lucia", "clave-segura-123")
    with pytest.raises(ServiceError, match="Ya existe"):
        users.create_user(session, "LUCIA", "otra-clave-larga")


def test_authenticate_ok_and_case_insensitive_username(session: Session) -> None:
    created = users.create_user(session, "lucia", "clave-segura-123")
    assert users.authenticate(session, " Lucia ", "clave-segura-123") is created


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("lucia", "clave-incorrecta"),
        ("lucia", ""),
        ("lucia", "CLAVE-SEGURA-123"),  # la contraseña sí distingue mayúsculas
        ("nadie", "clave-segura-123"),
    ],
)
def test_authenticate_rejects_wrong_password_or_unknown_user(
    session: Session, username: str, password: str
) -> None:
    users.create_user(session, "lucia", "clave-segura-123")
    assert users.authenticate(session, username, password) is None


def test_inactive_user_cannot_authenticate_nor_be_loaded(session: Session) -> None:
    user = users.create_user(session, "lucia", "clave-segura-123")
    user.is_active = False
    session.commit()
    assert users.authenticate(session, "lucia", "clave-segura-123") is None
    assert users.get_active_user(session, user.id) is None


def test_get_active_user_unknown_id_is_none(session: Session) -> None:
    assert users.get_active_user(session, 4242) is None
