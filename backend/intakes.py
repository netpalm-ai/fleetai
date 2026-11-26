"""Persist intakes, tickets, run logs, and ticket retention in Postgres."""

from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

import db

TICKET_LIST = "ticket_list"
SOLVED = ("fixed", "completed")
_TICKET_COLS = "t.public_id AS id, t.title, t.severity, t.services, t.context, t.expected, t.kind, t.status"
_KEEP_FOR = """
CASE COALESCE(pt.status, 'free')
  WHEN 'trial' THEN interval '7 days'
  WHEN 'paid' THEN make_interval(days => us.ticket_retention_days)
  ELSE interval '0'
END
"""
_USER_TIER_JOINS = """
LEFT JOIN user_subscriptions us ON us.user_id = u.id AND us.product_id = 'fleetai'
LEFT JOIN product_tiers pt ON pt.id = us.tier_id
"""


def deactivate(user_id: UUID, intake_type: str) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            """
            UPDATE intakes
            SET status = 'deactivated', deactivated_at = now()
            WHERE user_id = %s AND type = %s AND status = 'active'
            """,
            (user_id, intake_type),
        )
        conn.commit()


def put(
    user_id: UUID,
    session_id: UUID | None,
    intake_type: str,
    fmt: str,
    data: bytes,
) -> UUID:
    intake_id = uuid4()
    with db.get_pool().connection() as conn:
        conn.execute(
            """
            UPDATE intakes
            SET status = 'deactivated', deactivated_at = now()
            WHERE user_id = %s AND type = %s AND status = 'active'
            """,
            (user_id, intake_type),
        )
        conn.execute(
            """
            INSERT INTO intakes (
              id, user_id, session_id, type, format, status, sha256, byte_size, content
            )
            VALUES (%s, %s, %s, %s, %s, 'active', %s, %s, %s)
            """,
            (
                intake_id,
                user_id,
                session_id,
                intake_type,
                fmt,
                hashlib.sha256(data).digest(),
                len(data),
                data,
            ),
        )
        conn.commit()
    return intake_id


def active_content(user_id: UUID, intake_type: str) -> tuple[str, bytes] | None:
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT format, content FROM intakes
            WHERE user_id = %s AND type = %s AND status = 'active'
            """,
            (user_id, intake_type),
        ).fetchone()
    if row is None:
        return None
    return row["format"], bytes(row["content"])


def _active_ticket_list_id(conn, user_id: UUID) -> UUID | None:
    row = conn.execute(
        """
        SELECT id FROM intakes
        WHERE user_id = %s AND type = %s AND status = 'active'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id, TICKET_LIST),
    ).fetchone()
    if row is None:
        return None
    return row["id"]


def sync_tickets(user_id: UUID, session_id: UUID | None, tickets: list[dict]) -> None:
    incoming = [str(item["id"]) for item in tickets]
    with db.get_pool().connection() as conn:
        intake_id = _active_ticket_list_id(conn, user_id)
        for item in tickets:
            conn.execute(
                """
                INSERT INTO tickets (
                  public_id, user_id, session_id, intake_id,
                  title, severity, services, context, expected, kind, status, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (user_id, public_id) DO UPDATE SET
                  session_id = EXCLUDED.session_id,
                  intake_id = EXCLUDED.intake_id,
                  title = EXCLUDED.title,
                  severity = EXCLUDED.severity,
                  services = EXCLUDED.services,
                  context = EXCLUDED.context,
                  expected = EXCLUDED.expected,
                  kind = EXCLUDED.kind,
                  status = EXCLUDED.status,
                  handled_at = CASE WHEN EXCLUDED.status IN ('fixed', 'completed')
                    THEN COALESCE(tickets.handled_at, now()) END,
                  updated_at = now()
                """,
                (
                    item["id"],
                    user_id,
                    session_id,
                    intake_id,
                    str(item.get("title") or ""),
                    str(item.get("severity") or ""),
                    list(item.get("services") or []),
                    str(item.get("context") or ""),
                    str(item.get("expected") or ""),
                    str(item.get("kind") or "new"),
                    item["status"],
                ),
            )
        if incoming:
            conn.execute(
                """
                DELETE FROM tickets
                WHERE user_id = %s AND status = 'unresolved' AND NOT (public_id = ANY(%s))
                """,
                (user_id, incoming),
            )
        else:
            conn.execute(
                "DELETE FROM tickets WHERE user_id = %s AND status = 'unresolved'",
                (user_id,),
            )
        conn.commit()


def list_open_tickets(user_id: UUID) -> list[dict]:
    with db.get_pool().connection() as conn:
        rows = conn.execute(
            f"""
            SELECT {_TICKET_COLS}
            FROM tickets t
            LEFT JOIN intakes i ON i.id = t.intake_id
            WHERE t.user_id = %s
              AND t.status IN ('unresolved', 'verifying')
              AND (t.intake_id IS NULL OR i.status = 'active')
            ORDER BY t.public_id
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_visible_tickets(user_id: UUID, project_id: UUID | None = None) -> list[dict]:
    where = "t.user_id = %s"
    params: list[object] = [user_id]
    if project_id is not None:
        where += " AND t.project_id = %s"
        params.append(project_id)
    with db.get_pool().connection() as conn:
        rows = conn.execute(
            f"""
            SELECT {_TICKET_COLS}
            FROM tickets t
            LEFT JOIN intakes i ON i.id = t.intake_id
            LEFT JOIN users u ON u.id = t.user_id
            {_USER_TIER_JOINS}
            WHERE {where}
              AND (
                t.status IN ('unresolved', 'verifying')
                OR (
                  t.status IN ('fixed', 'completed')
                  AND (
                    {_KEEP_FOR} IS NULL
                    OR t.handled_at > now() - ({_KEEP_FOR})
                  )
                )
              )
              AND (
                t.status IN ('fixed', 'completed')
                OR t.intake_id IS NULL
                OR i.status = 'active'
              )
            ORDER BY t.public_id
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def open_tickets(user_id: UUID) -> list[dict]:
    with db.get_pool().connection() as conn:
        rows = conn.execute(
            f"""
            SELECT {_TICKET_COLS}
            FROM tickets t
            WHERE t.user_id = %s AND t.status IN ('unresolved', 'verifying')
            ORDER BY t.public_id
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def solved_tickets(user_id: UUID) -> dict[str, dict]:
    with db.get_pool().connection() as conn:
        rows = conn.execute(
            f"""
            SELECT {_TICKET_COLS}
            FROM tickets t
            WHERE t.user_id = %s AND t.status IN ('fixed', 'completed')
            """,
            (user_id,),
        ).fetchall()
    return {row["id"]: dict(row) for row in rows}


def find_ticket(user_id: UUID, public_id: str) -> dict | None:
    with db.get_pool().connection() as conn:
        row = conn.execute(
            f"""
            SELECT {_TICKET_COLS}
            FROM tickets t
            WHERE t.user_id = %s AND t.public_id = %s
            """,
            (user_id, public_id),
        ).fetchone()
    return dict(row) if row else None


def set_ticket_status(user_id: UUID, public_id: str, status: str) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            """
            UPDATE tickets
            SET status = %s,
                handled_at = CASE WHEN %s IN ('fixed', 'completed') THEN now() END,
                updated_at = now()
            WHERE user_id = %s AND public_id = %s
            """,
            (status, status, user_id, public_id),
        )
        conn.commit()
    if status in SOLVED:
        purge_handled(user_id)


def add_run(
    user_id: UUID,
    public_id: str,
    run_id: str,
    kind: str,
    verdict: str | None,
    prompt: str,
    result: str | None,
) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO ticket_runs (ticket_id, run_id, kind, verdict, prompt, result)
            SELECT t.id, %s, %s, %s, %s, %s
            FROM tickets t
            WHERE t.user_id = %s AND t.public_id = %s
            """,
            (run_id, kind, verdict, prompt, result or "", user_id, public_id),
        )
        conn.commit()


def get_run(user_id: UUID, public_id: str, run_id: str) -> dict | None:
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT r.run_id, r.kind, r.verdict, r.prompt, r.result
            FROM ticket_runs r
            JOIN tickets t ON t.id = r.ticket_id
            WHERE t.user_id = %s AND t.public_id = %s AND r.run_id = %s
            ORDER BY r.created_at DESC
            LIMIT 1
            """,
            (user_id, public_id, run_id),
        ).fetchone()
    return dict(row) if row else None


def latest_run(user_id: UUID, public_id: str, kind: str | None = None) -> dict | None:
    sql = """
            SELECT r.run_id, r.kind, r.verdict, r.prompt, r.result
            FROM ticket_runs r
            JOIN tickets t ON t.id = r.ticket_id
            WHERE t.user_id = %s AND t.public_id = %s
            """
    args: list[object] = [user_id, public_id]
    if kind:
        sql += " AND r.kind = %s"
        args.append(kind)
    sql += " ORDER BY r.created_at DESC LIMIT 1"
    with db.get_pool().connection() as conn:
        row = conn.execute(sql, args).fetchone()
    return dict(row) if row else None


def latest_run_id(user_id: UUID, public_id: str) -> str | None:
    run = latest_run(user_id, public_id)
    return run["run_id"] if run else None


def keep_days(user_id: UUID) -> int | None:
    with db.get_pool().connection() as conn:
        row = conn.execute(
            f"""
            SELECT EXTRACT(day FROM {_KEEP_FOR})::int AS days
            FROM users u
            {_USER_TIER_JOINS}
            WHERE u.id = %s
            """,
            (user_id,),
        ).fetchone()
    return row["days"] if row else None


def set_keep_days(user_id: UUID, days: int | None) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            """
            UPDATE user_subscriptions
            SET ticket_retention_days = %s
            WHERE user_id = %s AND product_id = 'fleetai'
            """,
            (days, user_id),
        )
        conn.commit()
    purge_handled(user_id)


def purge_handled(user_id: UUID | None = None) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            f"""
            WITH keep AS (
              SELECT u.id AS user_id, {_KEEP_FOR} AS keep_for
              FROM users u
              {_USER_TIER_JOINS}
            )
            DELETE FROM tickets t
            USING keep k
            WHERE k.user_id = t.user_id
              AND t.status IN ('fixed', 'completed')
              AND k.keep_for IS NOT NULL
              AND t.handled_at <= now() - k.keep_for
              AND (%s::uuid IS NULL OR t.user_id = %s::uuid)
            """,
            (user_id, user_id),
        )
        conn.execute(
            """
            DELETE FROM intakes i
            WHERE i.status = 'deactivated'
              AND (%s::uuid IS NULL OR i.user_id = %s::uuid)
              AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.intake_id = i.id)
            """,
            (user_id, user_id),
        )
        conn.commit()
