"""Current user from the session cookie."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

import db
from auth.service import (
    FLEETAI_FEATURE_TICKETS,
    USER_FLEETAI_COLS,
    USER_FLEETAI_JOINS,
    User,
    user_from_row,
)
from auth.sessions import COOKIE_NAME, CSRF_HEADER, CSRF_VALUE, session_idle_minutes, token_hash, touch_session


def require_csrf(request: Request) -> None:
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(403, "missing X-Requested-With")


def get_current_user(request: Request) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "unauthorized")
    try:
        with db.get_pool().connection() as conn:
            row = conn.execute(
                f"""
                SELECT {USER_FLEETAI_COLS}, s.id AS session_id
                {USER_FLEETAI_JOINS}
                JOIN sessions s ON s.user_id = u.id
                WHERE s.token_hash = %s
                  AND s.revoked_at IS NULL
                  AND s.expires_at > now()
                  AND s.last_seen_at > now() - (%s * interval '1 minute')
                  AND u.status = 'active'
                  AND u.email_verified
                """,
                (token_hash(token), session_idle_minutes()),
            ).fetchone()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    if row is None:
        raise HTTPException(401, "unauthorized")
    touch_session(row["session_id"])
    return user_from_row(row)


def require_tickets(user: User = Depends(get_current_user)) -> User:
    if FLEETAI_FEATURE_TICKETS not in user.features:
        raise HTTPException(403, "forbidden")
    return user
