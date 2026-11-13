"""Auth routes against Postgres when DATABASE_URL is set."""

from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

import api
import db
from auth.sessions import COOKIE_NAME

CSRF = {"X-Requested-With": "fleetai"}


@unittest.skipUnless(os.getenv("DATABASE_URL"), "DATABASE_URL is required")
class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cm = TestClient(api.app)
        self.client = self.cm.__enter__()
        with db.get_pool().connection() as conn:
            conn.execute("TRUNCATE users CASCADE")
            conn.commit()

    def tearDown(self) -> None:
        self.cm.__exit__(None, None, None)

    def test_register_login_me_logout(self) -> None:
        created = self.client.post(
            "/auth/register",
            json={"username": "Ada", "password": "correct-horse", "tos_accepted": True},
            headers=CSRF,
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["username"], "Ada")
        self.assertIn(COOKIE_NAME, created.cookies)
        me = self.client.get("/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["username"], "Ada")
        with db.get_pool().connection() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE username = %s", ("Ada",)).fetchone()
        self.assertIsNotNone(row)
        self.assertTrue(str(row["password_hash"]).startswith("$argon2id$"))
        self.assertNotIn("correct-horse", str(row["password_hash"]))
        out = self.client.post("/auth/logout", headers=CSRF)
        self.assertEqual(out.status_code, 204)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_login_sets_cookie(self) -> None:
        self.client.post(
            "/auth/register",
            json={"username": "bob", "password": "correct-horse", "tos_accepted": True},
            headers=CSRF,
        )
        self.client.post("/auth/logout", headers=CSRF)
        logged = self.client.post(
            "/auth/login",
            json={"username": "bob", "password": "correct-horse"},
            headers=CSRF,
        )
        self.assertEqual(logged.status_code, 200)
        self.assertEqual(self.client.get("/auth/me").json()["username"], "bob")

    def test_duplicate_username_is_case_insensitive(self) -> None:
        first = self.client.post(
            "/auth/register",
            json={"username": "Casey", "password": "correct-horse", "tos_accepted": True},
            headers=CSRF,
        )
        self.assertEqual(first.status_code, 201)
        second = self.client.post(
            "/auth/register",
            json={"username": "casey", "password": "correct-horse", "tos_accepted": True},
            headers=CSRF,
        )
        self.assertEqual(second.status_code, 409)

    def test_invalid_register(self) -> None:
        weak = self.client.post(
            "/auth/register",
            json={"username": "eve", "password": "short", "tos_accepted": True},
            headers=CSRF,
        )
        self.assertEqual(weak.status_code, 422)
        tos = self.client.post(
            "/auth/register",
            json={"username": "eve", "password": "correct-horse", "tos_accepted": False},
            headers=CSRF,
        )
        self.assertEqual(tos.status_code, 422)

    def test_login_unknown_is_generic(self) -> None:
        response = self.client.post(
            "/auth/login",
            json={"username": "nobody", "password": "correct-horse"},
            headers=CSRF,
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "invalid credentials")

    def test_csrf_required_on_post(self) -> None:
        response = self.client.post(
            "/auth/login",
            json={"username": "bob", "password": "correct-horse"},
        )
        self.assertEqual(response.status_code, 403)

    def test_logout_without_session_is_204(self) -> None:
        response = self.client.post("/auth/logout", headers=CSRF)
        self.assertEqual(response.status_code, 204)

    def test_revoked_expired_idle_disabled_are_401(self) -> None:
        self.client.post(
            "/auth/register",
            json={"username": "zed", "password": "correct-horse", "tos_accepted": True},
            headers=CSRF,
        )
        self.assertEqual(self.client.get("/auth/me").status_code, 200)
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE sessions SET revoked_at = now()")
            conn.commit()
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

        logged = self.client.post(
            "/auth/login",
            json={"username": "zed", "password": "correct-horse"},
            headers=CSRF,
        )
        self.assertEqual(logged.status_code, 200)
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE sessions SET expires_at = now() - interval '1 day'")
            conn.commit()
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

        self.client.post(
            "/auth/login",
            json={"username": "zed", "password": "correct-horse"},
            headers=CSRF,
        )
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE sessions SET last_seen_at = now() - interval '8 days'")
            conn.commit()
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

        self.client.post(
            "/auth/login",
            json={"username": "zed", "password": "correct-horse"},
            headers=CSRF,
        )
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE users SET status = 'disabled'")
            conn.commit()
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        disabled_login = self.client.post(
            "/auth/login",
            json={"username": "zed", "password": "correct-horse"},
            headers=CSRF,
        )
        self.assertEqual(disabled_login.status_code, 401)
        self.assertEqual(disabled_login.json()["detail"], "invalid credentials")
