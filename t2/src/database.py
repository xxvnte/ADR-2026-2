from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

import psycopg2
import psycopg2.extras

from src.config import INSERT_BATCH_SIZE, DatabaseSettings, database_settings

logger = logging.getLogger(__name__)


class DatabaseUnavailableError(RuntimeError):
    pass


def connect(settings: DatabaseSettings | None = None, dbname: str | None = None) -> Any:
    active = settings or database_settings()
    try:
        connection = psycopg2.connect(
            host=active.host,
            port=active.port,
            dbname=dbname or active.dbname,
            user=active.user,
            password=active.password,
        )
    except psycopg2.OperationalError as error:
        raise DatabaseUnavailableError(str(error)) from error
    connection.autocommit = True
    return connection


@contextmanager
def session(dbname: str | None = None) -> Iterator[Any]:
    connection = connect(dbname=dbname)
    try:
        yield connection
    finally:
        connection.close()


def execute(connection: Any, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


def fetch_all(connection: Any, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def fetch_one(connection: Any, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> dict[str, Any]:
    rows = fetch_all(connection, sql, params)
    return rows[0] if rows else {}


def fetch_scalar(connection: Any, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> Any:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    return row[0] if row else None


def execute_many(
    connection: Any,
    sql: str,
    rows: Sequence[Sequence[Any]],
    page_size: int = INSERT_BATCH_SIZE,
    template: str | None = None,
) -> None:
    with connection.cursor() as cursor:
        psycopg2.extras.execute_values(cursor, sql, rows, template=template, page_size=page_size)


def run_sql_file(connection: Any, path: Path) -> None:
    logger.info("running sql file %s", path.name)
    execute(connection, path.read_text(encoding="utf-8"))


def ensure_extensions(connection: Any) -> None:
    execute(connection, "CREATE EXTENSION IF NOT EXISTS postgis")
    execute(connection, "CREATE EXTENSION IF NOT EXISTS pgrouting")
