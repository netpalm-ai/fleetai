"""One instruction becomes tickets, a fix, tests, and a merge of fleetai/dev into main."""

from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import selflooper


class SelfLooperTests(unittest.TestCase):
    def test_resolves_open_tickets_and_closes_fixed(self) -> None:
        user_id = uuid4()
        project_id = uuid4()
        context = "\n".join(selflooper._REQUIRED) + "\n"
        closed: list[tuple] = []

        @contextmanager
        def checkout(owner, project):
            self.assertEqual((owner, project), (user_id, project_id))
            yield

        def execute(owner, session_id, ticket_ids):
            self.assertEqual(owner, user_id)
            self.assertIsNone(session_id)
            self.assertEqual(ticket_ids, ["T1", "T2"])

        def find(owner, ticket_id):
            status = "fixed" if ticket_id == "T1" else "unresolved"
            return {"id": ticket_id, "status": status}

        def mark(owner, ticket_id, status):
            closed.append((owner, ticket_id, status))

        with TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "fleetai" / ".git").mkdir(parents=True)
            with (
                patch.object(selflooper.db, "open_pool"),
                patch.object(selflooper, "_probe_health", return_value="ok"),
                patch.object(selflooper, "finish_pushing_runs"),
                patch.object(selflooper, "fleetai_project", return_value={"id": project_id, "user_id": user_id}),
                patch.object(selflooper, "open_ticket_ids", return_value=["T1", "T2"]),
                patch.object(selflooper, "ensure_code_context", return_value=context),
                patch.object(selflooper.connections.github, "checkout_for", checkout),
                patch.object(selflooper, "product_cwd", return_value=root),
                patch.object(selflooper.orchestrator, "execute", side_effect=execute),
                patch.object(selflooper.intakes, "find_ticket", side_effect=find),
                patch.object(selflooper.intakes, "set_ticket_status", side_effect=mark),
            ):
                selflooper.main()
        self.assertEqual(closed, [(user_id, "T1", "completed")])

    def test_instruction_is_analyzed_tested_and_merged(self) -> None:
        user_id = uuid4()
        project_id = uuid4()
        context = "\n".join(selflooper._REQUIRED) + "\n"
        saved: list[dict] = []
        order: list[str] = []

        @contextmanager
        def checkout(owner, project):
            yield

        def execute(owner, session_id, ticket_ids):
            order.append("dev")
            self.assertEqual(ticket_ids, ["copy-home"])

        def save(owner, project, tickets):
            saved.extend(tickets)

        def tests(clone):
            order.append("test")

        def publish(clone, instruction):
            order.append("publish")
            self.assertIn("industrial", instruction)

        payload = json.dumps(
            [
                {
                    "id": "copy-home",
                    "title": "Home copy",
                    "severity": "low",
                    "services": ["tickets page"],
                    "context": "frontend/src/pages/HomePage.tsx uses odd wording",
                    "expected": "The home page uses ordinary product copy",
                }
            ]
        )
        with TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "fleetai" / ".git").mkdir(parents=True)
            with (
                patch.object(selflooper, "ensure_code_context", return_value=context),
                patch.object(selflooper, "existing_ids", return_value=["T1"]),
                patch.object(selflooper, "run_memory", return_value="(none)"),
                patch.object(selflooper, "begin_push_run"),
                patch.object(selflooper, "finish_pushing_runs"),
                patch.object(selflooper, "_status", return_value=""),
                patch.object(selflooper.connections.github, "checkout_for", checkout),
                patch.object(selflooper, "product_cwd", return_value=root),
                patch.object(selflooper, "analyze", return_value=payload),
                patch.object(selflooper, "save_tickets", side_effect=save),
                patch.object(selflooper.orchestrator, "execute", side_effect=execute),
                patch.object(selflooper.intakes, "find_ticket", return_value={"id": "copy-home", "status": "fixed"}),
                patch.object(selflooper, "run_tests", side_effect=tests),
                patch.object(selflooper, "publish", side_effect=publish),
                patch.object(selflooper.intakes, "set_ticket_status") as mark,
            ):
                selflooper.run_instruction(user_id, project_id, "review each FE page for industrial standard")
        self.assertEqual([item["id"] for item in saved], ["copy-home"])
        self.assertEqual(order, ["dev", "test", "publish"])
        mark.assert_called_once_with(user_id, "copy-home", "completed")

    def test_unfixed_instruction_is_not_published(self) -> None:
        user_id = uuid4()
        project_id = uuid4()
        context = "\n".join(selflooper._REQUIRED) + "\n"
        payload = json.dumps(
            [
                {
                    "id": "copy-home",
                    "title": "Home copy",
                    "severity": "low",
                    "services": [],
                    "context": "odd wording",
                    "expected": "ordinary copy",
                }
            ]
        )
        with TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "fleetai" / ".git").mkdir(parents=True)
            with (
                patch.object(selflooper, "ensure_code_context", return_value=context),
                patch.object(selflooper, "existing_ids", return_value=[]),
                patch.object(selflooper, "run_memory", return_value="(none)"),
                patch.object(selflooper, "_status", return_value=""),
                patch.object(selflooper.connections.github, "checkout_for", lambda *args: _quiet()),
                patch.object(selflooper, "product_cwd", return_value=root),
                patch.object(selflooper, "analyze", return_value=payload),
                patch.object(selflooper, "save_tickets"),
                patch.object(selflooper.orchestrator, "execute"),
                patch.object(selflooper.intakes, "find_ticket", return_value={"id": "copy-home", "status": "unresolved"}),
                patch.object(selflooper, "publish") as publish,
            ):
                with self.assertRaises(RuntimeError) as raised:
                    selflooper.run_instruction(user_id, project_id, "review the home page")
        self.assertIn("not fixed", str(raised.exception))
        publish.assert_not_called()

    def test_frontend_and_backend_commands(self) -> None:
        commands = selflooper.test_commands(
            ["frontend/src/pages/HomePage.tsx", "backend/solver.py"],
            "postgresql://fleetai:test@127.0.0.1:5432/fleetai",
        )
        self.assertEqual(commands[0][1][:2], ["npm", "ci"])
        self.assertEqual(commands[1][1][:3], ["npm", "run", "build"])
        self.assertIn("tests/test_workflow.py", commands[2][1])

    def test_backend_tests_refuse_the_live_database(self) -> None:
        with self.assertRaises(RuntimeError) as raised:
            selflooper.test_commands(
                ["backend/solver.py"],
                "postgresql://fleetai:secret@postgres:5432/fleetai",
            )
        self.assertEqual(str(raised.exception), "tests need a disposable database")

    def test_publish_merges_dev_into_main(self) -> None:
        calls: list[tuple] = []

        def fake(cwd, token, *args):
            calls.append(args)
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return "fleetai/dev\n"
            if args[:1] == ("status",):
                return " M frontend/src/pages/HomePage.tsx\n"
            return ""

        with patch.object(selflooper.connections.github, "git", side_effect=fake), patch.object(
            selflooper, "active_checkout", return_value=SimpleNamespace(token=None)
        ):
            selflooper.publish(Path("/tmp/fleetai"), "review each FE page")
        self.assertEqual(
            [args[0] for args in calls if args[0] in {"config", "commit", "push", "merge", "checkout", "fetch"}],
            ["config", "config", "commit", "push", "fetch", "checkout", "merge", "push", "checkout"],
        )
        self.assertEqual(calls[2], ("config", "user.email", "fleetai@netpalm.ai"))
        self.assertEqual(calls[3], ("config", "user.name", "FleetAI"))
        self.assertEqual(calls[4], ("add", "-A"))
        self.assertEqual(calls[5], ("commit", "-m", "fleetai: review each FE page"))
        self.assertEqual(calls[6], ("push", "origin", "HEAD:fleetai/dev"))
        self.assertEqual(calls[8], ("checkout", "-B", "main", "origin/main"))
        self.assertEqual(calls[9], ("merge", "--no-edit", "fleetai/dev"))
        self.assertEqual(calls[10], ("push", "origin", "HEAD:main"))
        self.assertEqual(calls[11], ("checkout", "fleetai/dev"))


@contextmanager
def _quiet():
    yield
