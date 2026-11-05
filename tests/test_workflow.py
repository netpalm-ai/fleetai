"""Workflow helpers: parse merge, verdicts, complete, run logs."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import solver
import verifier
from config import (
    BLOCKED,
    COMPLETED,
    FAILED,
    FIXED,
    READY,
    UNRESOLVED,
    VERIFYING,
    apply_workflow,
    archive_solved,
    last_verdict,
    load_tickets,
    normalize_ticket,
    product_areas,
    save_tickets,
    tech_ticket,
    write_run_log,
)


def _ticket(ticket_id: str, status: str, **extra: object) -> dict:
    item = {
        "id": ticket_id,
        "title": extra.pop("title", "title"),
        "severity": "P1",
        "kind": "new",
        "kind_reason": "reason",
        "services": extra.pop("services", ["frontend"]),
        "context": extra.pop("context", "context"),
        "expected": extra.pop("expected", "expected"),
        "status": status,
        "repos": extra.pop("repos", [{"name": "fe"}]),
        "report_status": extra.pop("report_status", "Open"),
    }
    item.update(extra)
    return item


class NormalizeTests(unittest.TestCase):
    def test_slugs_id_from_title_when_missing(self) -> None:
        item = {
            "title": "Login button is broken",
            "severity": "P2",
            "services": ["frontend"],
            "context": "the login button does nothing",
            "expected": "login submits",
        }
        ticket = normalize_ticket(item)
        self.assertEqual(ticket["id"], "Login_button_is_broken")
        self.assertEqual(ticket["kind"], "new")
        self.assertEqual(ticket["status"], UNRESOLVED)


class ProductAreasTests(unittest.TestCase):
    def test_parser_map_is_repositories_only(self) -> None:
        text = product_areas()
        self.assertIn("## Repositories", text)
        self.assertNotIn("## Work rules for the solver", text)
        self.assertNotIn("staging-uk-jmd-xycare-cicd", text)


class TechTicketTests(unittest.TestCase):
    def test_solver_sees_defect_fields_only(self) -> None:
        ticket = _ticket("T1", UNRESOLVED, report_status="Partially Fixed", solver_run_id="run-1")
        out = tech_ticket(ticket)
        self.assertEqual(set(out), {"id", "title", "severity", "services", "context", "expected"})
        prompt = solver.ticket_prompt(ticket, "map")
        self.assertNotIn("Partially Fixed", prompt)
        self.assertNotIn("kind_reason", prompt)
        self.assertNotIn("run-1", prompt)
        self.assertIn("Do not invent requirements", prompt)


class VerifierPromptTests(unittest.TestCase):
    def test_verifier_repairs_introduced_bugs_before_fixed(self) -> None:
        ticket = _ticket("T1", VERIFYING)
        prompt = verifier.verify_prompt(ticket, "map")
        self.assertNotIn("Do not implement", prompt)
        self.assertIn("If the change introduced a bug, fix that bug and re-check", prompt)
        self.assertIn("Also refine the solver diff", prompt)
        self.assertIn("reuse existing functions", prompt)
        self.assertIn("Other than that, you must fix", prompt)
        self.assertIn("Do not mark it resolved while a new bug or that extra complexity is still in the tree", prompt)
        self.assertIn("VERDICT: fixed", prompt)
        self.assertIn("VERDICT: failed", prompt)


class LastVerdictTests(unittest.TestCase):
    def test_reads_last_matching_line(self) -> None:
        self.assertEqual(last_verdict("notes\nVERDICT: ready"), READY)
        self.assertEqual(last_verdict("**VERDICT: blocked**"), BLOCKED)
        self.assertEqual(last_verdict("`VERDICT: fixed`"), FIXED)
        self.assertEqual(last_verdict("VERDICT: failed"), FAILED)
        self.assertIsNone(last_verdict("no verdict here"))
        self.assertIsNone(last_verdict(None))


class ApplyWorkflowTests(unittest.TestCase):
    def test_keeps_in_flight_body_and_updates_report_status(self) -> None:
        prior = _ticket("T1", FIXED, title="old", solver_run_id="run-1")
        incoming = _ticket(
            "T1",
            UNRESOLVED,
            title="rewritten",
            repos=[],
            report_status="Partially Fixed",
        )
        out = apply_workflow([incoming], [prior])
        self.assertEqual(out[0]["title"], "old")
        self.assertEqual(out[0]["status"], FIXED)
        self.assertEqual(out[0]["repos"], [{"name": "fe"}])
        self.assertEqual(out[0]["solver_run_id"], "run-1")
        self.assertEqual(out[0]["report_status"], "Partially Fixed")

    def test_keeps_omitted_in_flight_ticket(self) -> None:
        prior = _ticket("T1", VERIFYING)
        self.assertEqual(apply_workflow([], [prior])[0]["id"], "T1")

    def test_unresolved_takes_new_body_and_keeps_repos(self) -> None:
        prior = _ticket("T1", UNRESOLVED, title="old")
        incoming = _ticket("T1", UNRESOLVED, title="new", repos=[])
        out = apply_workflow([incoming], [prior])
        self.assertEqual(out[0]["title"], "new")
        self.assertEqual(out[0]["status"], UNRESOLVED)
        self.assertEqual(out[0]["repos"], [{"name": "fe"}])

    def test_skips_archived_ticket_when_still_the_same(self) -> None:
        with TemporaryDirectory() as raw:
            solved = Path(raw)
            archived = _ticket("T1", FIXED)
            (solved / "T1.json").write_text(json.dumps(archived) + "\n", encoding="utf-8")
            incoming = _ticket("T1", UNRESOLVED, title="rewritten")
            self.assertEqual(apply_workflow([incoming], [], solved), [])

    def test_skips_archived_ticket_restated_on_retest_list(self) -> None:
        with TemporaryDirectory() as raw:
            solved = Path(raw)
            archived = _ticket("T1", FIXED, context="original long context")
            (solved / "T1.json").write_text(json.dumps(archived) + "\n", encoding="utf-8")
            incoming = _ticket(
                "T1",
                UNRESOLVED,
                context="must pass acceptance before evaluation; remains on the retest list",
                expected="persistent alert on interruption",
            )
            self.assertEqual(apply_workflow([incoming], [], solved), [])

    def test_reopens_archived_ticket_when_retest_failed(self) -> None:
        with TemporaryDirectory() as raw:
            solved = Path(raw)
            archived = _ticket("T1", FIXED, repos=[{"name": "fe"}])
            (solved / "T1.json").write_text(json.dumps(archived) + "\n", encoding="utf-8")
            incoming = _ticket(
                "T1",
                UNRESOLVED,
                repos=[],
                kind="recurrent",
                context="Wi-Fi off for 60s during recording; only a timeout toast, expected modal did not appear",
            )
            out = apply_workflow([incoming], [], solved)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["status"], UNRESOLVED)
            self.assertEqual(out[0]["kind"], "recurrent")
            self.assertEqual(out[0]["repos"], [{"name": "fe"}])

    def test_skips_solved_id_if_kind_is_not_recurrent(self) -> None:
        with TemporaryDirectory() as raw:
            solved = Path(raw)
            archived = _ticket("T1", FIXED)
            (solved / "T1.json").write_text(json.dumps(archived) + "\n", encoding="utf-8")
            incoming = _ticket(
                "T1",
                UNRESOLVED,
                context="Wi-Fi off for 60s; expected modal did not appear",
            )
            self.assertEqual(apply_workflow([incoming], [], solved), [])

    def test_keeps_new_ids_and_drops_restated_solved(self) -> None:
        with TemporaryDirectory() as raw:
            solved = Path(raw)
            archived = _ticket("JMD-12OCT-01", FIXED)
            (solved / "JMD-12OCT-01.json").write_text(json.dumps(archived) + "\n", encoding="utf-8")
            restated = _ticket(
                "JMD-12OCT-01",
                UNRESOLVED,
                context="Silent omission of consultation content. Confirm root cause.",
            )
            fresh = _ticket(
                "EV-01",
                UNRESOLVED,
                title="Original SNOMED CT suggestions missing from frozen snapshot",
                context="Original SNOMED CT suggestions missing from the frozen pre-edit snapshot",
                expected="State 2 snapshot includes original SNOMED suggestions",
            )
            out = apply_workflow([restated, fresh], [], solved)
            self.assertEqual([item["id"] for item in out], ["EV-01"])
            self.assertEqual(out[0]["status"], UNRESOLVED)


class ArchiveSolvedTests(unittest.TestCase):
    def test_moves_fixed_and_completed_keeps_open(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "tickets.json"
            solved = root / "solved"
            save_tickets(
                [
                    _ticket("T1", FIXED),
                    _ticket("T2", COMPLETED),
                    _ticket("T3", UNRESOLVED),
                    _ticket("T4", VERIFYING),
                ],
                path,
            )
            with redirect_stdout(io.StringIO()):
                moved = archive_solved(path, solved)
            self.assertEqual([item["id"] for item in moved], ["T1", "T2"])
            self.assertEqual([item["id"] for item in load_tickets(path)], ["T3", "T4"])
            self.assertEqual(json.loads((solved / "T1.json").read_text(encoding="utf-8"))["status"], FIXED)
            self.assertEqual(json.loads((solved / "T2.json").read_text(encoding="utf-8"))["status"], COMPLETED)

    def test_parks_sources_when_working_list_empty(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "tickets.json"
            solved = root / "solved"
            email = root / "email.desc.txt"
            report = root / "list.pdf"
            save_tickets([_ticket("T1", FIXED)], path)
            email.write_text("previous email\n", encoding="utf-8")
            report.write_bytes(b"%PDF")
            with redirect_stdout(io.StringIO()):
                archive_solved(path, solved, sources=(email, report))
            self.assertEqual(load_tickets(path), [])
            self.assertFalse(email.exists())
            self.assertFalse(report.exists())
            self.assertEqual((solved / "email.desc.txt").read_text(encoding="utf-8"), "previous email\n")
            self.assertEqual((solved / "list.pdf").read_bytes(), b"%PDF")


class CompleteTests(unittest.TestCase):
    def test_complete_sets_completed(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "tickets.json"
            solved = root / "solved"
            save_tickets([_ticket("T1", VERIFYING)], path)
            with redirect_stdout(io.StringIO()):
                solver.complete("T1", path, solved)
            self.assertEqual(load_tickets(path), [])
            self.assertEqual(json.loads((solved / "T1.json").read_text(encoding="utf-8"))["status"], COMPLETED)

    def test_complete_rejects_fixed(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "tickets.json"
            save_tickets([_ticket("T1", FIXED)], path)
            with self.assertRaises(SystemExit):
                solver.complete("T1", path)
            self.assertEqual(load_tickets(path)[0]["status"], FIXED)


class RunLogTests(unittest.TestCase):
    def test_writes_prompt_verdict_files_and_tests(self) -> None:
        with TemporaryDirectory() as raw:
            runs = Path(raw)
            path = write_run_log(
                "JMD-12OCT-01",
                "solve",
                READY,
                "fix the ticket",
                "changed jmd-frontend/src/App.tsx\nnpm run test:run -- parse.test.ts\nVERDICT: ready",
                "run-abc",
                runs,
            )
            text = path.read_text(encoding="utf-8")
            self.assertEqual(path.name, "JMD-12OCT-01-run-abc.md")
            self.assertIn("- verdict: ready", text)
            self.assertIn("fix the ticket", text)
            self.assertIn("jmd-frontend/src/App.tsx", text)
            self.assertIn("npm run test:run -- parse.test.ts", text)
            self.assertIn("## Result", text)


if __name__ == "__main__":
    unittest.main()
