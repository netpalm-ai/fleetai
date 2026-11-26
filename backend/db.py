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


def refuse_live_wipe(conn) -> None:
    row = conn.execute("SELECT current_setting('cluster_name', true) AS name").fetchone()
    if row is None or row["name"] != "fleetai-ci":
        raise RuntimeError(
            "refusing to wipe this database. It is not a disposable test database, and the operator has not agreed to delete it."
        )


def get_pool() -> ConnectionPool:
    if pool is None:
        raise RuntimeError("database unavailable")
    return pool


def migrate(conn) -> None:
    with psycopg.ClientCursor(conn) as cur:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            cur.execute(path.read_text(encoding="utf-8"))
    _seed_codebase_contexts(conn)
    _seed_minh_projects(conn)
    conn.commit()


def _seed_codebase_contexts(conn) -> None:
    catalog = (
        ("HBA", "JarvisMD", "code-context.md", "React/Vite, FastAPI, Socket.IO, Celery, Python"),
        ("Netpalm.AI", "FleetAI", "code-context.fleetai.md", "React, TypeScript, FastAPI, Postgres"),
    )
    for org, product_name, filename, tech_stack in catalog:
        path = ROOT / "codebase" / filename
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").strip()
        conn.execute(
            """
            INSERT INTO project_contexts (org, product_name, codebase_context, tech_stack)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (org, product_name) WHERE project_id IS NULL
            DO UPDATE SET codebase_context = EXCLUDED.codebase_context,
                          tech_stack = EXCLUDED.tech_stack,
                          updated_at = now()
            """,
            (org, product_name, text, tech_stack),
        )


def _seed_minh_projects(conn) -> None:
    user = conn.execute("SELECT id FROM users WHERE email = %s", ("minh@netpalm.ai",)).fetchone()
    if user is None:
        return
    user_id = user["id"]
    lists = (
        ("JarvisMD", _JARVIS_TICKETS),
        ("FleetAI", _FLEET_TICKETS),
    )
    for name, tickets in lists:
        project = conn.execute(
            """
            INSERT INTO projects (user_id, name) VALUES (%s, %s)
            ON CONFLICT (user_id, name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (user_id, name),
        ).fetchone()
        catalog = conn.execute(
            """
            SELECT org, product_name, codebase_context, tech_stack
            FROM project_contexts
            WHERE project_id IS NULL AND product_name = %s
            """,
            (name,),
        ).fetchone()
        if catalog is not None:
            conn.execute(
                """
                INSERT INTO project_contexts (project_id, user_id, org, product_name, codebase_context, tech_stack)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id) WHERE project_id IS NOT NULL
                DO UPDATE SET user_id = EXCLUDED.user_id,
                              org = EXCLUDED.org,
                              product_name = EXCLUDED.product_name,
                              codebase_context = EXCLUDED.codebase_context,
                              tech_stack = EXCLUDED.tech_stack,
                              updated_at = now()
                """,
                (
                    project["id"],
                    user_id,
                    catalog["org"],
                    catalog["product_name"],
                    catalog["codebase_context"],
                    catalog["tech_stack"],
                ),
            )
        for public_id, title, severity, context, expected in tickets:
            conn.execute(
                """
                INSERT INTO tickets (public_id, user_id, project_id, title, severity, context, expected, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'unresolved')
                ON CONFLICT ON CONSTRAINT tickets_user_public DO NOTHING
                """,
                (public_id, user_id, project["id"], title, severity, context, expected),
            )


_JARVIS_TICKETS = (
    (
        "J1",
        "Annotated text missing while live text is present",
        "high",
        "Live text is present and the annotated text is missing.",
        "Compare word counts in jarvismd-backend annotation and nlp-services before touching the coder.",
    ),
    (
        "J2",
        "Summary drops a fact that was already annotated",
        "high",
        "A fact is in the annotated input and missing from Summary.",
        "Fix the Summary endpoints and NLP Summary. Do not patch snomed to fill the missing line.",
    ),
    (
        "J3",
        "SNOMED panel owns a clinical rule",
        "high",
        "The panel is showing a clinical decision instead of fields the service already stamped.",
        "jmd-frontend reads the stamped fields. A clinical rule change belongs in snomed.",
    ),
    (
        "J4",
        "GP template change never reaches the SPA",
        "medium",
        "The template repo changed and the SPA still shows the previous template.",
        "Vendor jmd-gp-consult-template into jmd-frontend. The template repo alone does not update the SPA.",
    ),
)

_FLEET_TICKETS = (
    (
        "T1",
        "The form takes the page",
        "high",
        "The intake form is the larger column, and Resolve sits below it. After tickets exist, the form stays full size.",
        "Once tickets exist, the board is the main surface. Intake can be opened without occupying the screen. Resolve stays visible.",
    ),
    (
        "T2",
        "The fields do not say what they are",
        "high",
        "Email is a notes box. Required and optional are only inside placeholders, and all three fields look the same.",
        "Each field is named for what the user pastes. Required and optional stay visible outside the placeholder.",
    ),
    (
        "T3",
        "The PDF control is a pill doing three jobs",
        "medium",
        "Upload or Drop PDF is the mode switch, the file button, and the drop target. The file input is off the keyboard.",
        "Paste and PDF are separate choices. The drop area is visible before a file is chosen. A keyboard user can open the picker.",
    ),
    (
        "T4",
        "A ticket row hides the ticket",
        "high",
        "The row shows an id, a title, a status word, and two lines of context. Severity, expected behaviour, and services are not shown.",
        "The title is the primary text. Severity, expected behaviour, and services are visible on the row.",
    ),
    (
        "T5",
        "Status is one amber word",
        "medium",
        "Open, Queued, Solving, and Verifying share one accent color. Hover lifts every row, including the one being worked.",
        "Each status is distinguishable without reading the word alone. Hover does not fight the active row.",
    ),
    (
        "T6",
        "Row actions and the report look unfinished",
        "medium",
        "Show report is a bare button. The report opens inside the card and pushes the list down.",
        "Both actions use the existing button styles. The report opens in a panel that does not shove the list.",
    ),
    (
        "T7",
        "Failure looks like the brand, and the run disappears",
        "high",
        "Errors use the same amber as status text, and several are still raw strings. Leave the page and the run is gone.",
        "A failure is a sentence in an error color. Coming back to the page still shows the run.",
    ),
)
