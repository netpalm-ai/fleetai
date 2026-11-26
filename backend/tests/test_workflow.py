"""Workflow helpers: parse merge, verdicts, locks, intake validation."""

from __future__ import annotations

import json
import subprocess
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pymupdf
from cursor_sdk import SDKImage, UserMessage

import config
import intakes
import llm
import parser
import solver
import verifier
from config import (
    BLOCKED,
    FAILED,
    FIXED,
    READY,
    UNRESOLVED,
    VERIFYING,
    apply_workflow,
    last_verdict,
    normalize_ticket,
    agent_context,
    engineering_standard,
    ensure_code_context,
    product_areas,
    tech_ticket,
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


class RequireEnvTests(unittest.TestCase):
    def test_missing_env_fails(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                config.require_env("FLEETAI_SUMMARY_MODEL")


class ProductAreasTests(unittest.TestCase):
    def test_parser_map_is_repositories_only(self) -> None:
        text = product_areas(
            "# Product\n\n## Repositories\n\n| app | . | local | demo |\n\n## Work rules\n\nstaging-uk-jmd-xycare-cicd\n"
        )
        self.assertIn("## Repositories", text)
        self.assertNotIn("## Work rules", text)
        self.assertNotIn("staging-uk-jmd-xycare-cicd", text)
        self.assertNotIn("jmd-frontend", text)

    def test_example_map_slices_to_repositories(self) -> None:
        path = Path(__file__).resolve().parents[1] / "codebase" / "code-context.fleetai.md"
        text = product_areas(path.read_text(encoding="utf-8"))
        self.assertIn("## Repositories", text)
        self.assertIn("frontend", text)
        self.assertNotIn("jmd-frontend", text)
        self.assertNotIn("## Work rules", text)

    def test_missing_map_is_stored_on_the_project(self) -> None:
        user_id = uuid4()
        project_id = uuid4()
        saved: dict = {}
        with TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.check_call(["git", "init", "-q", str(root)])

            def write_map(prompt: str) -> None:
                self.assertIn("Tech stack", prompt)
                self.assertNotIn("jmd-", prompt)
                self.assertNotIn("Jarvis", prompt)
                dest = root / ".fleetai" / "code-context.md"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(
                    "# Demo\n\n## Product\n\nFleetAI\n\n## Org\n\nnetpalm\n\n## Repositories\n\n| app | . | local | demo |\n\n## Tech stack\n\npython, postgres\n",
                    encoding="utf-8",
                )

            def remember(pid, owner, context: str, tech: str, org: str, product_name: str) -> None:
                saved[pid] = (context, tech, owner, org, product_name)

            with patch.dict("os.environ", {"FLEETAI_PRODUCT_ROOT": str(root)}):
                with (
                    patch("connections.active_project_id", return_value=project_id),
                    patch("connections.project_name", return_value="demo"),
                    patch("connections.catalog_context", return_value=None),
                    patch("connections.project_context", side_effect=lambda pid: None if pid not in saved else saved[pid][0]),
                    patch("connections.save_project_context", side_effect=remember),
                    patch("llm.cursor.run", side_effect=write_map) as run,
                ):
                    first = ensure_code_context(user_id)
                    second = ensure_code_context(user_id)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(len(run.call_args.args), 1)
            self.assertIsInstance(run.call_args.args[0], str)
            self.assertEqual(saved[project_id][0], first)
            self.assertEqual(saved[project_id][1], "python, postgres")
            self.assertEqual(saved[project_id][2], user_id)
            self.assertEqual(saved[project_id][3], "netpalm")
            self.assertEqual(saved[project_id][4], "FleetAI")
            self.assertEqual(second, first)
            self.assertFalse((root / ".fleetai" / "code-context.md").exists())
            self.assertIn(".fleetai/", (root / ".git" / "info" / "exclude").read_text(encoding="utf-8"))


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
        self.assertIn("Follow ENGINEERING STANDARD", prompt)
        self.assertIn("Investigate before you edit", prompt)
        self.assertIn("every repo the diff touches", prompt)
        self.assertIn("adjacent consumers CODE CONTEXT names", prompt)
        self.assertIn("list each named item", prompt)
        self.assertIn("not a software defect", prompt)
        self.assertNotIn("Fix this ticket", prompt)
        self.assertNotIn("PREVIOUS ATTEMPT", prompt)
        retry = solver.ticket_prompt(ticket, "map", previous_verify="missing adjacent tests\nVERDICT: failed")
        self.assertIn("PREVIOUS ATTEMPT", retry)
        self.assertIn("own work", retry)
        self.assertIn("missing adjacent tests", retry)
        long_note = "x" * (solver.VERIFY_NOTE_CHARS + 50)
        self.assertLessEqual(len(solver.clip_verify_note(long_note)), solver.VERIFY_NOTE_CHARS + 4)
        self.assertTrue(solver.clip_verify_note(long_note).endswith("..."))
        for banned in ("jmd-", "SNOMED", "Xycare", "FHIR", "409137002"):
            self.assertNotIn(banned, prompt)
            self.assertNotIn(banned, retry)


class EngineeringIngestTests(unittest.TestCase):
    def test_standard_is_generic_and_loaded_before_the_adapter(self) -> None:
        skill = engineering_standard()
        self.assertIn("Edit existing code", skill)
        self.assertIn("renders stamped fields", skill)
        self.assertIn("inspect FLEETAI_PRODUCT_ROOT", skill)
        self.assertIn("already dirty", skill)
        self.assertIn("own previous attempt", skill)
        self.assertIn("done, not done, or deferred", skill)
        self.assertIn("ticket's premise is false", skill)
        self.assertIn("every repo the diff touches", skill)
        self.assertIn("A test that passes only because a CI service is missing is not a pass", skill)
        self.assertIn("Do not switch branch, stash, commit, push, rebase, discard, or deploy", skill)
        for banned in ("jmd-", "SNOMED", "Xycare", "FHIR", "409137002", "staging-uk-jmd"):
            self.assertNotIn(banned, skill)
        packed = agent_context("# Product\n\n## Repositories\n\n| app | . | local | demo |\n")
        self.assertLess(packed.find("ENGINEERING STANDARD"), packed.find("CODE CONTEXT"))
        self.assertLess(packed.find("Edit existing code"), packed.find("## Repositories"))
        sent = solver.ticket_prompt(_ticket("T1", UNRESOLVED), packed)
        self.assertIn("Edit existing code", sent)
        self.assertIn("## Repositories", sent)

    def test_missing_or_empty_standard_fails(self) -> None:
        with TemporaryDirectory() as raw:
            missing = Path(raw) / "nope.md"
            empty = Path(raw) / "empty.md"
            empty.write_text("  \n", encoding="utf-8")
            prior = config.ENGINEERING_PATH
            try:
                config.ENGINEERING_PATH = missing
                with self.assertRaises(RuntimeError):
                    engineering_standard()
                config.ENGINEERING_PATH = empty
                with self.assertRaises(RuntimeError):
                    engineering_standard()
            finally:
                config.ENGINEERING_PATH = prior


class VerifierPromptTests(unittest.TestCase):
    def test_verifier_repairs_introduced_bugs_before_fixed(self) -> None:
        ticket = _ticket("T1", VERIFYING)
        prompt = verifier.verify_prompt(ticket, "map")
        self.assertNotIn("Do not implement", prompt)
        self.assertIn("If the change introduced a bug, fix that bug and re-check", prompt)
        self.assertIn("every repo the solver diff touches", prompt)
        self.assertIn("tests that pass only because a CI service is missing", prompt)
        self.assertIn("Also refine the solver diff", prompt)
        self.assertIn("reuse existing functions", prompt)
        self.assertIn("Other than that, you must fix", prompt)
        self.assertIn("Do not mark it resolved while a new bug or that extra complexity is still in the tree", prompt)
        self.assertIn("VERDICT: fixed", prompt)
        self.assertIn("VERDICT: failed", prompt)
        self.assertIn("Hunt incurred bugs", prompt)
        self.assertIn("domain rules or identifier tables added in the wrong layer", prompt)
        self.assertIn("sensitive payloads", prompt)
        self.assertIn("adjacent behaviour compiled away", prompt)
        self.assertIn("named ticket items", prompt)
        for banned in ("jmd-", "SNOMED", "Xycare", "FHIR", "409137002"):
            self.assertNotIn(banned, prompt)


class ParserPromptTests(unittest.TestCase):
    def test_parser_omits_rebuild_and_redeploy_process(self) -> None:
        self.assertIn("rebuild, merge, redeploy, image-tag requests", parser.PROMPT)
        self.assertIn("An attached image is evidence of the defect it shows.", parser.PROMPT)
        self.assertIn("A request whose only demand is to send a screenshot is still not a ticket.", parser.PROMPT)
        for banned in ("jmd-", "SNOMED", "Xycare", "FHIR", "409137002"):
            self.assertNotIn(banned, parser.PROMPT)


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
        prior = _ticket("T1", FIXED, title="old")
        incoming = _ticket(
            "T1",
            UNRESOLVED,
            title="rewritten",
            repos=[],
            report_status="Partially Fixed",
        )
        out = apply_workflow([incoming], [prior], {})
        self.assertEqual(out[0]["title"], "old")
        self.assertEqual(out[0]["status"], FIXED)
        self.assertEqual(out[0]["repos"], [{"name": "fe"}])
        self.assertEqual(out[0]["report_status"], "Partially Fixed")

    def test_keeps_omitted_in_flight_ticket(self) -> None:
        prior = _ticket("T1", VERIFYING)
        self.assertEqual(apply_workflow([], [prior], {})[0]["id"], "T1")

    def test_unresolved_takes_new_body_and_keeps_repos(self) -> None:
        prior = _ticket("T1", UNRESOLVED, title="old")
        incoming = _ticket("T1", UNRESOLVED, title="new", repos=[])
        out = apply_workflow([incoming], [prior], {})
        self.assertEqual(out[0]["title"], "new")
        self.assertEqual(out[0]["status"], UNRESOLVED)
        self.assertEqual(out[0]["repos"], [{"name": "fe"}])

    def test_skips_archived_ticket_when_still_the_same(self) -> None:
        archived = {"T1": _ticket("T1", FIXED)}
        incoming = _ticket("T1", UNRESOLVED, title="rewritten")
        self.assertEqual(apply_workflow([incoming], [], archived), [])

    def test_skips_archived_ticket_restated_on_retest_list(self) -> None:
        archived = {"T1": _ticket("T1", FIXED, context="original long context")}
        incoming = _ticket(
            "T1",
            UNRESOLVED,
            context="must pass acceptance before evaluation; remains on the retest list",
            expected="persistent alert on interruption",
        )
        self.assertEqual(apply_workflow([incoming], [], archived), [])

    def test_reopens_archived_ticket_when_retest_failed(self) -> None:
        archived = {"T1": _ticket("T1", FIXED, repos=[{"name": "fe"}])}
        incoming = _ticket(
            "T1",
            UNRESOLVED,
            repos=[],
            kind="recurrent",
            context="Wi-Fi off for 60s during recording; only a timeout toast, expected modal did not appear",
        )
        out = apply_workflow([incoming], [], archived)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["status"], UNRESOLVED)
        self.assertEqual(out[0]["kind"], "recurrent")
        self.assertEqual(out[0]["repos"], [{"name": "fe"}])

    def test_skips_solved_id_if_kind_is_not_recurrent(self) -> None:
        archived = {"T1": _ticket("T1", FIXED)}
        incoming = _ticket(
            "T1",
            UNRESOLVED,
            context="Wi-Fi off for 60s; expected modal did not appear",
        )
        self.assertEqual(apply_workflow([incoming], [], archived), [])

    def test_keeps_new_ids_and_drops_restated_solved(self) -> None:
        archived = {"JMD-12OCT-01": _ticket("JMD-12OCT-01", FIXED)}
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
        out = apply_workflow([restated, fresh], [], archived)
        self.assertEqual([item["id"] for item in out], ["EV-01"])
        self.assertEqual(out[0]["status"], UNRESOLVED)


class WorkflowLockTests(unittest.TestCase):
    def test_nested_lock_does_not_block(self) -> None:
        user = uuid4()
        with config.workflow_lock(user):
            with config.workflow_lock(user):
                self.assertTrue(config.workflow_busy(user))
        self.assertFalse(config.workflow_busy(user))

    def test_other_thread_is_busy(self) -> None:
        user = uuid4()
        held = threading.Event()
        release = threading.Event()

        def hold() -> None:
            with config.workflow_lock(user):
                held.set()
                release.wait()

        thread = threading.Thread(target=hold)
        thread.start()
        held.wait()
        try:
            self.assertTrue(config.workflow_busy(user))
            with self.assertRaises(config.WorkflowBusy):
                with config.workflow_lock(user, blocking=False):
                    pass
        finally:
            release.set()
            thread.join()
        self.assertFalse(config.workflow_busy(user))

    def test_other_user_is_not_busy(self) -> None:
        with config.workflow_lock(uuid4()):
            self.assertFalse(config.workflow_busy(uuid4()))


def _encrypted_pdf() -> bytes:
    document = pymupdf.open()
    document.new_page()
    data = document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    document.close()
    return data


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00"
JPEG = b"\xff\xd8\xff\xd9"
WEBP = b"RIFF\x08\x00\x00\x00WEBP"


class SaveIntakeValidationTests(unittest.TestCase):
    def _save(self, email: str, list_text: str, context: str, pdf: bytes | None, images: list[bytes] | None = None) -> None:
        config.save_intake(email, list_text, context, pdf, uuid4(), None, images)

    def test_rejects_empty(self) -> None:
        with self.assertRaises(RuntimeError):
            self._save("", "", "", None)

    def test_rejects_non_pdf(self) -> None:
        with self.assertRaises(RuntimeError):
            self._save("", "", "", b"hello")

    def test_rejects_truncated_pdf(self) -> None:
        with self.assertRaises(RuntimeError):
            self._save("", "", "", b"%PDF-1.4")

    def test_rejects_encrypted_pdf(self) -> None:
        with self.assertRaises(RuntimeError):
            self._save("", "", "", _encrypted_pdf())

    def test_rejects_invalid_image(self) -> None:
        with self.assertRaises(RuntimeError):
            self._save("", "", "", None, [b"hello"])

    def test_rejects_image_over_five_mb(self) -> None:
        with self.assertRaises(RuntimeError):
            self._save("", "", "", None, [b"\x89PNG\r\n\x1a\n" + b"\x00" * (config.INTAKE_IMAGE_MAX)])

    def test_rejects_more_than_eight_images(self) -> None:
        with self.assertRaises(RuntimeError):
            self._save("", "", "", None, [PNG] * 9)

    def test_rejects_upload_over_fifty_mb(self) -> None:
        pdf = b"%PDF" + b"\x00" * (config.INTAKE_PDF_MAX - 4)
        with patch.object(config, "_require_pdf"):
            with self.assertRaises(RuntimeError):
                self._save("", "", "", pdf, [PNG])

    def test_images_only_is_a_ticket_list(self) -> None:
        with patch.object(intakes, "put") as put, patch.object(intakes, "deactivate"):
            config.save_intake("", "", "", None, uuid4(), None, [PNG])
        self.assertEqual([call.args[3] for call in put.call_args_list], ["png"])
        self.assertEqual(put.call_args.args[4], PNG)

    def test_accepts_eight_images(self) -> None:
        with patch.object(intakes, "put") as put, patch.object(intakes, "deactivate"):
            config.save_intake("", "", "", None, uuid4(), None, [PNG] * 8)
        self.assertEqual([call.args[3] for call in put.call_args_list], ["png"] * 8)
        self.assertTrue(put.call_args_list[0].kwargs.get("replace", True))
        self.assertTrue(all(call.kwargs.get("replace") is False for call in put.call_args_list[1:]))

    def test_stores_png_jpeg_webp_on_ticket_list_rows(self) -> None:
        user_id = uuid4()
        with patch.object(intakes, "put") as put, patch.object(intakes, "deactivate"):
            config.save_intake("", "T1 login fails", "", None, user_id, None, [PNG, JPEG, WEBP])
        formats = [call.args[3] for call in put.call_args_list]
        payloads = [call.args[4] for call in put.call_args_list]
        self.assertEqual(formats, ["txt", "png", "jpeg", "webp"])
        self.assertEqual(payloads[1:], [PNG, JPEG, WEBP])
        self.assertNotIn("replace", put.call_args_list[0].kwargs)
        self.assertTrue(all(call.kwargs.get("replace") is False for call in put.call_args_list[1:]))
        self.assertNotIn(PNG, payloads[0])

    def test_pdf_plus_images_stores_pdf_then_images(self) -> None:
        pdf = b"%PDF-1.4 test"
        with patch.object(config, "_require_pdf"), patch.object(intakes, "put") as put, patch.object(intakes, "deactivate"):
            config.save_intake("", "", "", pdf, uuid4(), None, [PNG])
        self.assertEqual([call.args[3] for call in put.call_args_list], ["pdf", "png"])
        self.assertEqual(put.call_args_list[0].args[4], pdf)
        self.assertEqual(put.call_args_list[1].args[4], PNG)
        self.assertEqual(put.call_args_list[1].kwargs.get("replace"), False)


class IntakeTextTests(unittest.TestCase):
    def test_pdf_contributes_extracted_text_only(self) -> None:
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), "T9 export hangs")
        pdf = document.tobytes()
        document.close()
        with patch.object(intakes, "active_content", return_value=("pdf", pdf)):
            text = parser.intake_text(uuid4(), "ticket_list")
        self.assertEqual(text, "T9 export hangs")
        self.assertNotIn(pdf, text.encode("utf-8"))


class ParserImageTests(unittest.TestCase):
    def _ticket_json(self) -> str:
        return json.dumps(
            [
                {
                    "id": "T1",
                    "title": "login fails",
                    "severity": "high",
                    "services": ["api"],
                    "context": "broken login",
                    "expected": "login works",
                }
            ]
        )

    def test_images_only_extracts_with_cursor(self) -> None:
        user_id = uuid4()
        with (
            patch.object(parser, "ensure_code_context", return_value="## Repositories\n| app | . | local | demo |\n"),
            patch.object(parser, "intake_text", return_value=""),
            patch.object(intakes, "active_images", return_value=[("png", PNG)]),
            patch.object(intakes, "solved_tickets", return_value={}),
            patch.object(intakes, "open_tickets", return_value=[]),
            patch.object(intakes, "sync_tickets") as sync,
            patch.object(parser.bedrock, "complete") as complete,
            patch.object(parser.cursor, "run", return_value=SimpleNamespace(id="p1", result=self._ticket_json())) as run,
        ):
            tickets = parser.get_tickets(user_id, None)
        complete.assert_not_called()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0].count("still not a ticket"), 1)
        self.assertIn("The ticket list is the attached images.", run.call_args.args[0])
        self.assertEqual(run.call_args.args[1], [("png", PNG)])
        self.assertEqual([item["id"] for item in tickets], ["T1"])
        sync.assert_called_once()

    def test_email_plus_images_without_list_text_uses_cursor(self) -> None:
        user_id = uuid4()

        def texts(_user_id, intake_type: str) -> str:
            return {"email_desc": "login is broken", "ticket_list": "", "project_context": ""}.get(intake_type, "")

        with (
            patch.object(parser, "ensure_code_context", return_value="## Repositories\n| app | . | local | demo |\n"),
            patch.object(parser, "intake_text", side_effect=texts),
            patch.object(intakes, "active_images", return_value=[("png", PNG)]),
            patch.object(intakes, "solved_tickets", return_value={}),
            patch.object(intakes, "open_tickets", return_value=[]),
            patch.object(intakes, "sync_tickets"),
            patch.object(parser.bedrock, "complete") as complete,
            patch.object(parser.cursor, "run", return_value=SimpleNamespace(id="p1", result=self._ticket_json())) as run,
        ):
            tickets = parser.get_tickets(user_id, None)
        complete.assert_not_called()
        self.assertIn("login is broken", run.call_args.args[0])
        self.assertEqual(run.call_args.args[1], [("png", PNG)])
        self.assertEqual([item["id"] for item in tickets], ["T1"])

    def test_text_plus_images_extracts_from_text(self) -> None:
        user_id = uuid4()

        def texts(_user_id, intake_type: str) -> str:
            return {"email_desc": "", "ticket_list": "T1 login fails", "project_context": ""}.get(intake_type, "")

        with (
            patch.object(parser, "ensure_code_context", return_value="## Repositories\n| app | . | local | demo |\n"),
            patch.object(parser, "intake_text", side_effect=texts),
            patch.object(intakes, "active_images", return_value=[("png", PNG)]),
            patch.object(intakes, "solved_tickets", return_value={}),
            patch.object(intakes, "open_tickets", return_value=[]),
            patch.object(intakes, "sync_tickets"),
            patch.object(parser.bedrock, "complete", return_value=self._ticket_json()) as complete,
            patch.object(parser.cursor, "run") as run,
        ):
            tickets = parser.get_tickets(user_id, None)
        run.assert_not_called()
        complete.assert_called_once()
        self.assertIn("T1 login fails", complete.call_args.args[0])
        self.assertNotIn(PNG.decode("latin1"), complete.call_args.args[0])
        self.assertEqual([item["id"] for item in tickets], ["T1"])


class CursorImageTests(unittest.TestCase):
    def test_run_sends_user_message_with_sdk_images(self) -> None:
        result = SimpleNamespace(status="ok", id="run-1", result="done")
        with (
            patch.dict("os.environ", {"CURSOR_API_KEY": "test-key"}, clear=False),
            patch.object(llm, "product_cwd", return_value=Path("/tmp")),
            patch("cursor_sdk.Agent.prompt", return_value=result) as prompt,
        ):
            llm.cursor.run("PROMPT-TEXT", [("png", PNG), ("jpeg", JPEG)])
        message = prompt.call_args.args[0]
        self.assertIsInstance(message, UserMessage)
        self.assertEqual(message.text, "PROMPT-TEXT")
        self.assertEqual(len(message.images or []), 2)
        self.assertIsInstance((message.images or ())[0], SDKImage)
        self.assertEqual((message.images or ())[0].mime_type, "image/png")
        self.assertNotIn(PNG, message.text.encode("utf-8"))

    def test_run_without_images_still_sends_a_string(self) -> None:
        result = SimpleNamespace(status="ok", id="run-1", result="done")
        with (
            patch.dict("os.environ", {"CURSOR_API_KEY": "test-key"}, clear=False),
            patch.object(llm, "product_cwd", return_value=Path("/tmp")),
            patch("cursor_sdk.Agent.prompt", return_value=result) as prompt,
        ):
            llm.cursor.run("PROMPT-TEXT")
        self.assertEqual(prompt.call_args.args[0], "PROMPT-TEXT")

    def test_solve_stores_text_prompt_not_image_bytes(self) -> None:
        user_id = uuid4()
        ticket = _ticket("T1", UNRESOLVED)
        with (
            patch.object(intakes, "find_ticket", return_value=ticket),
            patch.object(intakes, "ticket_project_id", return_value=None),
            patch.object(intakes, "active_images", return_value=[("png", PNG)]),
            patch.object(intakes, "add_run") as add_run,
            patch.object(intakes, "set_ticket_status"),
            patch.object(config, "ensure_code_context", return_value="## Repositories\n"),
            patch("llm.cursor.run", return_value=SimpleNamespace(id="run-1", result="VERDICT: ready")) as run,
        ):
            config.run_step(user_id, "T1", UNRESOLVED, "solve", lambda _ticket, _context: "PROMPT-TEXT", {READY: VERIFYING})
        self.assertEqual(run.call_args.args[0], "PROMPT-TEXT")
        self.assertEqual(run.call_args.args[1], [("png", PNG)])
        stored = add_run.call_args.args[5]
        self.assertEqual(stored, "PROMPT-TEXT")
        self.assertNotIn(PNG, stored.encode("utf-8"))

    def test_solve_without_images_sends_text_only(self) -> None:
        user_id = uuid4()
        ticket = _ticket("T1", UNRESOLVED)
        with (
            patch.object(intakes, "find_ticket", return_value=ticket),
            patch.object(intakes, "ticket_project_id", return_value=None),
            patch.object(intakes, "active_images", return_value=[]),
            patch.object(intakes, "add_run"),
            patch.object(intakes, "set_ticket_status"),
            patch.object(config, "ensure_code_context", return_value="## Repositories\n"),
            patch("llm.cursor.run", return_value=SimpleNamespace(id="run-1", result="VERDICT: ready")) as run,
        ):
            config.run_step(user_id, "T1", UNRESOLVED, "solve", lambda _ticket, _context: "PROMPT-TEXT", {READY: VERIFYING})
        self.assertEqual(run.call_args.args[0], "PROMPT-TEXT")
        self.assertIsNone(run.call_args.args[1])

    def test_verify_sends_images_and_stores_text_prompt(self) -> None:
        user_id = uuid4()
        ticket = _ticket("T1", VERIFYING)
        with (
            patch.object(intakes, "find_ticket", return_value=ticket),
            patch.object(intakes, "ticket_project_id", return_value=None),
            patch.object(intakes, "active_images", return_value=[("webp", WEBP)]),
            patch.object(intakes, "add_run") as add_run,
            patch.object(intakes, "set_ticket_status"),
            patch.object(config, "ensure_code_context", return_value="## Repositories\n"),
            patch("llm.cursor.run", return_value=SimpleNamespace(id="run-2", result="VERDICT: fixed")) as run,
        ):
            config.run_step(user_id, "T1", VERIFYING, "verify", lambda _ticket, _context: "PROMPT-TEXT", {FIXED: FIXED, FAILED: UNRESOLVED})
        self.assertEqual(run.call_args.args[0], "PROMPT-TEXT")
        self.assertEqual(run.call_args.args[1], [("webp", WEBP)])
        stored = add_run.call_args.args[5]
        self.assertEqual(stored, "PROMPT-TEXT")
        self.assertNotIn(WEBP, stored.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
