"""Register, login, and session create/revoke."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from psycopg.errors import IntegrityError

import db
from auth import passwords, sessions

MAX_EMAIL = 254
MAX_NAME = 80
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class User:
    id: UUID
    username: str
    first_name: str
    last_name: str


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


def user_from_row(row) -> User:
    return User(
        id=row["id"],
        username=str(row["username"]),
        first_name=str(row["first_name"] or ""),
        last_name=str(row["last_name"] or ""),
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
    first_name: str,
    last_name: str,
    password: str,
    tos_accepted: bool,
    ip: str | None,
    user_agent: str | None,
) -> User:
    name = _normalize_email(username)
    given = _normalize_name(first_name)
    family = _normalize_name(last_name)
    if not valid_email(name) or not valid_name(given) or not valid_name(family):
        raise AuthError(422, "invalid")
    if not tos_accepted:
        raise AuthError(422, "invalid")
    if not passwords.valid_password(password):
        raise AuthError(422, "invalid")
    try:
        with db.get_pool().connection() as conn:
            row = conn.execute(
                """
                INSERT INTO users (username, email, first_name, last_name, password_hash, tos_accepted_at)
                VALUES (%s, %s, %s, %s, %s, now())
                RETURNING id, username, first_name, last_name
                """,
                (name, name, given, family, passwords.hash_password(password)),
            ).fetchone()
            conn.commit()
    except IntegrityError as exc:
        raise AuthError(409, "email taken") from exc
    if row is None:
        raise AuthError(500, "register failed")
    user = user_from_row(row)
    issue_verify_token(user.id)
    return user


def login(username: str, password: str, ip: str | None, user_agent: str | None) -> tuple[User, str]:
    name = _normalize_email(username)
    if not valid_email(name) or not passwords.valid_password(password):
        raise AuthError(422, "invalid")
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT id, username, first_name, last_name, password_hash, status, email_verified
            FROM users WHERE username = %s
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
    user = user_from_row(row)
    token = sessions.new_token()
    sessions.create_session(user.id, token, ip, user_agent)
    return user, token


def logout(token: str | None) -> None:
    if token:
        sessions.revoke_token(token)
