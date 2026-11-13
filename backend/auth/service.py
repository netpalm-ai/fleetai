"""Register, login, and session create/revoke."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from psycopg.errors import IntegrityError

import db
from auth import passwords, sessions


@dataclass(frozen=True)
class User:
    id: UUID
    username: str


class AuthError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _normalize_username(username: str) -> str:
    return username.strip()


def register(username: str, password: str, tos_accepted: bool, ip: str | None, user_agent: str | None) -> tuple[User, str]:
    name = _normalize_username(username)
    if not name or len(name) > 64:
        raise AuthError(422, "invalid")
    if not tos_accepted:
        raise AuthError(422, "invalid")
    if not passwords.valid_password(password):
        raise AuthError(422, "invalid")
    try:
        with db.get_pool().connection() as conn:
            row = conn.execute(
                """
                INSERT INTO users (username, password_hash, tos_accepted_at)
                VALUES (%s, %s, now())
                RETURNING id, username
                """,
                (name, passwords.hash_password(password)),
            ).fetchone()
            conn.commit()
    except IntegrityError as exc:
        raise AuthError(409, "username taken") from exc
    if row is None:
        raise AuthError(500, "register failed")
    user = User(id=row["id"], username=str(row["username"]))
    token = sessions.new_token()
    sessions.create_session(user.id, token, ip, user_agent)
    return user, token


def login(username: str, password: str, ip: str | None, user_agent: str | None) -> tuple[User, str]:
    name = _normalize_username(username)
    with db.get_pool().connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, status FROM users WHERE username = %s",
            (name,),
        ).fetchone()
    if row is None:
        passwords.verify_dummy(password)
        raise AuthError(401, "invalid credentials")
    if not passwords.verify_password(row["password_hash"], password):
        raise AuthError(401, "invalid credentials")
    if row["status"] != "active":
        raise AuthError(401, "invalid credentials")
    user = User(id=row["id"], username=str(row["username"]))
    token = sessions.new_token()
    sessions.create_session(user.id, token, ip, user_agent)
    return user, token


def logout(token: str | None) -> None:
    if token:
        sessions.revoke_token(token)
