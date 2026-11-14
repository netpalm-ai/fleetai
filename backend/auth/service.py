"""Register, login, and session create/revoke."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from psycopg.errors import UniqueViolation

import db
from auth import passwords, sessions

MAX_EMAIL = 254
MAX_NAME = 80
FLEETAI_PRODUCT = "fleetai"
FLEETAI_TIER_FREE = "free"
FLEETAI_FEATURE_TICKETS = "tickets"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USER_FLEETAI_COLS = """
u.id, u.username, u.first_name, u.last_name, u.email,
u.status, u.last_signed_in_ts,
pt.status AS subscription_status,
us.product_id AS registered_product,
COALESCE((
  SELECT array_agg(pf.key ORDER BY pf.key)
  FROM tier_entitlements te
  JOIN product_features pf ON pf.id = te.feature_id
  WHERE te.tier_id = us.tier_id
), '{}'::text[]) AS features
"""
USER_FLEETAI_JOINS = """
FROM users u
LEFT JOIN user_subscriptions us
  ON us.user_id = u.id AND us.product_id = 'fleetai'
LEFT JOIN product_tiers pt ON pt.id = us.tier_id
"""


@dataclass(frozen=True)
class User:
    id: UUID
    username: str
    first_name: str
    last_name: str
    email: str = ""
    subscription_status: str = "free"
    registered_product: str = ""
    features: tuple[str, ...] = ()
    status: str = "active"
    last_signed_in_ts: datetime | None = None


class AuthError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _normalize_email(value: str) -> str:
    return value.strip()


def valid_email(value: str) -> bool:
    return bool(value) and len(value) <= MAX_EMAIL and _EMAIL.fullmatch(value) is not None


def _normalize_name(value: str) -> str:
    return " ".join(value.split())


def valid_name(value: str) -> bool:
    return bool(value) and len(value) <= MAX_NAME


def _normalize_username(value: str) -> str:
    return value.strip()


def valid_username(value: str) -> bool:
    return bool(value) and len(value) <= MAX_NAME and not any(ch.isspace() for ch in value)


def _row_features(row) -> tuple[str, ...]:
    try:
        value = row["features"]
    except (KeyError, IndexError):
        return ()
    if not value:
        return ()
    return tuple(str(item) for item in value)


def user_from_row(row) -> User:
    return User(
        id=row["id"],
        username=str(row["username"]),
        first_name=str(row["first_name"] or ""),
        last_name=str(row["last_name"] or ""),
        email=str(row.get("email") or ""),
        subscription_status=str(row.get("subscription_status") or "free"),
        registered_product=str(row.get("registered_product") or ""),
        features=_row_features(row),
        status=str(row.get("status") or "active"),
        last_signed_in_ts=row.get("last_signed_in_ts"),
    )


def issue_verify_token(user_id: UUID) -> str:
    token = sessions.new_token()
    with db.get_pool().connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET email_verify_token_hash = %s, email_verify_expires_at = now() + %s
            WHERE id = %s
            """,
            (sessions.token_hash(token), timedelta(days=1), user_id),
        )
        conn.commit()
    return token


def verify_email(token: str) -> None:
    raw = (token or "").strip()
    if not raw:
        raise AuthError(422, "invalid")
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT id FROM users
            WHERE email_verify_token_hash = %s
              AND email_verify_expires_at > now()
              AND email_verified = false
            """,
            (sessions.token_hash(raw),),
        ).fetchone()
        if row is None:
            raise AuthError(400, "invalid")
        conn.execute(
            """
            UPDATE users
            SET email_verified = true,
                email_verified_ts = now(),
                email_verify_token_hash = NULL,
                email_verify_expires_at = NULL
            WHERE id = %s
            """,
            (row["id"],),
        )
        conn.commit()


def register(
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    password: str,
    tos_accepted: bool,
    ip: str | None,
    user_agent: str | None,
) -> User:
    handle = _normalize_username(username)
    name = _normalize_email(email)
    given = _normalize_name(first_name)
    family = _normalize_name(last_name)
    if not valid_username(handle) or not valid_email(name) or not valid_name(given) or not valid_name(family):
        raise AuthError(422, "invalid")
    if not tos_accepted:
        raise AuthError(422, "invalid")
    if not passwords.valid_password(password):
        raise AuthError(422, "invalid")
    try:
        with db.get_pool().connection() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    INSERT INTO users (
                        username, email, first_name, last_name, password_hash
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, username, first_name, last_name, email
                    """,
                    (handle, name, given, family, passwords.hash_password(password)),
                ).fetchone()
                if row is None:
                    raise AuthError(500, "register failed")
                conn.execute(
                    """
                    INSERT INTO user_subscriptions (user_id, product_id, tier_id)
                    SELECT %s, %s, id FROM product_tiers
                    WHERE product_id = %s AND status = %s
                    """,
                    (row["id"], FLEETAI_PRODUCT, FLEETAI_PRODUCT, FLEETAI_TIER_FREE),
                )
                row = conn.execute(
                    f"SELECT {USER_FLEETAI_COLS} {USER_FLEETAI_JOINS} WHERE u.id = %s",
                    (row["id"],),
                ).fetchone()
    except UniqueViolation as exc:
        raise AuthError(409, "account taken") from exc
    if row is None:
        raise AuthError(500, "register failed")
    user = user_from_row(row)
    issue_verify_token(user.id)
    return user


def login(email: str, password: str, ip: str | None, user_agent: str | None) -> tuple[User, str]:
    name = _normalize_email(email)
    if not valid_email(name) or not password or len(password) > passwords.MAX_PASSWORD:
        raise AuthError(422, "invalid")
    with db.get_pool().connection() as conn:
        row = conn.execute(
            f"""
            SELECT {USER_FLEETAI_COLS},
                   u.password_hash, u.email_verified
            {USER_FLEETAI_JOINS}
            WHERE u.email = %s
            """,
            (name,),
        ).fetchone()
        if row is None:
            passwords.verify_dummy(password)
            raise AuthError(401, "invalid credentials")
        if not passwords.verify_password(row["password_hash"], password):
            raise AuthError(401, "invalid credentials")
        if row["status"] != "active":
            raise AuthError(401, "invalid credentials")
        if not row["email_verified"]:
            raise AuthError(403, "email not verified")
        signed = conn.execute(
            """
            UPDATE users SET last_signed_in_ts = now()
            WHERE id = %s
            RETURNING last_signed_in_ts
            """,
            (row["id"],),
        ).fetchone()
        conn.commit()
    user = user_from_row({**row, "last_signed_in_ts": signed["last_signed_in_ts"] if signed else None})
    token = sessions.new_token()
    sessions.create_session(user.id, token, ip, user_agent)
    return user, token


def logout(token: str | None) -> None:
    if token:
        sessions.revoke_token(token)


def change_password(user_id: UUID, current: str, new: str) -> None:
    if not current or not passwords.valid_password(new):
        raise AuthError(422, "invalid")
    with db.get_pool().connection() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
        if row is None or not passwords.verify_password(row["password_hash"], current):
            raise AuthError(401, "invalid credentials")
        conn.execute(
            """
            UPDATE users
            SET password_hash = %s, updated_at = now()
            WHERE id = %s
            """,
            (passwords.hash_password(new), user_id),
        )
        conn.commit()
    sessions.revoke_user_sessions(user_id)
