"""Conexión a SQLite y fábrica de sesiones de SQLAlchemy."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from crm.config import get_settings


def make_engine(url: str) -> Engine:
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
        # SQLite no comprueba las claves foráneas si no se le pide en cada conexión.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def default_session_factory() -> sessionmaker[Session]:
    """Fábrica de sesiones con la base de datos de la configuración (crea `data/` si falta)."""
    settings = get_settings()
    settings.crm_db_path.parent.mkdir(parents=True, exist_ok=True)
    return make_session_factory(make_engine(settings.database_url))


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Sesión con commit al salir bien y rollback si hay excepción (para la CLI y el MCP)."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
