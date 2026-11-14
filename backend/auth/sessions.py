"""Opaque session tokens stored as sha256 hashes."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import secrets
import threading
from datetime import timedelta

COOKIE_NAME = "fleetai_session"
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "fleetai"


def session_max_days() -> int:
    return int((os.getenv("SESSION_MAX_DAYS") or "30").strip() or "30")


def session_idle_days() -> int:
    return int((os.getenv("SESSION_IDLE_DAYS") or "7").strip() or "7")


def cookie_secure() -> bool:
    return (os.getenv("COOKIE_SECURE") or "").strip().lower() in {"1", "true", "yes"}


def cookie_max_age() -> int:
    return session_max_days() * 86400


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def client_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value


def start_cleanup() -> threading.Event:
    stop = threading.Event()

    def loop() -> None:
        while True:
            try:
                cleanup()
            except Exception:
                pass
            if stop.wait(3600):
                return

    threading.Thread(target=loop, name="session-cleanup", daemon=True).start()
    return stop


def cleanup() -> None:
    import db

    with db.get_pool().connection() as conn:
        conn.execute(
            """
            DELETE FROM sessions
            WHERE expires_at < now() - interval '7 days'
               OR (revoked_at IS NOT NULL AND revoked_at < now() - interval '7 days')
            """
        )
        conn.commit()


def create_session(user_id, token: str, ip: str | None, user_agent: str | None) -> None:
    import db

    with db.get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO sessions (user_id, token_hash, expires_at, ip, user_agent)
            VALUES (%s, %s, now() + %s, %s, %s)
            """,
            (user_id, token_hash(token), timedelta(days=session_max_days()), client_ip(ip), None),
        )
        conn.commit()


def revoke_token(token: str) -> None:
    import db

    with db.get_pool().connection() as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at = now() WHERE token_hash = %s AND revoked_at IS NULL",
            (token_hash(token),),
        )
        conn.commit()


def revoke_user_sessions(user_id) -> None:
    import db

    with db.get_pool().connection() as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
            (user_id,),
        )
        conn.commit()


def touch_session(session_id) -> None:
    import db

    with db.get_pool().connection() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET last_seen_at = now()
            WHERE id = %s AND last_seen_at <= now() - interval '5 minutes'
            """,
            (session_id,),
        )
        conn.commit()
