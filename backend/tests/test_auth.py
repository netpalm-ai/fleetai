"""Auth routes against Postgres when DATABASE_URL is set."""

from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

import pyotp
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import auth.app as auth_api
import db
from auth.service import LOGIN_MAX_FAILURES, Product
from auth.sessions import COOKIE_NAME, cleanup, cookie_secure

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
        key = patch.dict(os.environ, {"AUTH_SECRET_KEY": Fernet.generate_key().decode()})
        key.start()
        self.addCleanup(key.stop)
        verification = patch("auth.service.emails.send_verification_email")
        self.verification_email = verification.start()
        self.addCleanup(verification.stop)
        self.cm = TestClient(auth_api.app)
        self.client = self.cm.__enter__()
        with db.get_pool().connection() as conn:
            conn.execute("TRUNCATE users CASCADE")
            conn.commit()

    def tearDown(self) -> None:
        self.cm.__exit__(None, None, None)

    def _verify(self) -> None:
        token = self.verification_email.call_args.args[2]
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
        self.assertEqual(created.json()["features"], ["tickets"])
        with db.get_pool().connection() as conn:
            event = conn.execute(
                "SELECT product_id FROM subscription_events WHERE user_id = %s",
                (created.json()["id"],),
            ).fetchone()
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
        with db.get_pool().connection() as conn:
            event = conn.execute("SELECT event FROM auth_events").fetchone()
        self.assertEqual(event["event"], "login_unverified")
        self._verify()
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
        self.assertEqual(me.json()["idle_limit_minutes"], 60)
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
        self._verify()
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
        self._verify()
        second = self.client.post(
            "/auth/register",
            json=_reg("casey@example.com", username="casey2"),
            headers=CSRF,
        )
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["detail"], "account taken")

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
        self._verify()
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
            conn.execute("UPDATE sessions SET last_seen_at = now() - interval '30 minutes'")
            conn.commit()
        self.assertEqual(self.client.get("/auth/me").status_code, 200)
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE sessions SET last_seen_at = now() - interval '2 hours'")
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
        with db.get_pool().connection() as conn:
            event = conn.execute("SELECT event FROM auth_events ORDER BY at DESC LIMIT 1").fetchone()
        self.assertEqual(event["event"], "login_disabled")

    def test_register_emails_a_verification_token(self) -> None:
        with patch("auth.service.emails.send_verification_email") as send:
            created = self.client.post("/auth/register", json=_reg(ADA), headers=CSRF)
        self.assertEqual(created.status_code, 201)
        product_name, to, token, valid_days = send.call_args.args
        self.assertEqual((product_name, to, valid_days), ("FleetAI", ADA, 7))
        verified = self.client.post("/auth/verify", json={"token": token}, headers=CSRF)
        self.assertEqual(verified.status_code, 200)

    def test_verification_link_lasts_seven_days(self) -> None:
        with patch("auth.service.emails.send_verification_email") as send:
            self.client.post("/auth/register", json=_reg(ADA), headers=CSRF)
        _, _, token, _ = send.call_args.args
        with db.get_pool().connection() as conn:
            lasts = conn.execute(
                "SELECT email_verify_expires_at - now() > interval '6 days 23 hours' AS ok FROM users WHERE email = %s",
                (ADA,),
            ).fetchone()["ok"]
            conn.execute("UPDATE users SET email_verify_expires_at = now() - interval '1 second'")
            conn.commit()
        self.assertTrue(lasts)
        expired = self.client.post("/auth/verify", json={"token": token}, headers=CSRF)
        self.assertEqual(expired.status_code, 400)

    def test_unverified_email_can_register_again(self) -> None:
        with patch("auth.service.emails.send_verification_email") as send:
            first = self.client.post("/auth/register", json=_reg(ADA), headers=CSRF)
            _, _, old_token, _ = send.call_args.args
            again = self.client.post("/auth/register", json=_reg(ADA, username="ada2"), headers=CSRF)
            _, _, new_token, _ = send.call_args.args
        self.assertEqual(first.status_code, 201)
        self.assertEqual(again.status_code, 201)
        self.assertNotEqual(first.json()["id"], again.json()["id"])
        with db.get_pool().connection() as conn:
            count = conn.execute("SELECT count(*) AS n FROM users WHERE email = %s", (ADA,)).fetchone()["n"]
        self.assertEqual(count, 1)
        stale = self.client.post("/auth/verify", json={"token": old_token}, headers=CSRF)
        self.assertEqual(stale.status_code, 400)
        fresh = self.client.post("/auth/verify", json={"token": new_token}, headers=CSRF)
        self.assertEqual(fresh.status_code, 200)

    def _enable_authenticator(self) -> tuple[pyotp.TOTP, list[str]]:
        setup = self.client.post("/auth/totp/setup", headers=CSRF)
        self.assertEqual(setup.status_code, 200)
        totp = pyotp.TOTP(setup.json()["secret"])
        enabled = self.client.post(
            "/auth/totp/enable", json={"password": PASSWORD, "code": totp.now()}, headers=CSRF
        )
        self.assertEqual(enabled.status_code, 200)
        return totp, enabled.json()["recovery_codes"]

    def _next_code(self, totp: pyotp.TOTP) -> str:
        return totp.at(int(time.time()) + totp.interval)

    def _signed_in_user(self, email: str) -> None:
        self.client.post("/auth/register", json=_reg(email), headers=CSRF)
        self._verify()
        logged = self.client.post("/auth/login", json={"email": email, "password": PASSWORD}, headers=CSRF)
        self.assertEqual(logged.status_code, 200)

    def test_authenticator_is_opt_in_and_then_required_at_login(self) -> None:
        self._signed_in_user(ADA)
        login = {"email": ADA, "password": PASSWORD}
        self.client.post("/auth/logout", headers=CSRF)
        self.assertEqual(self.client.post("/auth/totp/setup", headers=CSRF).status_code, 401)
        self.client.post("/auth/login", json=login, headers=CSRF)
        self.assertFalse(self.client.get("/auth/me").json()["totp_enabled"])
        setup = self.client.post("/auth/totp/setup", headers=CSRF)
        self.assertEqual(setup.status_code, 200)
        self.assertTrue(setup.json()["qr"].startswith("data:image/png;base64,"))
        totp = pyotp.TOTP(setup.json()["secret"])
        wrong = self.client.post("/auth/totp/enable", json={"password": PASSWORD, "code": "000000"}, headers=CSRF)
        self.assertEqual(wrong.status_code, 400)
        no_password = self.client.post(
            "/auth/totp/enable", json={"password": "nope-nope-nope", "code": totp.now()}, headers=CSRF
        )
        self.assertEqual(no_password.status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json=login, headers=CSRF).status_code, 200)
        enabled = self.client.post(
            "/auth/totp/enable", json={"password": PASSWORD, "code": totp.now()}, headers=CSRF
        )
        self.assertEqual(enabled.status_code, 200)
        self.assertEqual(len(enabled.json()["recovery_codes"]), 10)
        self.assertTrue(self.client.get("/auth/me").json()["totp_enabled"])
        again = self.client.post("/auth/totp/setup", headers=CSRF)
        self.assertEqual(again.status_code, 409)
        self.client.post("/auth/logout", headers=CSRF)
        missing = self.client.post("/auth/login", json=login, headers=CSRF)
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json()["detail"], "code required")
        bad = self.client.post("/auth/login", json={**login, "code": "000000"}, headers=CSRF)
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(bad.json()["detail"], "invalid credentials")
        ok = self.client.post("/auth/login", json={**login, "code": self._next_code(totp)}, headers=CSRF)
        self.assertEqual(ok.status_code, 200)

    def test_an_authenticator_code_works_once(self) -> None:
        self._signed_in_user(ADA)
        setup = self.client.post("/auth/totp/setup", headers=CSRF)
        totp = pyotp.TOTP(setup.json()["secret"])
        code = totp.now()
        self.client.post("/auth/totp/enable", json={"password": PASSWORD, "code": code}, headers=CSRF)
        self.client.post("/auth/logout", headers=CSRF)
        login = {"email": ADA, "password": PASSWORD}
        replayed = self.client.post("/auth/login", json={**login, "code": code}, headers=CSRF)
        self.assertEqual(replayed.status_code, 401)
        later = self._next_code(totp)
        self.assertEqual(self.client.post("/auth/login", json={**login, "code": later}, headers=CSRF).status_code, 200)
        self.client.post("/auth/logout", headers=CSRF)
        self.assertEqual(self.client.post("/auth/login", json={**login, "code": later}, headers=CSRF).status_code, 401)

    def test_wrong_codes_lock_the_second_factor_for_a_while(self) -> None:
        self._signed_in_user(ADA)
        totp, recovery_codes = self._enable_authenticator()
        self.client.post("/auth/logout", headers=CSRF)
        login = {"email": ADA, "password": PASSWORD}
        for _ in range(5):
            wrong = self.client.post("/auth/login", json={**login, "code": "000000"}, headers=CSRF)
            self.assertEqual(wrong.status_code, 401)
        for code in (self._next_code(totp), recovery_codes[0]):
            locked = self.client.post("/auth/login", json={**login, "code": code}, headers=CSRF)
            self.assertEqual(locked.status_code, 429)
            self.assertEqual(locked.json()["detail"], "too many attempts")
        wrong_password = self.client.post(
            "/auth/login", json={"email": ADA, "password": "nope-nope-nope", "code": "000000"}, headers=CSRF
        )
        self.assertEqual(wrong_password.status_code, 401)
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE users SET totp_locked_until = now() - interval '1 second'")
            conn.commit()
        ok = self.client.post("/auth/login", json={**login, "code": self._next_code(totp)}, headers=CSRF)
        self.assertEqual(ok.status_code, 200)

    def test_authenticator_secret_is_encrypted_at_rest(self) -> None:
        self._signed_in_user(ADA)
        setup = self.client.post("/auth/totp/setup", headers=CSRF)
        with db.get_pool().connection() as conn:
            stored = conn.execute("SELECT totp_secret FROM users WHERE email = %s", (ADA,)).fetchone()["totp_secret"]
        self.assertNotEqual(stored, setup.json()["secret"])
        self.assertNotIn(setup.json()["secret"], stored)
        for key in ("", "not-a-key"):
            with patch.dict(os.environ, {"AUTH_SECRET_KEY": key}):
                self.assertEqual(self.client.post("/auth/totp/setup", headers=CSRF).status_code, 503)

    def test_a_replaced_key_answers_503_at_login(self) -> None:
        self._signed_in_user(ADA)
        totp, _ = self._enable_authenticator()
        self.client.post("/auth/logout", headers=CSRF)
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": Fernet.generate_key().decode()}):
            answer = self.client.post(
                "/auth/login",
                json={"email": ADA, "password": PASSWORD, "code": self._next_code(totp)},
                headers=CSRF,
            )
        self.assertEqual(answer.status_code, 503)

    def test_a_recovery_code_signs_in_once(self) -> None:
        self._signed_in_user(ADA)
        _, recovery_codes = self._enable_authenticator()
        self.client.post("/auth/logout", headers=CSRF)
        login = {"email": ADA, "password": PASSWORD, "code": recovery_codes[0]}
        first = self.client.post("/auth/login", json=login, headers=CSRF)
        self.assertEqual(first.status_code, 200)
        self.client.post("/auth/logout", headers=CSRF)
        second = self.client.post("/auth/login", json=login, headers=CSRF)
        self.assertEqual(second.status_code, 401)
        other = self.client.post("/auth/login", json={**login, "code": recovery_codes[1]}, headers=CSRF)
        self.assertEqual(other.status_code, 200)

    def test_authenticator_can_be_turned_off_with_password_and_code(self) -> None:
        self._signed_in_user(ADA)
        totp, recovery_codes = self._enable_authenticator()
        wrong_password = self.client.post(
            "/auth/totp/disable", json={"password": "nope-nope-nope", "code": totp.now()}, headers=CSRF
        )
        self.assertEqual(wrong_password.status_code, 401)
        wrong_code = self.client.post(
            "/auth/totp/disable", json={"password": PASSWORD, "code": "000000"}, headers=CSRF
        )
        self.assertEqual(wrong_code.status_code, 401)
        off = self.client.post(
            "/auth/totp/disable", json={"password": PASSWORD, "code": recovery_codes[0]}, headers=CSRF
        )
        self.assertEqual(off.status_code, 204)
        self.assertFalse(self.client.get("/auth/me").json()["totp_enabled"])
        with db.get_pool().connection() as conn:
            row = conn.execute("SELECT totp_secret FROM users WHERE email = %s", (ADA,)).fetchone()
            left = conn.execute("SELECT count(*) AS n FROM totp_recovery_codes").fetchone()["n"]
        self.assertIsNone(row["totp_secret"])
        self.assertEqual(left, 0)
        self.client.post("/auth/logout", headers=CSRF)
        plain = self.client.post("/auth/login", json={"email": ADA, "password": PASSWORD}, headers=CSRF)
        self.assertEqual(plain.status_code, 200)
        self.assertEqual(self.client.post("/auth/totp/setup", headers=CSRF).status_code, 200)

    def test_forgot_password_emails_a_reset_link_to_a_verified_account(self) -> None:
        self._signed_in_user(ADA)
        self.client.post("/auth/register", json=_reg(BOB), headers=CSRF)
        self.client.post("/auth/logout", headers=CSRF)
        with patch("auth.service.emails.send_password_reset_email") as send:
            for email in ("nobody@example.com", BOB, "not-an-email"):
                answer = self.client.post("/auth/password/forgot", json={"email": email}, headers=CSRF)
                self.assertEqual(answer.status_code, 202)
            send.assert_not_called()
            self.client.post("/auth/password/forgot", json={"email": ADA}, headers=CSRF)
        with db.get_pool().connection() as conn:
            requested = conn.execute(
                "SELECT count(*) AS n FROM auth_events WHERE event = 'password_reset_requested'"
            ).fetchone()["n"]
        self.assertEqual(requested, 2)
        product_name, to, token, valid_minutes = send.call_args.args
        self.assertEqual((product_name, to, valid_minutes), ("FleetAI", ADA, 60))
        self.assertTrue(token)

    def test_reset_password_sets_it_once_and_signs_everyone_out(self) -> None:
        self._signed_in_user(ADA)
        with patch("auth.service.emails.send_password_reset_email") as send:
            self.client.post("/auth/password/forgot", json={"email": ADA}, headers=CSRF)
        _, _, token, _ = send.call_args.args
        short = self.client.post("/auth/password/reset", json={"token": token, "password": "short"}, headers=CSRF)
        self.assertEqual(short.status_code, 422)
        reset = self.client.post(
            "/auth/password/reset", json={"token": token, "password": "brand-new-password"}, headers=CSRF
        )
        self.assertEqual(reset.status_code, 204)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        again = self.client.post(
            "/auth/password/reset", json={"token": token, "password": "another-password-1"}, headers=CSRF
        )
        self.assertEqual(again.status_code, 400)
        with db.get_pool().connection() as conn:
            failed = conn.execute(
                "SELECT count(*) AS n FROM auth_events WHERE event = 'password_reset_failed'"
            ).fetchone()["n"]
        self.assertEqual(failed, 0)
        old = self.client.post("/auth/login", json={"email": ADA, "password": PASSWORD}, headers=CSRF)
        self.assertEqual(old.status_code, 401)
        new = self.client.post(
            "/auth/login", json={"email": ADA, "password": "brand-new-password"}, headers=CSRF
        )
        self.assertEqual(new.status_code, 200)

    def test_reset_link_expires_and_keeps_the_authenticator(self) -> None:
        self._signed_in_user(ADA)
        totp, _ = self._enable_authenticator()
        self.client.post("/auth/logout", headers=CSRF)
        with patch("auth.service.emails.send_password_reset_email") as send:
            self.client.post("/auth/password/forgot", json={"email": ADA}, headers=CSRF)
        _, _, token, _ = send.call_args.args
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE users SET password_reset_expires_at = now() - interval '1 second'")
            conn.commit()
        body = {"token": token, "password": "brand-new-password"}
        self.assertEqual(self.client.post("/auth/password/reset", json=body, headers=CSRF).status_code, 400)
        with db.get_pool().connection() as conn:
            failed = conn.execute(
                "SELECT event FROM auth_events WHERE event = 'password_reset_failed'"
            ).fetchone()
        self.assertEqual(failed["event"], "password_reset_failed")
        with patch("auth.service.emails.send_password_reset_email") as send:
            self.client.post("/auth/password/forgot", json={"email": ADA}, headers=CSRF)
        _, _, fresh, _ = send.call_args.args
        self.client.post("/auth/password/reset", json={**body, "token": fresh}, headers=CSRF)
        login = {"email": ADA, "password": "brand-new-password"}
        needs_code = self.client.post("/auth/login", json=login, headers=CSRF)
        self.assertEqual(needs_code.json()["detail"], "code required")
        ok = self.client.post("/auth/login", json={**login, "code": self._next_code(totp)}, headers=CSRF)
        self.assertEqual(ok.status_code, 200)

    def test_changing_the_password_cancels_a_pending_reset_link(self) -> None:
        self._signed_in_user(ADA)
        with patch("auth.service.emails.send_password_reset_email") as send:
            self.client.post("/auth/password/forgot", json={"email": ADA}, headers=CSRF)
        _, _, token, _ = send.call_args.args
        changed = self.client.post(
            "/auth/password",
            json={"current_password": PASSWORD, "new_password": "correct-horse-2"},
            headers=CSRF,
        )
        self.assertEqual(changed.status_code, 204)
        stale = self.client.post(
            "/auth/password/reset", json={"token": token, "password": "brand-new-password"}, headers=CSRF
        )
        self.assertEqual(stale.status_code, 400)

    def test_expired_unverified_accounts_are_removed(self) -> None:
        self.client.post("/auth/register", json=_reg(ADA), headers=CSRF)
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE users SET email_verify_expires_at = now() - interval '1 second'")
            conn.commit()
        self.client.post("/auth/register", json=_reg(BOB), headers=CSRF)
        self.client.post("/auth/register", json=_reg(EVE), headers=CSRF)
        self._verify()
        cleanup()
        with db.get_pool().connection() as conn:
            left = conn.execute("SELECT email::text AS email FROM users ORDER BY email").fetchall()
        self.assertEqual([row["email"] for row in left], [BOB, EVE])
        retaken = self.client.post("/auth/register", json=_reg("ada2@example.com", username="ada"), headers=CSRF)
        self.assertEqual(retaken.status_code, 201)

    def test_non_ascii_tokens_are_rejected_not_crashed(self) -> None:
        verified = self.client.post("/auth/verify", json={"token": "tökén"}, headers=CSRF)
        self.assertEqual(verified.status_code, 400)
        reset = self.client.post(
            "/auth/password/reset", json={"token": "tökén", "password": "brand-new-password"}, headers=CSRF
        )
        self.assertEqual(reset.status_code, 400)
        self.assertEqual(self.client.get("/auth/me", headers={"Cookie": COOKIE_NAME + "=t%C3%B6k"}).status_code, 401)

    def test_session_keeps_a_bounded_user_agent(self) -> None:
        self.client.post("/auth/register", json=_reg(ADA), headers=CSRF)
        self._verify()
        self.client.post(
            "/auth/login",
            json={"email": ADA, "password": PASSWORD},
            headers={**CSRF, "User-Agent": "agent-" + "x" * 600},
        )
        with db.get_pool().connection() as conn:
            stored = conn.execute("SELECT user_agent FROM sessions").fetchone()["user_agent"]
        self.assertEqual(len(stored), 512)
        self.assertTrue(stored.startswith("agent-"))

    def test_an_oversized_password_is_rejected_without_hashing(self) -> None:
        self._signed_in_user(ADA)
        with patch("auth.passwords._hasher") as hasher:
            answer = self.client.post(
                "/auth/password",
                json={"current_password": "x" * 200, "new_password": "correct-horse-2"},
                headers=CSRF,
            )
        self.assertEqual(answer.status_code, 401)
        hasher.verify.assert_not_called()

    def test_wrong_passwords_lock_sign_in_for_a_while(self) -> None:
        self._signed_in_user(ADA)
        self.client.post("/auth/logout", headers=CSRF)
        login = {"email": ADA, "password": PASSWORD}
        wrong = {"email": ADA, "password": "nope-nope-nope"}
        for _ in range(LOGIN_MAX_FAILURES - 1):
            self.assertEqual(self.client.post("/auth/login", json=wrong, headers=CSRF).status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json=login, headers=CSRF).status_code, 200)
        for _ in range(LOGIN_MAX_FAILURES):
            self.assertEqual(self.client.post("/auth/login", json=wrong, headers=CSRF).status_code, 401)
        locked = self.client.post("/auth/login", json=login, headers=CSRF)
        self.assertEqual(locked.status_code, 429)
        self.assertEqual(locked.json()["detail"], "too many attempts")
        with db.get_pool().connection() as conn:
            event = conn.execute("SELECT event FROM auth_events ORDER BY at DESC LIMIT 1").fetchone()
        self.assertEqual(event["event"], "login_locked")
        with db.get_pool().connection() as conn:
            conn.execute("UPDATE users SET login_locked_until = now() - interval '1 second'")
            conn.commit()
        self.assertEqual(self.client.post("/auth/login", json=login, headers=CSRF).status_code, 200)

    def test_a_password_reset_lifts_the_sign_in_lock(self) -> None:
        self._signed_in_user(ADA)
        self.client.post("/auth/logout", headers=CSRF)
        for _ in range(LOGIN_MAX_FAILURES):
            self.client.post("/auth/login", json={"email": ADA, "password": "nope-nope-nope"}, headers=CSRF)
        with patch("auth.service.emails.send_password_reset_email") as send:
            self.client.post("/auth/password/forgot", json={"email": ADA}, headers=CSRF)
        _, _, token, _ = send.call_args.args
        self.client.post("/auth/password/reset", json={"token": token, "password": "brand-new-password"}, headers=CSRF)
        unlocked = self.client.post(
            "/auth/login", json={"email": ADA, "password": "brand-new-password"}, headers=CSRF
        )
        self.assertEqual(unlocked.status_code, 200)

    def test_forgot_password_sends_one_link_within_the_resend_window(self) -> None:
        self._signed_in_user(ADA)
        with patch("auth.service.emails.send_password_reset_email") as send:
            self.client.post("/auth/password/forgot", json={"email": ADA}, headers=CSRF)
            self.client.post("/auth/password/forgot", json={"email": ADA}, headers=CSRF)
            send.assert_called_once()
            with db.get_pool().connection() as conn:
                conn.execute(
                    "UPDATE users SET password_reset_expires_at = password_reset_expires_at - interval '6 minutes'"
                )
                conn.commit()
            self.client.post("/auth/password/forgot", json={"email": ADA}, headers=CSRF)
            self.assertEqual(send.call_count, 2)
        with db.get_pool().connection() as conn:
            requested = conn.execute(
                "SELECT count(*) AS n FROM auth_events WHERE event = 'password_reset_requested'"
            ).fetchone()["n"]
        self.assertEqual(requested, 3)

    def test_security_events_are_recorded_with_the_client_address(self) -> None:
        self.client.post("/auth/register", json=_reg(ADA), headers=CSRF)
        self._verify()
        login = {"email": ADA, "password": PASSWORD}
        client = TestClient(auth_api.app, client=("203.0.113.9", 50000))
        client.post("/auth/login", json={**login, "password": "nope-nope-nope"}, headers=CSRF)
        client.post("/auth/login", json=login, headers=CSRF)
        setup = client.post("/auth/totp/setup", headers=CSRF)
        totp = pyotp.TOTP(setup.json()["secret"])
        client.post("/auth/totp/enable", json={"password": PASSWORD, "code": totp.now()}, headers=CSRF)
        client.post("/auth/login", json={**login, "code": "000000"}, headers=CSRF)
        client.post("/auth/totp/disable", json={"password": PASSWORD, "code": self._next_code(totp)}, headers=CSRF)
        client.post(
            "/auth/password",
            json={"current_password": PASSWORD, "new_password": "correct-horse-2"},
            headers=CSRF,
        )
        with patch("auth.service.emails.send_password_reset_email") as send:
            client.post("/auth/password/forgot", json={"email": ADA}, headers=CSRF)
        _, _, token, _ = send.call_args.args
        client.post("/auth/password/reset", json={"token": token, "password": "brand-new-password"}, headers=CSRF)
        with db.get_pool().connection() as conn:
            events = conn.execute("SELECT event, host(ip) AS ip FROM auth_events ORDER BY at").fetchall()
        self.assertEqual(
            [row["event"] for row in events],
            [
                "login_failed",
                "login",
                "totp_enabled",
                "second_factor_failed",
                "totp_disabled",
                "password_changed",
                "password_reset_requested",
                "password_reset",
            ],
        )
        self.assertEqual({row["ip"] for row in events}, {"203.0.113.9"})

    def test_one_account_signs_in_to_a_second_product(self) -> None:
        with db.get_pool().connection() as conn:
            conn.execute("INSERT INTO products (id, name) VALUES ('notes', 'Notes') ON CONFLICT (id) DO NOTHING")
            conn.execute(
                "INSERT INTO product_tiers (product_id, status) VALUES ('notes', 'free') "
                "ON CONFLICT (product_id, status) DO NOTHING"
            )
            conn.commit()
        self._signed_in_user(ADA)
        self.assertEqual(self.client.get("/auth/me").json()["registered_product"], "fleetai")
        with patch.object(auth_api.app.state, "auth_product", Product(id="notes", name="Notes", signup_tier="free")):
            taken = self.client.post("/auth/register", json=_reg(ADA, username="ada2"), headers=CSRF)
            self.assertEqual(taken.status_code, 409)
            self.assertEqual(self.client.get("/auth/me").json()["registered_product"], "")
            logged = self.client.post("/auth/login", json={"email": ADA, "password": PASSWORD}, headers=CSRF)
            self.assertEqual(logged.status_code, 200)
            self.assertEqual(logged.json()["registered_product"], "notes")
            self.assertEqual(logged.json()["subscription_status"], "free")
            self.assertEqual(logged.json()["features"], [])
            with patch("auth.service.emails.send_verification_email") as send:
                created = self.client.post("/auth/register", json=_reg(BOB), headers=CSRF)
            self.assertEqual(created.json()["registered_product"], "notes")
            self.assertEqual(send.call_args.args[0], "Notes")
        self.assertEqual(self.client.get("/auth/me").json()["features"], ["tickets"])
        with db.get_pool().connection() as conn:
            subscribed = conn.execute(
                """
                SELECT us.product_id
                FROM user_subscriptions us
                JOIN users u ON u.id = us.user_id
                WHERE u.email = %s
                ORDER BY us.product_id
                """,
                (ADA,),
            ).fetchall()
        self.assertEqual([row["product_id"] for row in subscribed], ["fleetai", "notes"])

    def test_idle_limit_follows_environment(self) -> None:
        self.client.post("/auth/register", json=_reg(EVE), headers=CSRF)
        self._verify()
        with patch.dict(os.environ, {"SESSION_IDLE_MIN_LIMIT": "10"}):
            logged = self.client.post(
                "/auth/login",
                json={"email": EVE, "password": PASSWORD},
                headers=CSRF,
            )
            self.assertEqual(logged.json()["idle_limit_minutes"], 10)
            with db.get_pool().connection() as conn:
                conn.execute("UPDATE sessions SET last_seen_at = now() - interval '15 minutes'")
                conn.commit()
            self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_password_change_revokes_sessions(self) -> None:
        self.client.post("/auth/register", json=_reg(ADA), headers=CSRF)
        self._verify()
        self.client.post(
            "/auth/login",
            json={"email": ADA, "password": PASSWORD},
            headers=CSRF,
        )
        self.assertEqual(self.client.get("/auth/me").status_code, 200)
        changed = self.client.post(
            "/auth/password",
            json={"current_password": PASSWORD, "new_password": "correct-horse-2"},
            headers=CSRF,
        )
        self.assertEqual(changed.status_code, 204)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        old = self.client.post(
            "/auth/login",
            json={"email": ADA, "password": PASSWORD},
            headers=CSRF,
        )
        self.assertEqual(old.status_code, 401)
        new = self.client.post(
            "/auth/login",
            json={"email": ADA, "password": "correct-horse-2"},
            headers=CSRF,
        )
        self.assertEqual(new.status_code, 200)
        self.assertEqual(self.client.get("/auth/me").status_code, 200)


class CookieTests(unittest.TestCase):
    def test_cookie_is_secure_unless_turned_off(self) -> None:
        for value, secure in (("", True), ("true", True), ("false", False), ("0", False), ("no", False)):
            with self.subTest(value=value), patch.dict(os.environ, {"COOKIE_SECURE": value}):
                self.assertEqual(cookie_secure(), secure)
