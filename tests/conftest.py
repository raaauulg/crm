"""Fixtures comunes: base de datos SQLite temporal y cliente web con sesión iniciada."""

import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from crm.config import Settings
from crm.db import make_engine, make_session_factory
from crm.models import Base
from crm.services import users
from crm.services.catalog import ensure_default_catalog
from crm.web.app import create_app
from crm.web.routes.auth import _FAILED_ATTEMPTS

TEST_USER = "raul"
TEST_PASSWORD = "contraseña-de-prueba"
CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.fixture(autouse=True)
def _reset_login_rate_limiter() -> Iterator[None]:
    _FAILED_ATTEMPTS.clear()
    yield
    _FAILED_ATTEMPTS.clear()


@pytest.fixture
def session_factory(tmp_path) -> Iterator[sessionmaker[Session]]:
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as s:
        ensure_default_catalog(s)
        yield s


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """Cliente sin sesión iniciada (con un usuario ya creado)."""
    with session_factory() as s:
        users.create_user(s, TEST_USER, TEST_PASSWORD)
    settings = Settings(_env_file=None, secret_key="clave-de-pruebas")
    app = create_app(session_factory, settings)
    with TestClient(app) as test_client:
        yield test_client


def csrf_from(html: str) -> str:
    match = CSRF_RE.search(html)
    assert match, "La página no tiene token CSRF"
    return match.group(1)


def login(client: TestClient, password: str = TEST_PASSWORD) -> TestClient:
    token = csrf_from(client.get("/login").text)
    client.post(
        "/login",
        data={"username": TEST_USER, "password": password, "csrf_token": token, "next": "/"},
        follow_redirects=False,
    )
    return client


@pytest.fixture
def auth_client(client: TestClient) -> TestClient:
    """Cliente con la sesión iniciada."""
    return login(client)


def post_form(client: TestClient, url: str, data: dict[str, str], page: str = "/"):  # noqa: ANN201
    """POST con el token CSRF sacado de `page` (como haría el navegador)."""
    token = csrf_from(client.get(page).text)
    return client.post(url, data={**data, "csrf_token": token}, follow_redirects=False)
