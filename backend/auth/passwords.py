"""Argon2id password hashing."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

MIN_PASSWORD = 10
MAX_PASSWORD = 128

_hasher = PasswordHasher()
_DUMMY = _hasher.hash("not-a-real-user")


def valid_password(password: str) -> bool:
    return MIN_PASSWORD <= len(password) <= MAX_PASSWORD


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def verify_dummy(password: str) -> None:
    try:
        _hasher.verify(_DUMMY, password)
    except (VerifyMismatchError, InvalidHashError):
        return
