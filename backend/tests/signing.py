"""Sign in through the auth app, then carry the session cookie to the API client."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

import db
from auth.app import app as auth_app

CSRF = {"X-Requested-With": "fleetai"}


def register_verify_login(
    api_client: TestClient,
    *,
    email: str,
    password: str,
    username: str,
    first_name: str = "Ada",
    last_name: str = "Lovelace",
) -> UUID:
    with TestClient(auth_app) as auth:
        with patch("auth.service.emails.send_verification_email") as send:
            created = auth.post(
                "/auth/register",
                json={
                    "username": username,
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "password": password,
                    "tos_accepted": True,
                },
                headers=CSRF,
            )
            assert created.status_code == 201, created.text
            token = send.call_args.args[2]
        verified = auth.post("/auth/verify", json={"token": token}, headers=CSRF)
        assert verified.status_code == 200, verified.text
        logged = auth.post("/auth/login", json={"email": email, "password": password}, headers=CSRF)
        assert logged.status_code == 200, logged.text
        api_client.cookies.update(auth.cookies)
        user_id = UUID(created.json()["id"])
    db.open_pool()
    return user_id
