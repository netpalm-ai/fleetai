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
import selflooper
import solver
import verifier
from auth.sessions import COOKIE_NAME
from tests.signing import register_verify_login

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
        self.user_id = register_verify_login(
            self.client, email=EMAIL, password=PASSWORD, username="ada"
        )
        self.assertIn(COOKIE_NAME, self.client.cookies)
        with db.get_pool().connection() as conn:
            project_id = conn.execute(
                "INSERT INTO projects (user_id, name) VALUES (%s, 'acme') RETURNING id",
                (self.user_id,),
            ).fetchone()["id"]
            conn.execute(
                """
                INSERT INTO github_connections (user_id, github_login, access_token, project_name, project_id)
                VALUES (%s, 'octocat', 'token', 'acme', %s)
                """,
                (self.user_id, project_id),
            )
            conn.execute(
                """
                INSERT INTO project_contexts (project_id, user_id, org, product_name, codebase_context, tech_stack)
                VALUES (%s, %s, 'acme', 'FleetAI', %s, 'python, postgres')
                """,
                (
                    project_id,
                    self.user_id,
                    "# Product\n\n## Repositories\n\n| app | . | local | demo |\n\n## Tech stack\n\npython, postgres\n",
                ),
            )
            conn.commit()

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
        ready = SimpleNamespace(id="run-solve", result="notes\nVERDICT: ready")
        done = SimpleNamespace(id="run-verify", result="checked\nVERDICT: {0}".format(final))
        with patch("llm.cursor.run", side_effect=[ready, done]):
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

    def test_execute_resolves_only_the_selected_tickets(self) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket("T1"), _ticket("T2")])
        intakes.set_ticket_status(self.user_id, "T2", "verifying")
        with (
            patch.object(orchestrator.parser, "get_tickets") as parse,
            patch.object(orchestrator.solver, "solve") as solve,
            patch.object(orchestrator.verifier, "verify") as verify,
        ):
            orchestrator.execute(self.user_id, None, ["T1"])
        parse.assert_not_called()
        solve.assert_called_once_with(self.user_id, "T1")
        verify.assert_not_called()
        self.assertEqual(intakes.find_ticket(self.user_id, "T2")["status"], "verifying")

    def test_execute_retries_verify_until_fixed(self) -> None:
        self._tier("paid")
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        replies = [
            SimpleNamespace(id="s1", result="notes\nVERDICT: ready"),
            SimpleNamespace(id="v1", result="broken\nVERDICT: failed"),
            SimpleNamespace(id="s2", result="retry\nVERDICT: ready"),
            SimpleNamespace(id="v2", result="still broken\nVERDICT: failed"),
            SimpleNamespace(id="s3", result="again\nVERDICT: ready"),
            SimpleNamespace(id="v3", result="ok\nVERDICT: fixed"),
        ]
        with (
            patch.object(orchestrator.parser, "get_tickets"),
            patch("llm.cursor.run", side_effect=replies) as run,
        ):
            orchestrator.execute(self.user_id, None)
        self.assertEqual(run.call_count, 6)
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "fixed")
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

    def test_free_tier_keeps_a_handled_ticket_for_one_minute(self) -> None:
        self._solve_and_verify("T1", "fixed")
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "fixed")
        with db.get_pool().connection() as conn:
            conn.execute(
                """
                UPDATE tickets
                SET handled_at = now() - interval '2 minutes'
                WHERE user_id = %s AND public_id = 'T1'
                """,
                (self.user_id,),
            )
            conn.commit()
        intakes.purge_handled()
        self.assertIsNone(intakes.find_ticket(self.user_id, "T1"))
        with db.get_pool().connection() as conn:
            runs = conn.execute("SELECT count(*) AS n FROM ticket_runs").fetchone()["n"]
        self.assertEqual(runs, 0)

    def test_free_tier_keeps_a_ticket_that_failed_verification(self) -> None:
        self._solve_and_verify("T1", "failed")
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "unresolved")

    def test_complete_returns_the_ticket_even_when_it_is_deleted(self) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket("T1", "verifying")])
        completed = self.client.post("/tickets/T1/complete", headers=CSRF)
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["status"], "completed")
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "completed")
        with db.get_pool().connection() as conn:
            conn.execute(
                """
                UPDATE tickets
                SET handled_at = now() - interval '2 minutes'
                WHERE user_id = %s AND public_id = 'T1'
                """,
                (self.user_id,),
            )
            conn.commit()
        intakes.purge_handled()
        self.assertIsNone(intakes.find_ticket(self.user_id, "T1"))

    def test_trial_keeps_handled_tickets_for_seven_days(self) -> None:
        self._tier("trial")
        self._solve_and_verify("T1", "fixed")
        self.assertEqual(intakes.keep_days(self.user_id), 7)
        self.assertEqual(intakes.find_ticket(self.user_id, "T1")["status"], "fixed")
        self._age_handled("T1", 6)
        intakes.purge_handled()
        self.assertIsNotNone(intakes.find_ticket(self.user_id, "T1"))
        self._age_handled("T1", 8)
        intakes.purge_handled()
        self.assertIsNone(intakes.find_ticket(self.user_id, "T1"))

    def test_paid_keeps_handled_tickets_for_ninety_days_by_default(self) -> None:
        self._tier("paid")
        self._solve_and_verify("T1", "fixed")
        self.assertEqual(intakes.keep_days(self.user_id), 90)
        self._age_handled("T1", 89)
        intakes.purge_handled()
        self.assertIsNotNone(intakes.find_ticket(self.user_id, "T1"))
        self._age_handled("T1", 91)
        intakes.purge_handled()
        self.assertIsNone(intakes.find_ticket(self.user_id, "T1"))

    def test_paid_user_can_keep_tickets_forever(self) -> None:
        self._tier("paid")
        intakes.set_keep_days(self.user_id, None)
        self.assertIsNone(intakes.keep_days(self.user_id))
        self._solve_and_verify("T1", "fixed")
        self._age_handled("T1", 3650)
        intakes.purge_handled()
        self.assertIsNotNone(intakes.find_ticket(self.user_id, "T1"))

    def test_paid_user_shortening_days_purges_now(self) -> None:
        self._tier("paid")
        self._solve_and_verify("T1", "fixed")
        self._age_handled("T1", 40)
        response = self.client.put("/settings", json={"ticket_retention_days": 30}, headers=CSRF)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ticket_retention_days"], 30)
        self.assertIsNone(intakes.find_ticket(self.user_id, "T1"))

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

    def test_deploy_run_survives_and_blocks_the_next_one(self) -> None:
        with db.get_pool().connection() as conn:
            project_id = conn.execute(
                "SELECT id FROM projects WHERE user_id = %s AND name = 'acme'",
                (self.user_id,),
            ).fetchone()["id"]
            conn.execute(
                """
                INSERT INTO deploy_runs (project_id, instruction, users_before, outcome)
                VALUES (%s, 'remember the deploy', 100000, 'pushing')
                """,
                (project_id,),
            )
            conn.commit()
        selflooper.finish_pushing_runs("ok")
        with db.get_pool().connection() as conn:
            row = conn.execute(
                "SELECT outcome, users_after, health FROM deploy_runs WHERE project_id = %s",
                (project_id,),
            ).fetchone()
        self.assertEqual(row["outcome"], "failed")
        self.assertEqual(row["health"], "ok")
        self.assertGreaterEqual(row["users_after"], 1)
        with self.assertRaises(RuntimeError):
            selflooper.refuse_failed_run(project_id, health="ok")
        with db.get_pool().connection() as conn:
            conn.execute("DELETE FROM tickets WHERE user_id = %s", (self.user_id,))
            conn.commit()
            kept = conn.execute("SELECT count(*) AS n FROM deploy_runs").fetchone()["n"]
        self.assertEqual(kept, 1)

    def test_job_runs_through_the_api(self) -> None:
        intakes.sync_tickets(self.user_id, None, [_ticket("T1")])
        with (
            patch("connections.github.prepare", return_value=None),
            patch("llm.cursor.run", return_value=SimpleNamespace(id="run-1", result="VERDICT: ready")),
        ):
            started = self.client.post("/tickets/T1/solve", headers=CSRF)
        self.assertEqual(started.status_code, 202)
        job = self.client.get("/jobs/{0}".format(started.json()["id"])).json()
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["run_id"], "run-1")
        self.assertIsNotNone(config.load_job(self.user_id, job["id"]))

    def test_minh_sees_a_different_list_for_each_project(self) -> None:
        register_verify_login(
            self.client,
            email="Minh@netpalm.ai",
            password=PASSWORD,
            username="minh",
            first_name="Minh",
            last_name="Netpalm",
        )
        with db.get_pool().connection() as conn:
            db._seed_minh_projects(conn)
            conn.commit()
        listed = self.client.get("/projects")
        self.assertEqual(listed.status_code, 200, listed.text)
        by_name = {row["name"]: row for row in listed.json()}
        self.assertEqual(sorted(by_name), ["FleetAI", "JarvisMD"])
        self.assertEqual(by_name["JarvisMD"]["org"], "HBA")
        self.assertEqual(by_name["FleetAI"]["org"], "Netpalm.AI")
        jarvis = self.client.get("/tickets", params={"project_id": by_name["JarvisMD"]["id"]})
        fleet = self.client.get("/tickets", params={"project_id": by_name["FleetAI"]["id"]})
        self.assertEqual(jarvis.status_code, 200, jarvis.text)
        self.assertEqual(fleet.status_code, 200, fleet.text)
        self.assertEqual([row["id"] for row in jarvis.json()], ["J1", "J2", "J3", "J4"])
        self.assertEqual([row["id"] for row in fleet.json()], ["T1", "T2", "T3", "T4", "T5", "T6", "T7"])
        self.assertEqual(jarvis.json()[0]["title"], "Annotated text missing while live text is present")
        self.assertEqual(fleet.json()[0]["title"], "The form takes the page")

    def test_a_ticket_cannot_use_another_users_project(self) -> None:
        other = register_verify_login(
            self.client,
            email="other@example.com",
            password=PASSWORD,
            username="other",
        )
        with db.get_pool().connection() as conn:
            project_id = conn.execute(
                "SELECT id FROM projects WHERE user_id = %s",
                (self.user_id,),
            ).fetchone()["id"]
            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                conn.execute(
                    """
                    INSERT INTO tickets (public_id, user_id, project_id, title, status)
                    VALUES ('X1', %s, %s, 'nope', 'unresolved')
                    """,
                    (other, project_id),
                )
            conn.rollback()
