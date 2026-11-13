"""Postgres pool and SQL migrations."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / "migrations"

pool: ConnectionPool | None = None


def database_url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip()


def open_pool() -> None:
    global pool
    url = database_url()
    if not url:
        pool = None
        return
    pool = ConnectionPool(
        url,
        min_size=1,
        max_size=4,
        open=True,
        kwargs={"row_factory": dict_row},
    )
    with pool.connection() as conn:
        migrate(conn)


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
