"""Intake uploads are tracked and previous rows are deactivated."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

import api
import config
import db
import intakes
from auth.service import issue_verify_token
from auth.sessions import COOKIE_NAME

CSRF = {"X-Requested-With": "fleetai"}
EMAIL = "ada@example.com"
PASSWORD = "correct-horse"


@unittest.skipUnless(os.getenv("DATABASE_URL"), "DATABASE_URL is required")
class IntakeTrackingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [
            patch.object(config, "TICKETS_DIR", root),
            patch.object(config, "EMAIL_PATH", root / "email.desc.txt"),
            patch.object(config, "PDF_PATH", root / "list.pdf"),
            patch.object(config, "LIST_TEXT_PATH", root / "list.txt"),
            patch.object(config, "ADDITIONAL_CONTEXT_PATH", root / "additional_context.pdf"),
            patch.object(config, "CONTEXT_MD_PATH", root / "additional_context.md"),
            patch.object(config, "LOCK_PATH", root / ".lock"),
            patch.object(intakes, "TICKETS_DIR", root),
            patch.object(intakes, "INTAKES_DIR", root / "intakes"),
        ]
        for item in self.patches:
            item.start()
        self.cm = TestClient(api.app)
        self.client = self.cm.__enter__()
        with db.get_pool().connection() as conn:
            conn.execute("TRUNCATE users CASCADE")
            conn.commit()
        created = self.client.post(
            "/auth/register",
            json={
                "username": "ada",
                "email": EMAIL,
                "first_name": "Ada",
                "last_name": "Lovelace",
                "password": PASSWORD,
                "tos_accepted": True,
            },
            headers=CSRF,
        )
        self.assertEqual(created.status_code, 201)
        self.user_id = UUID(created.json()["id"])
        token = issue_verify_token(self.user_id)
        self.client.post("/auth/verify", json={"token": token}, headers=CSRF)
        logged = self.client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers=CSRF)
        self.assertEqual(logged.status_code, 200)
        self.assertIn(COOKIE_NAME, self.client.cookies)

    def tearDown(self) -> None:
        self.cm.__exit__(None, None, None)
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def test_replacing_list_deactivates_previous_intake(self) -> None:
        first = self.client.post(
            "/tickets/inputs",
            json={"email": "first notes", "list_text": "T1 login fails"},
            headers=CSRF,
        )
        self.assertEqual(first.status_code, 204)
        second = self.client.post(
            "/tickets/inputs",
            json={"email": "second notes", "list_text": "T2 export hangs"},
            headers=CSRF,
        )
        self.assertEqual(second.status_code, 204)
        with db.get_pool().connection() as conn:
            rows = conn.execute(
                """
                SELECT type, format, status
                FROM intakes
                WHERE user_id = %s
                ORDER BY created_at, type
                """,
                (self.user_id,),
            ).fetchall()
        kinds = [(str(row["type"]), str(row["format"]), str(row["status"])) for row in rows]
        self.assertEqual(
            kinds,
            [
                ("email_desc", "txt", "deactivated"),
                ("ticket_list", "txt", "deactivated"),
                ("email_desc", "txt", "active"),
                ("ticket_list", "txt", "active"),
            ],
        )

    def test_sync_tickets_stores_user_and_session(self) -> None:
        self.client.post(
            "/tickets/inputs",
            json={"list_text": "T1 login fails"},
            headers=CSRF,
        )
        with db.get_pool().connection() as conn:
            session = conn.execute(
                "SELECT id FROM sessions WHERE user_id = %s AND revoked_at IS NULL",
                (self.user_id,),
            ).fetchone()
        intakes.sync_tickets(
            self.user_id,
            session["id"],
            [
                {
                    "id": "T1",
                    "title": "login fails",
                    "severity": "high",
                    "services": ["api"],
                    "context": "short password",
                    "expected": "reject",
                    "kind": "new",
                    "status": "unresolved",
                }
            ],
        )
        tracked = intakes.list_open_tickets(self.user_id)
        self.assertEqual(tracked[0]["id"], "T1")
        self.assertEqual(tracked[0]["title"], "login fails")
        self.assertEqual(tracked[0]["status"], "unresolved")
        with db.get_pool().connection() as conn:
            row = conn.execute(
                "SELECT user_id, session_id, context, intake_id FROM tickets WHERE user_id = %s AND public_id = %s",
                (self.user_id, "T1"),
            ).fetchone()
        self.assertEqual(row["user_id"], self.user_id)
        self.assertEqual(row["session_id"], session["id"])
        self.assertEqual(row["context"], "short password")
        self.assertIsNotNone(row["intake_id"])
