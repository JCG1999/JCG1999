"""
Gestión de la conexión a la base de datos.

Patrón Session-per-operation:
- Cada operación obtiene una sesión nueva del pool
- La sesión se cierra automáticamente al salir del context manager
- Evita sesiones colgadas y problemas de concurrencia

Por qué no una sesión global:
- Las sesiones SQLAlchemy no son thread-safe
- Una sesión larga acumula estado en caché que puede quedar stale
- Es más fácil razonar sobre transacciones cortas y explícitas
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from storage.models import Base
from monitoring.logger import get_logger

logger = get_logger(__name__)


def create_db_engine(database_url: str, echo_sql: bool = False):
    """
    Crea el engine SQLAlchemy con configuración apropiada según el tipo de DB.

    Para SQLite:
    - check_same_thread=False: necesario para uso en múltiples threads
    - WAL mode: mejora la concurrencia en SQLite (lecturas no bloquean escrituras)

    Para PostgreSQL:
    - pool_size y max_overflow controlan el pool de conexiones
    """
    connect_args = {}
    engine_kwargs = {}

    if "sqlite" in database_url:
        connect_args["check_same_thread"] = False
        engine_kwargs["connect_args"] = connect_args

        engine = create_engine(
            database_url,
            echo=echo_sql,
            **engine_kwargs,
        )

        # Activar WAL mode en SQLite para mejor concurrencia
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    else:
        engine = create_engine(
            database_url,
            echo=echo_sql,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,  # verifica conexión antes de usarla
        )

    return engine


class Database:
    """
    Gestiona el engine y la fábrica de sesiones.
    Se instancia una vez y se reutiliza.
    """

    def __init__(self, database_url: str, echo_sql: bool = False) -> None:
        self._engine = create_db_engine(database_url, echo_sql)
        self._session_factory = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,  # objetos siguen accesibles después del commit
        )
        logger.info(f"Base de datos inicializada", url=database_url.split("@")[-1])

    def create_tables(self) -> None:
        """Crea todas las tablas si no existen. Seguro de llamar múltiples veces."""
        Base.metadata.create_all(self._engine)
        logger.info("Tablas de base de datos creadas/verificadas")

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        Context manager para operaciones con la base de datos.

        Uso:
            with db.session() as session:
                session.add(record)
                # commit automático al salir del bloque
                # rollback automático si hay excepción

        """
        sess = self._session_factory()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    def dispose(self) -> None:
        """Libera todas las conexiones del pool. Llamar al cerrar la aplicación."""
        self._engine.dispose()


_db_instance: Database | None = None


def get_database() -> Database:
    """
    Retorna la instancia singleton de Database.
    Se inicializa en la primera llamada usando la configuración activa.
    """
    global _db_instance
    if _db_instance is None:
        from config.settings import get_settings
        settings = get_settings()
        _db_instance = Database(
            database_url=settings.database.url,
            echo_sql=settings.database.echo_sql,
        )
        _db_instance.create_tables()
    return _db_instance


def reset_database() -> None:
    """Resetea la instancia singleton. Útil en tests."""
    global _db_instance
    if _db_instance is not None:
        _db_instance.dispose()
    _db_instance = None
