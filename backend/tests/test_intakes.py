"""Intakes, tickets, run logs, and retention live in Postgres."""

from __future__ import annotations

import base64
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import psycopg
import pymupdf
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

import api
import config
import db
import intakes
import orchestrator
import parser
import solver
import verifier
from auth.sessions import COOKIE_NAME

CSRF = {"X-Requested-With": "fleetai"}
EMAIL = "ada@example.com"
PASSWORD = "correct-horse"


def _ticket(ticket_id: str, status: str = "unresolved") -> dict:
    return {
        "id": ticket_id,
        "title": "login fails",
        "severity": "high",
        "services": ["api"],
        "context": "short password",
        "expected": "reject",
        "kind": "new",
        "status": status,
    }


def _minimal_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "T9 export hangs")
    data = document.tobytes()
    document.close()
    return data


@unittest.skipUnless(os.getenv("DATABASE_URL"), "DATABASE_URL is required")
class TicketStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cm = TestClient(api.app)
        self.client = self.cm.__enter__()
        with db.get_pool().connection() as conn:
            conn.execute("TRUNCATE users CASCADE")
            conn.commit()
        with patch("auth.service.emails.send_verification_email") as send:
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
        self.client.post("/auth/verify", json={"token": send.call_args.args[2]}, headers=CSRF)
        logged = self.client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers=CSRF)
        self.assertEqual(logged.status_code, 200)
        self.assertIn(COOKIE_NAME, self.client.cookies)

    def tearDown(self) -> None:
        self.cm.__exit__(None, None, None)

    def _tier(self, status: str) -> None:
        with db.get_pool().connection() as conn:
            conn.execute(
                """
                UPDATE user_subscriptions
                SET tier_id = (
                  SELECT id FROM product_tiers WHERE product_id = 'fleetai' AND status = %s
                )
                WHERE user_id = %s AND product_id = 'fleetai'
                """,
                (status, self.user_id),
            )
            conn.commit()

    def _age_handled(self, ticket_id: str, days: int) -> None:
        with db.get_pool().connection() as conn:
            conn.execute(
                """
                UPDATE tickets SET handled_at = now() - make_interval(days => %s)
                WHERE user_id = %s AND public_id = %s
                """,
                (days, self.user_id, ticket_id),
            )
            conn.commit()

    def _solve_and_verify(self, ticket_id: str, final: str) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket(ticket_id)])
        ready = SimpleNamespace(
            id="run-solve", result="CHANGED FILES:\napi/login.py\nVERDICT: ready"
        )
        done = SimpleNamespace(
            id="run-verify",
            result="CHANGED FILES:\napi/login.py\nVERDICT: {0}".format(final),
        )
        with patch("llm.cursor.run", side_effect=[ready, done]), patch("verifier.push_ticket"):
            solver.solve(self.user_id, ticket_id)
            verifier.verify(self.user_id, ticket_id)

    def test_intake_content_is_stored_in_the_database(self) -> None:
        pdf = _minimal_pdf()
        first = self.client.post(
            "/tickets/inputs",
            json={"email": "first notes", "context": "# project"},
            headers=CSRF,
        )
        self.assertEqual(first.status_code, 204)
        second = self.client.post(
            "/tickets/inputs",
            json={"list_pdf_base64": base64.b64encode(pdf).decode("ascii")},
            headers=CSRF,
        )
        self.assertEqual(second.status_code, 204)
        self.assertEqual(intakes.active_content(self.user_id, "ticket_list"), ("pdf", pdf))
        self.assertIsNone(intakes.active_content(self.user_id, "email_desc"))
        self.assertEqual(parser.intake_text(self.user_id, "ticket_list"), "T9 export hangs")

    def test_replacing_list_deactivates_previous_intake(self) -> None:
        for body in (
            {"email": "first notes", "list_text": "T1 login fails"},
            {"email": "second notes", "list_text": "T2 export hangs"},
        ):
            self.assertEqual(self.client.post("/tickets/inputs", json=body, headers=CSRF).status_code, 204)
        with db.get_pool().connection() as conn:
            rows = conn.execute(
                "SELECT type, format, status FROM intakes WHERE user_id = %s ORDER BY created_at, type",
                (self.user_id,),
            ).fetchall()
        self.assertEqual(
            [(str(row["type"]), str(row["format"]), str(row["status"])) for row in rows],
            [
                ("email_desc", "txt", "deactivated"),
                ("ticket_list", "txt", "deactivated"),
                ("email_desc", "txt", "active"),
                ("ticket_list", "txt", "active"),
            ],
        )
        self.assertEqual(parser.intake_text(self.user_id, "ticket_list"), "T2 export hangs")

    def test_sync_tickets_stores_user_and_session(self) -> None:
        self.client.post("/tickets/inputs", json={"list_text": "T1 login fails"}, headers=CSRF)
        with db.get_pool().connection() as conn:
            session = conn.execute(
                "SELECT id FROM sessions WHERE user_id = %s AND revoked_at IS NULL",
                (self.user_id,),
            ).fetchone()
        intakes.sync_tickets(self.user_id, session["id"], [_ticket("T1")])
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

    def test_parser_reads_intakes_and_saves_tickets(self) -> None:
        self.client.post(
            "/tickets/inputs",
            json={"email": "login is broken", "list_text": "T1 login fails", "context": "# product"},
            headers=CSRF,
        )
        reply = json.dumps([_ticket("T1")])
        with (
            patch.object(parser.ollama, "summarize", side_effect=lambda text: text),
            patch.object(parser.bedrock, "complete", return_value=reply) as complete,
        ):
            tickets = parser.get_tickets(self.user_id, None)
        prompt = complete.call_args.args[0]
        self.assertIn("login is broken", prompt)
        self.assertIn("T1 login fails", prompt)
        self.assertIn("# product", prompt)
        self.assertEqual([item["id"] for item in tickets], ["T1"])
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "unresolved")

    def test_parser_rejects_a_reply_that_is_not_json(self) -> None:
        self.client.post("/tickets/inputs", json={"email": "login is broken"}, headers=CSRF)
        with patch.object(parser.bedrock, "complete", return_value="I found one defect."):
            with self.assertRaisesRegex(RuntimeError, "did not return JSON"):
                parser.get_tickets(self.user_id, None)
            answer = self.client.post("/tickets/parse", headers=CSRF)
        self.assertEqual(answer.status_code, 400)

    def test_verifier_reviews_the_solver_report(self) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        replies = [
            SimpleNamespace(id="s1", result="CHANGED FILES:\napi/login.py\nVERDICT: ready"),
            SimpleNamespace(id="v1", result="checked\nVERDICT: failed"),
        ]
        with patch("llm.cursor.run", side_effect=replies), patch("verifier.push_ticket") as push:
            solver.solve(self.user_id, "T1")
            verifier.verify(self.user_id, "T1")
        verify_prompt = intakes.latest_run(self.user_id, "T1", "verify")["prompt"]
        self.assertIn("SOLVER REPORT\nCHANGED FILES:\napi/login.py\nVERDICT: ready", verify_prompt)
        push.assert_not_called()

    def test_verifier_rechecks_then_pushes_when_it_edited(self) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        replies = [
            SimpleNamespace(id="s1", result="CHANGED FILES:\napi/login.py\nVERDICT: ready"),
            SimpleNamespace(
                id="v1",
                result="fixed a bug\nCHANGED FILES:\napi/login.py\napi/auth.py\nVERDICT: fixed",
            ),
            SimpleNamespace(id="v2", result="still good\nCHANGED FILES:\napi/login.py\napi/auth.py\nVERDICT: fixed"),
        ]
        with patch("llm.cursor.run", side_effect=replies) as run, patch("verifier.push_ticket") as push:
            solver.solve(self.user_id, "T1")
            verifier.verify(self.user_id, "T1")
        self.assertEqual(run.call_count, 3)
        self.assertIn("Do not edit any file", run.call_args_list[2].args[0])
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "fixed")
        push.assert_called_once()

    def test_a_failed_push_leaves_the_ticket_verifying(self) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        replies = [
            SimpleNamespace(id="s1", result="CHANGED FILES:\napi/login.py\nVERDICT: ready"),
            SimpleNamespace(id="v1", result="ok\nCHANGED FILES:\napi/login.py\nVERDICT: fixed"),
        ]
        with patch("llm.cursor.run", side_effect=replies), patch(
            "verifier.push_ticket", side_effect=RuntimeError("push rejected")
        ):
            with self.assertRaisesRegex(RuntimeError, "push rejected"):
                solver.solve(self.user_id, "T1")
                verifier.verify(self.user_id, "T1")
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "verifying")

    def test_verifier_pushes_without_a_recheck_when_files_match(self) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        replies = [
            SimpleNamespace(id="s1", result="CHANGED FILES:\napi/login.py\nVERDICT: ready"),
            SimpleNamespace(id="v1", result="ok\nCHANGED FILES:\napi/login.py\nVERDICT: fixed"),
        ]
        with patch("llm.cursor.run", side_effect=replies) as run, patch("verifier.push_ticket") as push:
            solver.solve(self.user_id, "T1")
            verifier.verify(self.user_id, "T1")
        self.assertEqual(run.call_count, 2)
        push.assert_called_once()

    def test_execute_runs_the_steps_for_one_user(self) -> None:
        with (
            patch.object(orchestrator.parser, "get_tickets") as parse,
            patch.object(orchestrator.solver, "solve_tickets") as solve,
            patch.object(orchestrator.verifier, "verify_tickets") as verify,
        ):
            orchestrator.execute(self.user_id, None)
        parse.assert_called_once_with(self.user_id, None)
        solve.assert_called_once_with(self.user_id)
        verify.assert_called_once_with(self.user_id)

    def test_execute_retries_verify_until_fixed(self) -> None:
        self._tier("paid")
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        replies = [
            SimpleNamespace(id="s1", result="CHANGED FILES:\napi/a.py\nVERDICT: ready"),
            SimpleNamespace(id="v1", result="broken\nVERDICT: failed"),
            SimpleNamespace(id="s2", result="CHANGED FILES:\napi/a.py\nVERDICT: ready"),
            SimpleNamespace(id="v2", result="still broken\nVERDICT: failed"),
            SimpleNamespace(id="s3", result="CHANGED FILES:\napi/a.py\nVERDICT: ready"),
            SimpleNamespace(id="v3", result="CHANGED FILES:\napi/a.py\nVERDICT: fixed"),
        ]
        with (
            patch.object(orchestrator.parser, "get_tickets"),
            patch("llm.cursor.run", side_effect=replies) as run,
            patch("verifier.push_ticket") as push,
        ):
            orchestrator.execute(self.user_id, None)
        self.assertEqual(run.call_count, 6)
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "fixed")
        push.assert_called_once()
        retry_prompt = intakes.latest_run(self.user_id, "T1", "solve")["prompt"]
        self.assertIn("PREVIOUS ATTEMPT", retry_prompt)
        self.assertIn("still broken", retry_prompt)

    def test_execute_stops_when_retry_solve_is_blocked(self) -> None:
        self._tier("paid")
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        replies = [
            SimpleNamespace(id="s1", result="notes\nVERDICT: ready"),
            SimpleNamespace(id="v1", result="missing tests\nVERDICT: failed"),
            SimpleNamespace(id="s2", result="cannot patch\nVERDICT: blocked"),
        ]
        with (
            patch.object(orchestrator.parser, "get_tickets"),
            patch("llm.cursor.run", side_effect=replies) as run,
        ):
            orchestrator.execute(self.user_id, None)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "unresolved")
        retry_prompt = intakes.latest_run(self.user_id, "T1", "solve")["prompt"]
        self.assertIn("PREVIOUS ATTEMPT", retry_prompt)
        self.assertIn("missing tests", retry_prompt)

    def test_execute_stops_at_max_solve_attempts(self) -> None:
        self._tier("paid")
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        replies = [
            SimpleNamespace(id="s{0}".format(index), result="notes\nVERDICT: ready")
            if index % 2 == 1
            else SimpleNamespace(id="v{0}".format(index), result="broken\nVERDICT: failed")
            for index in range(1, 2 * orchestrator.MAX_SOLVE_ATTEMPTS + 3)
        ]
        with (
            patch.object(orchestrator.parser, "get_tickets"),
            patch("llm.cursor.run", side_effect=replies) as run,
        ):
            orchestrator.execute(self.user_id, None)
        self.assertEqual(run.call_count, 2 * orchestrator.MAX_SOLVE_ATTEMPTS)
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "unresolved")

    def test_run_log_is_stored_and_served(self) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        with patch("llm.cursor.run", return_value=SimpleNamespace(id="run-1", result="notes\nVERDICT: ready")):
            solver.solve(self.user_id, "T1")
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "verifying")
        self.assertEqual(intakes.latest_run_id(self.user_id, "T1"), "run-1")
        response = self.client.get("/tickets/T1/runs/run-1")
        self.assertEqual(response.status_code, 200)
        text = response.json()["text"]
        self.assertIn("- verdict: ready", text)
        self.assertIn("- run: run-1", text)
        self.assertIn("## Result\nnotes\nVERDICT: ready", text)

    def test_tickets_and_runs_are_private_to_their_user(self) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        with patch("llm.cursor.run", return_value=SimpleNamespace(id="run-1", result="VERDICT: ready")):
            solver.solve(self.user_id, "T1")
        other = UUID(int=1)
        self.assertIsNone(intakes.find_ticket(other, "T1"))
        self.assertIsNone(intakes.get_run(other, "T1", "run-1"))
        self.assertEqual(intakes.open_tickets(other), [])

    def test_free_tier_hides_a_handled_ticket_immediately(self) -> None:
        with patch("verifier.push_ticket"):
            self._solve_and_verify("T1", "fixed")
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "fixed")
        self.assertEqual(intakes.list_visible_tickets(self.user_id), [])
        with db.get_pool().connection() as conn:
            runs = conn.execute("SELECT count(*) AS n FROM ticket_runs").fetchone()["n"]
        self.assertEqual(runs, 2)

    def test_free_tier_keeps_a_ticket_that_failed_verification(self) -> None:
        self._solve_and_verify("T1", "failed")
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "unresolved")
        self.assertEqual(intakes.list_visible_tickets(self.user_id)[0]["id"], "T1")

    def test_complete_keeps_the_ticket_and_hides_it_on_free(self) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket("T1", "verifying")])
        completed = self.client.post("/tickets/T1/complete", headers=CSRF)
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["status"], "completed")
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "completed")
        self.assertEqual(self.client.get("/tickets").json(), [])

    def test_trial_shows_handled_tickets_for_seven_days(self) -> None:
        self._tier("trial")
        with patch("verifier.push_ticket"):
            self._solve_and_verify("T1", "fixed")
        self.assertEqual(intakes.keep_days(self.user_id), 7)
        self.assertEqual(intakes.list_visible_tickets(self.user_id)[0]["status"], "fixed")
        self._age_handled("T1", 6)
        self.assertEqual(len(intakes.list_visible_tickets(self.user_id)), 1)
        self._age_handled("T1", 8)
        self.assertEqual(intakes.list_visible_tickets(self.user_id), [])
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "fixed")

    def test_paid_shows_handled_tickets_for_ninety_days_by_default(self) -> None:
        self._tier("paid")
        with patch("verifier.push_ticket"):
            self._solve_and_verify("T1", "fixed")
        self.assertEqual(intakes.keep_days(self.user_id), 90)
        self._age_handled("T1", 89)
        self.assertEqual(len(intakes.list_visible_tickets(self.user_id)), 1)
        self._age_handled("T1", 91)
        self.assertEqual(intakes.list_visible_tickets(self.user_id), [])
        self.assertIsNotNone(intakes.find_ticket(self.user_id, "T1"))

    def test_paid_user_can_show_tickets_forever(self) -> None:
        self._tier("paid")
        intakes.set_keep_days(self.user_id, None)
        self.assertIsNone(intakes.keep_days(self.user_id))
        with patch("verifier.push_ticket"):
            self._solve_and_verify("T1", "fixed")
        self._age_handled("T1", 3650)
        self.assertEqual(intakes.list_visible_tickets(self.user_id)[0]["id"], "T1")

    def test_paid_user_shortening_days_hides_now(self) -> None:
        self._tier("paid")
        with patch("verifier.push_ticket"):
            self._solve_and_verify("T1", "fixed")
        self._age_handled("T1", 40)
        response = self.client.put("/settings", json={"ticket_retention_days": 30}, headers=CSRF)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ticket_retention_days"], 30)
        self.assertEqual(intakes.list_visible_tickets(self.user_id), [])
        self.assertIsNotNone(intakes.find_ticket(self.user_id, "T1"))

    def test_settings_by_tier(self) -> None:
        free = self.client.get("/settings").json()
        self.assertEqual(free, {"subscription_status": "free", "ticket_retention_days": 0, "editable": False})
        self._tier("trial")
        self.assertEqual(self.client.get("/settings").json()["ticket_retention_days"], 7)
        self._tier("paid")
        paid = self.client.get("/settings").json()
        self.assertEqual(paid, {"subscription_status": "paid", "ticket_retention_days": 90, "editable": True})

    def test_open_tickets_are_never_purged(self) -> None:
        self._tier("trial")
        intakes.sync_tickets(self.user_id, None, [_ticket("T1"), _ticket("T2", "verifying")])
        intakes.purge_handled()
        self.assertEqual([item["id"] for item in intakes.open_tickets(self.user_id)], ["T1", "T2"])

    def test_replaced_intake_is_purged_once_no_ticket_uses_it(self) -> None:
        self.client.post("/tickets/inputs", json={"list_text": "T1 login fails"}, headers=CSRF)
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        self.client.post("/tickets/inputs", json={"list_text": "T2 export hangs"}, headers=CSRF)
        intakes.purge_handled()
        with db.get_pool().connection() as conn:
            statuses = [row["status"] for row in conn.execute("SELECT status FROM intakes ORDER BY created_at").fetchall()]
        self.assertEqual(statuses, ["deactivated", "active"])
        intakes.sync_tickets(self.user_id, None, [_ticket("T2")])
        intakes.purge_handled()
        with db.get_pool().connection() as conn:
            statuses = [row["status"] for row in conn.execute("SELECT status FROM intakes ORDER BY created_at").fetchall()]
        self.assertEqual(statuses, ["active"])

    def test_migrating_again_keeps_existing_data(self) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        self.client.post("/tickets/inputs", json={"list_text": "T1 login fails"}, headers=CSRF)
        with psycopg.connect(db.database_url(), row_factory=dict_row) as owner:
            db.migrate(owner)
        self.assertIsNotNone(intakes.find_ticket(self.user_id, "T1"))
        self.assertEqual(parser.intake_text(self.user_id, "ticket_list"), "T1 login fails")

    def test_migrating_backfills_handled_at_on_old_handled_tickets(self) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket("T1", "fixed")])
        with db.get_pool().connection() as conn:
            conn.execute(
                """
                UPDATE tickets
                SET handled_at = NULL, updated_at = now() - interval '10 days'
                WHERE user_id = %s AND public_id = 'T1'
                """,
                (self.user_id,),
            )
            conn.commit()
        with psycopg.connect(db.database_url(), row_factory=dict_row) as owner:
            db.migrate(owner)
        with db.get_pool().connection() as conn:
            row = conn.execute(
                "SELECT handled_at = updated_at AS backfilled FROM tickets WHERE user_id = %s",
                (self.user_id,),
            ).fetchone()
        self.assertTrue(row["backfilled"])

    def test_job_runs_through_the_api(self) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        with patch("llm.cursor.run", return_value=SimpleNamespace(id="run-1", result="VERDICT: ready")):
            started = self.client.post("/tickets/T1/solve", headers=CSRF)
        self.assertEqual(started.status_code, 202)
        job = self.client.get("/jobs/{0}".format(started.json()["id"])).json()
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["run_id"], "run-1")
        self.assertIsNotNone(config.load_job(self.user_id, job["id"]))
