"""Current user from the session cookie."""

from __future__ import annotations

from fastapi import HTTPException, Request

import db
from auth.service import User
from auth.sessions import COOKIE_NAME, CSRF_HEADER, CSRF_VALUE, session_idle_days, token_hash, touch_session


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
                """
                SELECT u.id, u.username, u.first_name, u.last_name, s.id AS session_id
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = %s
                  AND s.revoked_at IS NULL
                  AND s.expires_at > now()
                  AND s.last_seen_at > now() - (%s * interval '1 day')
                  AND u.status = 'active'
                  AND u.email_verified
                """,
                (token_hash(token), session_idle_days()),
            ).fetchone()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    if row is None:
        raise HTTPException(401, "unauthorized")
    touch_session(row["session_id"])
    return User(
        id=row["id"],
        username=str(row["username"]),
        first_name=str(row["first_name"] or ""),
        last_name=str(row["last_name"] or ""),
    )
