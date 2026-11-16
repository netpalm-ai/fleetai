"""Register, login, and session create/revoke."""

from __future__ import annotations

import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import pyotp
import segno
from cryptography.fernet import Fernet, InvalidToken
from psycopg.errors import UniqueViolation
from pyotp.utils import strings_equal

import db
import emails
from auth import passwords, sessions

MAX_EMAIL = 254
MAX_NAME = 80
VERIFY_LINK_DAYS = 7
RECOVERY_CODE_COUNT = 10
LOGIN_MAX_FAILURES = 10
LOGIN_LOCK_MINUTES = 15
SECOND_FACTOR_MAX_FAILURES = 5
SECOND_FACTOR_LOCK_MINUTES = 15
PASSWORD_RESET_MINUTES = 60
PASSWORD_RESET_RESEND_MINUTES = 5
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USER_COLS = """
u.id, u.username, u.first_name, u.last_name, u.email,
u.status, u.last_signed_in_ts, u.totp_enabled,
pt.status AS subscription_status,
us.product_id AS registered_product,
COALESCE((
  SELECT array_agg(pf.key ORDER BY pf.key)
  FROM tier_entitlements te
  JOIN product_features pf ON pf.id = te.feature_id
  WHERE te.tier_id = us.tier_id
), '{}'::text[]) AS features
"""
USER_JOINS = """
FROM users u
LEFT JOIN user_subscriptions us
  ON us.user_id = u.id AND us.product_id = %s
LEFT JOIN product_tiers pt ON pt.id = us.tier_id
"""


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    signup_tier: str


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
    totp_enabled: bool = False
    session_id: UUID | None = None


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
        totp_enabled=bool(row.get("totp_enabled")),
        session_id=row.get("session_id"),
    )


def _load_user(conn, product: Product, user_id: UUID) -> User:
    row = conn.execute(f"SELECT {USER_COLS} {USER_JOINS} WHERE u.id = %s", (product.id, user_id)).fetchone()
    return user_from_row(row)


def _subscribe(conn, product: Product, user_id: UUID) -> None:
    conn.execute(
        """
        INSERT INTO user_subscriptions (user_id, product_id, tier_id)
        SELECT %s, %s, id FROM product_tiers
        WHERE product_id = %s AND status = %s
        ON CONFLICT (user_id, product_id) DO NOTHING
        """,
        (user_id, product.id, product.id, product.signup_tier),
    )


def _record_event(conn, user_id: UUID, event: str, ip: str | None) -> None:
    conn.execute(
        "INSERT INTO auth_events (user_id, event, ip) VALUES (%s, %s, %s)",
        (user_id, event, sessions.client_ip(ip)),
    )


def _count_failure(conn, user_id: UUID, counter: str, locked_until: str, max_failures: int, lock_minutes: int) -> None:
    conn.execute(
        f"""
        UPDATE users
        SET {locked_until} = CASE WHEN {counter} + 1 >= %s THEN now() + %s END,
            {counter} = CASE WHEN {counter} + 1 >= %s THEN 0 ELSE {counter} + 1 END
        WHERE id = %s
        """,
        (max_failures, timedelta(minutes=lock_minutes), max_failures, user_id),
    )


def _cipher() -> Fernet:
    try:
        return Fernet((os.getenv("AUTH_SECRET_KEY") or "").strip())
    except ValueError as exc:
        raise RuntimeError("AUTH_SECRET_KEY is missing or not a valid key") from exc


def _totp(stored_secret: str) -> pyotp.TOTP:
    try:
        return pyotp.TOTP(_cipher().decrypt(stored_secret.encode()).decode())
    except InvalidToken as exc:
        raise RuntimeError("authenticator secret cannot be read with AUTH_SECRET_KEY") from exc


def _matching_totp_step(totp: pyotp.TOTP, code: str) -> int | None:
    digits = "".join(code.split())
    current = int(time.time()) // totp.interval
    for step in (current - 1, current, current + 1):
        if strings_equal(digits, totp.generate_otp(step)):
            return step
    return None


def _recovery_hash(code: str) -> bytes:
    return sessions.token_hash("".join(ch for ch in code.lower() if ch in "0123456789abcdef"))


def _require_second_factor(conn, user_id: UUID, code: str, ip: str | None) -> None:
    row = conn.execute(
        """
        SELECT totp_secret, totp_last_step, COALESCE(totp_locked_until > now(), false) AS locked
        FROM users
        WHERE id = %s
        FOR UPDATE
        """,
        (user_id,),
    ).fetchone()
    if row["locked"]:
        raise AuthError(429, "too many attempts")
    step = _matching_totp_step(_totp(row["totp_secret"]), code)
    if step is not None and row["totp_last_step"] is not None and step <= row["totp_last_step"]:
        step = None
    if step is None:
        spent = conn.execute(
            "DELETE FROM totp_recovery_codes WHERE user_id = %s AND code_hash = %s RETURNING id",
            (user_id, _recovery_hash(code)),
        ).fetchone()
        if spent is None:
            _count_failure(
                conn,
                user_id,
                "totp_failed_attempts",
                "totp_locked_until",
                SECOND_FACTOR_MAX_FAILURES,
                SECOND_FACTOR_LOCK_MINUTES,
            )
            _record_event(conn, user_id, "second_factor_failed", ip)
            conn.commit()
            raise AuthError(401, "invalid credentials")
    conn.execute(
        """
        UPDATE users
        SET totp_last_step = COALESCE(%s, totp_last_step), totp_failed_attempts = 0, totp_locked_until = NULL
        WHERE id = %s
        """,
        (step, user_id),
    )


def start_totp_setup(product: Product, user: User) -> dict:
    secret = pyotp.random_base32()
    stored = _cipher().encrypt(secret.encode()).decode()
    with db.get_pool().connection() as conn:
        row = conn.execute(
            "UPDATE users SET totp_secret = %s WHERE id = %s AND NOT totp_enabled RETURNING id",
            (stored, user.id),
        ).fetchone()
        conn.commit()
    if row is None:
        raise AuthError(409, "already enabled")
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=product.name)
    return {"secret": secret, "qr": segno.make(uri).png_data_uri(scale=6)}


def enable_totp(user_id: UUID, password: str, code: str, ip: str | None) -> list[str]:
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT password_hash, totp_secret FROM users
            WHERE id = %s AND NOT totp_enabled AND totp_secret IS NOT NULL
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            raise AuthError(400, "invalid")
        if not passwords.verify_password(row["password_hash"], password):
            raise AuthError(401, "invalid credentials")
        step = _matching_totp_step(_totp(row["totp_secret"]), code)
        if step is None:
            raise AuthError(400, "invalid")
        recovery_codes = [secrets.token_hex(6) for _ in range(RECOVERY_CODE_COUNT)]
        conn.execute("UPDATE users SET totp_enabled = true, totp_last_step = %s WHERE id = %s", (step, user_id))
        conn.execute("DELETE FROM totp_recovery_codes WHERE user_id = %s", (user_id,))
        for recovery_code in recovery_codes:
            conn.execute(
                "INSERT INTO totp_recovery_codes (user_id, code_hash) VALUES (%s, %s)",
                (user_id, _recovery_hash(recovery_code)),
            )
        _record_event(conn, user_id, "totp_enabled", ip)
        conn.commit()
    return recovery_codes


def disable_totp(user_id: UUID, password: str, code: str, ip: str | None) -> None:
    with db.get_pool().connection() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = %s AND totp_enabled",
            (user_id,),
        ).fetchone()
        if row is None or not passwords.verify_password(row["password_hash"], password):
            raise AuthError(401, "invalid credentials")
        _require_second_factor(conn, user_id, code, ip)
        conn.execute(
            "UPDATE users SET totp_enabled = false, totp_secret = NULL, totp_last_step = NULL WHERE id = %s",
            (user_id,),
        )
        conn.execute("DELETE FROM totp_recovery_codes WHERE user_id = %s", (user_id,))
        _record_event(conn, user_id, "totp_disabled", ip)
        conn.commit()


def request_password_reset(product: Product, email: str) -> None:
    name = _normalize_email(email)
    if not valid_email(name):
        return
    token = sessions.new_token()
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """
            UPDATE users
            SET password_reset_token_hash = %s, password_reset_expires_at = now() + %s
            WHERE email = %s AND email_verified AND status = 'active'
              AND (password_reset_expires_at IS NULL OR password_reset_expires_at < now() + %s)
            RETURNING email
            """,
            (
                sessions.token_hash(token),
                timedelta(minutes=PASSWORD_RESET_MINUTES),
                name,
                timedelta(minutes=PASSWORD_RESET_MINUTES - PASSWORD_RESET_RESEND_MINUTES),
            ),
        ).fetchone()
        conn.commit()
    if row is not None:
        emails.send_password_reset_email(product.name, str(row["email"]), token, PASSWORD_RESET_MINUTES)


def reset_password(token: str, new: str, ip: str | None) -> None:
    raw = (token or "").strip()
    if not raw or not passwords.valid_password(new):
        raise AuthError(422, "invalid")
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """
            UPDATE users
            SET password_hash = %s,
                password_reset_token_hash = NULL,
                password_reset_expires_at = NULL,
                failed_logins = 0,
                login_locked_until = NULL,
                updated_at = now()
            WHERE password_reset_token_hash = %s AND password_reset_expires_at > now()
            RETURNING id
            """,
            (passwords.hash_password(new), sessions.token_hash(raw)),
        ).fetchone()
        if row is None:
            raise AuthError(400, "invalid")
        _record_event(conn, row["id"], "password_reset", ip)
        conn.commit()
    sessions.revoke_user_sessions(row["id"])


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
    product: Product,
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    password: str,
    tos_accepted: bool,
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
    verify_token = sessions.new_token()
    try:
        with db.get_pool().connection() as conn:
            with conn.transaction():
                conn.execute("DELETE FROM users WHERE email = %s AND NOT email_verified", (name,))
                row = conn.execute(
                    """
                    INSERT INTO users (
                        username, email, first_name, last_name, password_hash,
                        email_verify_token_hash, email_verify_expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, now() + %s)
                    RETURNING id
                    """,
                    (
                        handle,
                        name,
                        given,
                        family,
                        passwords.hash_password(password),
                        sessions.token_hash(verify_token),
                        timedelta(days=VERIFY_LINK_DAYS),
                    ),
                ).fetchone()
                _subscribe(conn, product, row["id"])
                user = _load_user(conn, product, row["id"])
    except UniqueViolation as exc:
        raise AuthError(409, "account taken") from exc
    emails.send_verification_email(product.name, user.email, verify_token, VERIFY_LINK_DAYS)
    return user


def login(
    product: Product, email: str, password: str, code: str, ip: str | None, user_agent: str | None
) -> tuple[User, str]:
    name = _normalize_email(email)
    if not valid_email(name) or not password or len(password) > passwords.MAX_PASSWORD:
        raise AuthError(422, "invalid")
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT id, password_hash, status, email_verified, totp_enabled,
                   COALESCE(login_locked_until > now(), false) AS locked
            FROM users
            WHERE email = %s
            """,
            (name,),
        ).fetchone()
        if row is None:
            passwords.verify_dummy(password)
            raise AuthError(401, "invalid credentials")
        if row["locked"]:
            raise AuthError(429, "too many attempts")
        if not passwords.verify_password(row["password_hash"], password):
            _count_failure(
                conn, row["id"], "failed_logins", "login_locked_until", LOGIN_MAX_FAILURES, LOGIN_LOCK_MINUTES
            )
            _record_event(conn, row["id"], "login_failed", ip)
            conn.commit()
            raise AuthError(401, "invalid credentials")
        if row["status"] != "active":
            raise AuthError(401, "invalid credentials")
        if not row["email_verified"]:
            raise AuthError(403, "email not verified")
        if row["totp_enabled"]:
            if not code:
                raise AuthError(401, "code required")
            _require_second_factor(conn, row["id"], code, ip)
        conn.execute(
            "UPDATE users SET last_signed_in_ts = now(), failed_logins = 0, login_locked_until = NULL WHERE id = %s",
            (row["id"],),
        )
        _subscribe(conn, product, row["id"])
        _record_event(conn, row["id"], "login", ip)
        user = _load_user(conn, product, row["id"])
        conn.commit()
    token = sessions.new_token()
    sessions.create_session(user.id, token, ip, user_agent)
    return user, token


def logout(token: str | None) -> None:
    if token:
        sessions.revoke_token(token)


def change_password(user_id: UUID, current: str, new: str, ip: str | None) -> None:
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
            SET password_hash = %s,
                password_reset_token_hash = NULL,
                password_reset_expires_at = NULL,
                updated_at = now()
            WHERE id = %s
            """,
            (passwords.hash_password(new), user_id),
        )
        _record_event(conn, user_id, "password_changed", ip)
        conn.commit()
    sessions.revoke_user_sessions(user_id)
