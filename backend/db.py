"""Postgres pool and SQL migrations."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, urlunparse

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / "migrations"
RUNTIME_ROLE = "fleetai_runtime"

pool: ConnectionPool | None = None


def database_url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip()


def _runtime_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.username or parsed.username == RUNTIME_ROLE or not parsed.password:
        return url
    password = quote(unquote(parsed.password), safe="")
    host = parsed.hostname or "127.0.0.1"
    netloc = f"{RUNTIME_ROLE}:{password}@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _ensure_runtime_role(conn, url: str) -> None:
    parsed = urlparse(url)
    password = unquote(parsed.password or "")
    if not password or parsed.username == RUNTIME_ROLE:
        return
    exists = conn.execute(
        "SELECT 1 AS ok FROM pg_roles WHERE rolname = %s",
        (RUNTIME_ROLE,),
    ).fetchone()
    if exists is None:
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                sql.Identifier(RUNTIME_ROLE),
                sql.Literal(password),
            )
        )
    else:
        conn.execute(
            sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(RUNTIME_ROLE),
                sql.Literal(password),
            )
        )
    dbname = conn.execute("SELECT current_database() AS n").fetchone()["n"]
    conn.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(dbname),
            sql.Identifier(RUNTIME_ROLE),
        )
    )
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(RUNTIME_ROLE)))
    conn.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(sql.Identifier(RUNTIME_ROLE)))
    conn.execute(
        sql.SQL(
            "GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public TO {}"
        ).format(sql.Identifier(RUNTIME_ROLE))
    )
    conn.execute(
        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(
            sql.Identifier(RUNTIME_ROLE)
        )
    )
    conn.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO {}"
        ).format(sql.Identifier(RUNTIME_ROLE))
    )


def open_pool() -> None:
    global pool
    url = database_url()
    if not url:
        pool = None
        return
    owner = ConnectionPool(
        url,
        min_size=1,
        max_size=1,
        open=True,
        kwargs={"row_factory": dict_row},
    )
    try:
        with owner.connection() as conn:
            migrate(conn)
            _ensure_runtime_role(conn, url)
            conn.commit()
    finally:
        owner.close()
    pool = ConnectionPool(
        _runtime_url(url),
        min_size=1,
        max_size=4,
        open=True,
        kwargs={"row_factory": dict_row},
    )


def close_pool() -> None:
    global pool
    if pool is not None:
        pool.close()
        pool = None


def get_pool() -> ConnectionPool:
    if pool is None:
        raise RuntimeError("database unavailable")
    return pool


def migrate(conn) -> None:
    with psycopg.ClientCursor(conn) as cur:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            cur.execute(path.read_text(encoding="utf-8"))
    conn.commit()
