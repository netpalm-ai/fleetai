"""Persist intake uploads and parsed tickets in Postgres."""

from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

import db
from config import TICKETS_DIR

INTAKES_DIR = TICKETS_DIR / "intakes"
TICKET_LIST = "ticket_list"


def deactivate(user_id: UUID, intake_type: str) -> None:
    if db.pool is None:
        return
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
    suffix: str,
) -> UUID | None:
    if db.pool is None:
        return None
    intake_id = uuid4()
    INTAKES_DIR.mkdir(parents=True, exist_ok=True)
    path = INTAKES_DIR / "{0}{1}".format(intake_id, suffix)
    path.write_bytes(data)
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
              id, user_id, session_id, type, format, status, sha256, byte_size, storage_path
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
                str(path.relative_to(TICKETS_DIR)),
            ),
        )
        conn.commit()
    return intake_id


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
    if db.pool is None:
        return
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


def list_open_tickets(user_id: UUID) -> list[dict] | None:
    if db.pool is None:
        return None
    with db.get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT t.public_id AS id, t.title, t.severity, t.services, t.context, t.expected, t.kind, t.status
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
