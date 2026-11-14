"""Auth routes against Postgres when DATABASE_URL is set."""

from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from uuid import UUID

import api
import db
from auth.service import issue_verify_token
from auth.sessions import COOKIE_NAME

CSRF = {"X-Requested-With": "fleetai"}
ADA = "ada@example.com"
BOB = "bob@example.com"
CASEY = "Casey@example.com"
EVE = "eve@example.com"
ZED = "zed@example.com"
PASSWORD = "correct-horse"


def _handle(email: str) -> str:
    return email.split("@", 1)[0]


def _reg(email: str, **extra) -> dict:
    body = {
        "username": _handle(email),
        "email": email,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "password": PASSWORD,
        "tos_accepted": True,
    }
    body.update(extra)
    return body


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

    def _verify(self, user_id: str) -> None:
        token = issue_verify_token(UUID(user_id))
        verified = self.client.post("/auth/verify", json={"token": token}, headers=CSRF)
        self.assertEqual(verified.status_code, 200)

    def test_register_login_me_logout(self) -> None:
        created = self.client.post(
            "/auth/register",
            json=_reg(ADA),
            headers=CSRF,
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["username"], _handle(ADA))
        self.assertEqual(created.json()["email"], ADA)
        self.assertEqual(created.json()["status"], "active")
        self.assertIsNone(created.json()["last_signed_in_ts"])
        self.assertEqual(created.json()["subscription_status"], "free")
        self.assertEqual(created.json()["registered_product"], "fleetai")
        self.assertEqual(created.json()["features"], [])
        with db.get_pool().connection() as conn:
            sub = conn.execute(
                """
                SELECT us.product_id, pt.status
                FROM user_subscriptions us
                JOIN product_tiers pt ON pt.id = us.tier_id
                WHERE us.user_id = %s
                """,
                (created.json()["id"],),
            ).fetchone()
        self.assertIsNotNone(sub)
        self.assertEqual(str(sub["product_id"]), "fleetai")
        self.assertEqual(str(sub["status"]), "free")
        self.assertNotIn(COOKIE_NAME, created.cookies)
        blocked = self.client.post(
            "/auth/login",
            json={"email": ADA, "password": PASSWORD},
            headers=CSRF,
        )
        self.assertEqual(blocked.status_code, 403)
        self._verify(created.json()["id"])
        logged = self.client.post(
            "/auth/login",
            json={"email": ADA, "password": PASSWORD},
            headers=CSRF,
        )
        self.assertEqual(logged.status_code, 200)
        me = self.client.get("/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["username"], _handle(ADA))
        self.assertEqual(me.json()["email"], ADA)
        self.assertEqual(logged.json()["status"], "active")
        self.assertIsNotNone(logged.json()["last_signed_in_ts"])
        self.assertEqual(me.json()["last_signed_in_ts"], logged.json()["last_signed_in_ts"])
        self.assertEqual(me.json()["first_name"], "Ada")
        self.assertEqual(me.json()["last_name"], "Lovelace")
        with db.get_pool().connection() as conn:
            row = conn.execute(
                "SELECT password_hash, email FROM users WHERE email = %s",
                (ADA,),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(str(row["email"]), ADA)
        self.assertTrue(str(row["password_hash"]).startswith("$argon2id$"))
        self.assertNotIn(PASSWORD, str(row["password_hash"]))
        out = self.client.post("/auth/logout", headers=CSRF)
        self.assertEqual(out.status_code, 204)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_login_sets_cookie(self) -> None:
        created = self.client.post(
            "/auth/register",
            json=_reg(BOB),
            headers=CSRF,
        )
        self._verify(created.json()["id"])
        logged = self.client.post(
            "/auth/login",
            json={"email": BOB, "password": PASSWORD},
            headers=CSRF,
        )
        self.assertEqual(logged.status_code, 200)
        self.assertEqual(self.client.get("/auth/me").json()["username"], _handle(BOB))

    def test_duplicate_email_is_case_insensitive(self) -> None:
        first = self.client.post(
            "/auth/register",
            json=_reg(CASEY),
            headers=CSRF,
        )
        self.assertEqual(first.status_code, 201)
        second = self.client.post(
            "/auth/register",
            json=_reg("casey@example.com", username="casey2"),
            headers=CSRF,
        )
        self.assertEqual(second.status_code, 409)

    def test_invalid_register(self) -> None:
        not_email = self.client.post(
            "/auth/register",
            json=_reg("eve"),
            headers=CSRF,
        )
        self.assertEqual(not_email.status_code, 422)
        weak = self.client.post(
            "/auth/register",
            json=_reg(EVE, password="short"),
            headers=CSRF,
        )
        self.assertEqual(weak.status_code, 422)
        tos = self.client.post(
            "/auth/register",
            json=_reg(EVE, tos_accepted=False),
            headers=CSRF,
        )
        self.assertEqual(tos.status_code, 422)
        no_name = self.client.post(
            "/auth/register",
            json=_reg(EVE, first_name=""),
            headers=CSRF,
        )
        self.assertEqual(no_name.status_code, 422)

    def test_login_requires_email_and_password(self) -> None:
        bad_id = self.client.post(
            "/auth/login",
            json={"email": "bob", "password": PASSWORD},
            headers=CSRF,
        )
        self.assertEqual(bad_id.status_code, 422)
        empty = self.client.post(
            "/auth/login",
            json={"email": BOB, "password": ""},
            headers=CSRF,
        )
        self.assertEqual(empty.status_code, 422)

    def test_login_unknown_is_generic(self) -> None:
        response = self.client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": PASSWORD},
            headers=CSRF,
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "invalid credentials")

    def test_csrf_required_on_post(self) -> None:
        response = self.client.post(
            "/auth/login",
            json={"email": BOB, "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 403)

    def test_logout_without_session_is_204(self) -> None:
        response = self.client.post("/auth/logout", headers=CSRF)
        self.assertEqual(response.status_code, 204)

    def test_revoked_expired_idle_disabled_are_401(self) -> None:
        created = self.client.post(
            "/auth/register",
            json=_reg(ZED),
            headers=CSRF,
        )
        self._verify(created.json()["id"])
        self.client.post(
            "/auth/login",
            json={"email": ZED, "password": PASSWORD},
            headers=CSRF,
        )
        self.assertEqual(self.client.get("/auth/me").status_code, 200)
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE sessions SET revoked_at = now()")
            conn.commit()
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

        logged = self.client.post(
            "/auth/login",
            json={"email": ZED, "password": PASSWORD},
            headers=CSRF,
        )
        self.assertEqual(logged.status_code, 200)
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE sessions SET expires_at = now() - interval '1 day'")
            conn.commit()
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

        self.client.post(
            "/auth/login",
            json={"email": ZED, "password": PASSWORD},
            headers=CSRF,
        )
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE sessions SET last_seen_at = now() - interval '8 days'")
            conn.commit()
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

        self.client.post(
            "/auth/login",
            json={"email": ZED, "password": PASSWORD},
            headers=CSRF,
        )
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE users SET status = 'disabled'")
            conn.commit()
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        disabled_login = self.client.post(
            "/auth/login",
            json={"email": ZED, "password": PASSWORD},
            headers=CSRF,
        )
        self.assertEqual(disabled_login.status_code, 401)
        self.assertEqual(disabled_login.json()["detail"], "invalid credentials")
