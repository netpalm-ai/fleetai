"""HTTP routes call the existing workflow functions."""

from __future__ import annotations

import base64
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

import api
import config
from auth.deps import get_current_user
from auth.service import User

CSRF = {"X-Requested-With": "fleetai"}
USER = User(
    id=uuid4(),
    username="tester",
    first_name="Test",
    last_name="User",
    features=("tickets",),
)
PAID = User(
    id=uuid4(),
    username="payer",
    first_name="Pay",
    last_name="User",
    features=("tickets",),
    subscription_status="paid",
)


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        api.app.dependency_overrides[get_current_user] = lambda: USER
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        api.app.dependency_overrides.clear()

    def test_health_returns_version(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "version": config.VERSION})

    def test_health_fails_when_skill_missing(self) -> None:
        with patch.object(api.config, "engineering_standard", side_effect=RuntimeError("missing engineering standard")):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)

    def test_lists_tickets(self) -> None:
        with patch.object(api.intakes, "list_visible_tickets", return_value=[{"id": "T1", "status": "unresolved"}]) as listed:
            response = self.client.get("/tickets")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"id": "T1", "status": "unresolved"}])
        listed.assert_called_once_with(USER.id, None)

    def test_gets_one_ticket(self) -> None:
        ticket = {"id": "T1", "status": "completed"}
        with patch.object(api.intakes, "find_ticket", return_value=ticket) as found:
            response = self.client.get("/tickets/T1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), ticket)
        found.assert_called_once_with(USER.id, "T1")

    def test_missing_ticket_get_is_404(self) -> None:
        with patch.object(api.intakes, "find_ticket", return_value=None):
            response = self.client.get("/tickets/T9")
        self.assertEqual(response.status_code, 404)

    def test_parse_returns_tickets(self) -> None:
        with patch.object(api.parser, "get_tickets", return_value=[{"id": "T1"}]) as get_tickets:
            response = self.client.post("/tickets/parse")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"id": "T1"}])
        get_tickets.assert_called_once_with(USER.id, None)

    def test_execute_requires_a_ticket(self) -> None:
        with patch.object(api.orchestrator, "execute") as execute:
            response = self.client.post("/execute", json={"ticket_ids": []}, headers=CSRF)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Select a ticket.")
        execute.assert_not_called()

    def test_execute_returns_job(self) -> None:
        with patch.object(api.orchestrator, "execute") as execute:
            response = self.client.post("/execute", json={"ticket_ids": ["T1"]}, headers=CSRF)
        self.assertEqual(response.status_code, 202)
        job = response.json()
        self.assertEqual(job["kind"], "execute")
        execute.assert_called_once_with(USER.id, None, ["T1"])
        polled = self.client.get("/jobs/{0}".format(job["id"]))
        self.assertEqual(polled.status_code, 200)
        self.assertEqual(polled.json()["status"], "done")

    def test_job_is_private_to_its_user(self) -> None:
        with patch.object(api.orchestrator, "execute"):
            job = self.client.post("/execute", json={"ticket_ids": ["T1"]}, headers=CSRF).json()
        api.app.dependency_overrides[get_current_user] = lambda: PAID
        self.assertEqual(self.client.get("/jobs/{0}".format(job["id"])).status_code, 404)

    def test_execute_error_is_reported_on_the_job(self) -> None:
        with patch.object(api.orchestrator, "execute", side_effect=RuntimeError("boom")):
            job = self.client.post("/execute", json={"ticket_ids": ["T1"]}, headers=CSRF).json()
        polled = self.client.get("/jobs/{0}".format(job["id"])).json()
        self.assertEqual(polled["status"], "error")
        self.assertEqual(polled["error"], "boom")

    def test_solve_verify_return_jobs(self) -> None:
        with (
            patch.object(api.config, "require_ticket", return_value={"id": "T1", "status": "unresolved"}),
            patch.object(api.solver, "solve") as solve,
            patch.object(api.verifier, "verify") as verify,
            patch.object(api.intakes, "latest_run_id", return_value="run-1"),
        ):
            solved = self.client.post("/tickets/T1/solve")
            verified = self.client.post("/tickets/T1/verify")
        self.assertEqual(solved.status_code, 202)
        self.assertEqual(verified.status_code, 202)
        solve.assert_called_once_with(USER.id, "T1")
        verify.assert_called_once_with(USER.id, "T1")
        job = self.client.get("/jobs/{0}".format(verified.json()["id"])).json()
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["ticket_id"], "T1")
        self.assertEqual(job["run_id"], "run-1")

    def test_complete_returns_ticket(self) -> None:
        completed = {"id": "T1", "status": "completed"}
        with patch.object(api.solver, "complete", return_value=completed) as complete:
            response = self.client.post("/tickets/T1/complete")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), completed)
        complete.assert_called_once_with(USER.id, "T1")

    def test_complete_maps_system_exit(self) -> None:
        with patch.object(api.solver, "complete", side_effect=SystemExit("ticket T1 is fixed; complete only accepts verifying")):
            response = self.client.post("/tickets/T1/complete")
        self.assertEqual(response.status_code, 409)

    def test_missing_ticket_solve_is_404(self) -> None:
        with patch.object(api.config, "require_ticket", side_effect=SystemExit("ticket not found: T9")):
            response = self.client.post("/tickets/T9/solve")
        self.assertEqual(response.status_code, 404)

    def test_missing_job_is_404(self) -> None:
        self.assertEqual(self.client.get("/jobs/missing").status_code, 404)

    def test_execute_conflict_is_409(self) -> None:
        held = threading.Event()
        release = threading.Event()

        def hold() -> None:
            with config.workflow_lock(USER.id):
                held.set()
                release.wait()

        thread = threading.Thread(target=hold)
        thread.start()
        held.wait()
        try:
            with patch.object(api.orchestrator, "execute") as execute:
                response = self.client.post("/execute", json={"ticket_ids": ["T1"]}, headers=CSRF)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"], "workflow busy")
            execute.assert_not_called()
        finally:
            release.set()
            thread.join()

    def test_run_log_returns_text(self) -> None:
        with patch.object(api.config, "read_run_log", return_value="# T1 solve\n") as read:
            response = self.client.get("/tickets/T1/runs/run-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ticket_id": "T1", "run_id": "run-1", "text": "# T1 solve\n"})
        read.assert_called_once_with(USER.id, "T1", "run-1")

    def test_ticket_routes_require_login(self) -> None:
        api.app.dependency_overrides.clear()
        try:
            self.assertEqual(self.client.get("/tickets").status_code, 401)
            self.assertEqual(self.client.get("/tickets/T1").status_code, 401)
            self.assertEqual(self.client.get("/tickets/T1/runs/run-1").status_code, 401)
            self.assertEqual(self.client.get("/jobs/missing").status_code, 401)
            self.assertEqual(self.client.post("/tickets/parse").status_code, 401)
            self.assertEqual(self.client.post("/tickets/inputs").status_code, 401)
            self.assertEqual(self.client.post("/tickets/T1/solve").status_code, 401)
            self.assertEqual(self.client.post("/tickets/T1/verify").status_code, 401)
            self.assertEqual(self.client.post("/tickets/T1/complete").status_code, 401)
            self.assertEqual(self.client.post("/execute").status_code, 401)
            self.assertEqual(self.client.get("/settings").status_code, 401)
            self.assertEqual(self.client.put("/settings", json={"ticket_retention_days": 30}, headers=CSRF).status_code, 401)
            self.assertEqual(self.client.get("/health").status_code, 200)
        finally:
            api.app.dependency_overrides[get_current_user] = lambda: USER

    def test_ticket_routes_require_entitlement(self) -> None:
        api.app.dependency_overrides[get_current_user] = lambda: User(
            id=uuid4(),
            username="tester",
            first_name="Test",
            last_name="User",
        )
        self.assertEqual(self.client.get("/tickets").status_code, 403)
        self.assertEqual(self.client.post("/tickets/inputs", json={"email": "hi"}).status_code, 403)
        self.assertEqual(self.client.post("/execute").status_code, 403)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_post_inputs_saves_text(self) -> None:
        with patch.object(api.config, "save_intake") as save:
            response = self.client.post(
                "/tickets/inputs",
                json={"email": "hello", "list_text": "T1 broken login", "context": "# project"},
            )
        self.assertEqual(response.status_code, 204)
        save.assert_called_once_with("hello", "T1 broken login", "# project", None, USER.id, None)

    def test_post_inputs_saves_pdf(self) -> None:
        raw = b"%PDF-1.4 test"
        with patch.object(api.config, "save_intake") as save:
            response = self.client.post(
                "/tickets/inputs",
                json={"list_pdf_base64": base64.b64encode(raw).decode("ascii")},
            )
        self.assertEqual(response.status_code, 204)
        save.assert_called_once_with("", "", "", raw, USER.id, None)

    def test_post_inputs_rejects_empty(self) -> None:
        with patch.object(api.config, "save_intake", side_effect=RuntimeError("need an email or a ticket list")):
            response = self.client.post("/tickets/inputs", json={})
        self.assertEqual(response.status_code, 400)

    def test_post_inputs_busy(self) -> None:
        with patch.object(api.config, "save_intake", side_effect=config.WorkflowBusy("workflow busy")):
            response = self.client.post("/tickets/inputs", json={"email": "hello"})
        self.assertEqual(response.status_code, 409)


class SettingsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        api.app.dependency_overrides.clear()

    def test_free_user_sees_immediate_deletion_and_cannot_edit(self) -> None:
        api.app.dependency_overrides[get_current_user] = lambda: USER
        with patch.object(api.intakes, "keep_days", return_value=0):
            response = self.client.get("/settings")
        self.assertEqual(
            response.json(),
            {"subscription_status": "free", "ticket_retention_days": 0, "editable": False},
        )

    def test_paid_user_can_read_and_edit(self) -> None:
        api.app.dependency_overrides[get_current_user] = lambda: PAID
        with patch.object(api.intakes, "keep_days", return_value=90):
            response = self.client.get("/settings")
        self.assertEqual(
            response.json(),
            {"subscription_status": "paid", "ticket_retention_days": 90, "editable": True},
        )

    def test_paid_user_sets_days_and_forever(self) -> None:
        api.app.dependency_overrides[get_current_user] = lambda: PAID
        with patch.object(api.intakes, "set_keep_days") as save, patch.object(api.intakes, "keep_days", return_value=30):
            days = self.client.put("/settings", json={"ticket_retention_days": 30}, headers=CSRF)
            forever = self.client.put("/settings", json={"ticket_retention_days": None}, headers=CSRF)
        self.assertEqual(days.status_code, 200)
        self.assertEqual(forever.status_code, 200)
        self.assertEqual([call.args for call in save.call_args_list], [(PAID.id, 30), (PAID.id, None)])

    def test_non_paid_user_cannot_edit(self) -> None:
        api.app.dependency_overrides[get_current_user] = lambda: USER
        with patch.object(api.intakes, "set_keep_days") as save:
            response = self.client.put("/settings", json={"ticket_retention_days": 30}, headers=CSRF)
        self.assertEqual(response.status_code, 403)
        save.assert_not_called()

    def test_rejects_bad_values_and_missing_csrf(self) -> None:
        api.app.dependency_overrides[get_current_user] = lambda: PAID
        with patch.object(api.intakes, "set_keep_days") as save:
            self.assertEqual(self.client.put("/settings", json={"ticket_retention_days": 0}, headers=CSRF).status_code, 422)
            self.assertEqual(self.client.put("/settings", json={"ticket_retention_days": 45}, headers=CSRF).status_code, 422)
            self.assertEqual(self.client.put("/settings", json={}, headers=CSRF).status_code, 422)
            self.assertEqual(self.client.put("/settings", json={"ticket_retention_days": 30}).status_code, 403)
        save.assert_not_called()
