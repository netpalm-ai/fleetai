"""Current user from the session cookie."""

from __future__ import annotations

from fastapi import HTTPException, Request

import db
from auth.service import USER_COLS, USER_JOINS, Product, User, user_from_row
from auth.sessions import COOKIE_NAME, CSRF_HEADER, CSRF_VALUE, session_idle_minutes, token_hash, touch_session


def require_csrf(request: Request) -> None:
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(403, "missing X-Requested-With")


def get_product(request: Request) -> Product:
    return request.app.state.auth_product


def get_current_user(request: Request) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "unauthorized")
    try:
        with db.get_pool().connection() as conn:
            row = conn.execute(
                f"""
                SELECT {USER_COLS}, s.id AS session_id
                {USER_JOINS}
                JOIN sessions s ON s.user_id = u.id
                WHERE s.token_hash = %s
                  AND s.revoked_at IS NULL
                  AND s.expires_at > now()
                  AND s.last_seen_at > now() - (%s * interval '1 minute')
                  AND u.status = 'active'
                  AND u.email_verified
                """,
                (get_product(request).id, token_hash(token), session_idle_minutes()),
            ).fetchone()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    if row is None:
        raise HTTPException(401, "unauthorized")
    touch_session(row["session_id"])
    return user_from_row(row)
