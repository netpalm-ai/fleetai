"""HTTP routes call the existing workflow functions."""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

import api
import config
from auth.deps import get_current_user
from auth.service import User


def _user() -> User:
    return User(id=uuid4(), username="tester", first_name="Test", last_name="User")


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.jobs = Path(self.tmp.name)
        self.prior = config.JOBS_DIR
        self.prior_lock = config.LOCK_PATH
        config.JOBS_DIR = self.jobs
        config.LOCK_PATH = self.jobs / ".lock"
        api.app.dependency_overrides[get_current_user] = _user
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        api.app.dependency_overrides.clear()
        config.JOBS_DIR = self.prior
        config.LOCK_PATH = self.prior_lock
        self.tmp.cleanup()

    def test_health_returns_version(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "version": config.VERSION})

    def test_health_fails_when_skill_missing(self) -> None:
        with patch.object(api.config, "engineering_standard", side_effect=RuntimeError("missing engineering standard")):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)

    def test_lists_tickets(self) -> None:
        with patch.object(api.config, "load_tickets", return_value=[{"id": "T1", "status": "unresolved"}]):
            response = self.client.get("/tickets")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"id": "T1", "status": "unresolved"}])

    def test_gets_one_ticket(self) -> None:
        ticket = {"id": "T1", "status": "completed"}
        with patch.object(api.config, "find_ticket", return_value=ticket):
            response = self.client.get("/tickets/T1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), ticket)

    def test_missing_ticket_get_is_404(self) -> None:
        with patch.object(api.config, "find_ticket", return_value=None):
            response = self.client.get("/tickets/T9")
        self.assertEqual(response.status_code, 404)

    def test_parse_returns_tickets(self) -> None:
        with patch.object(api.parser, "get_tickets", return_value=[{"id": "T1"}]) as get_tickets:
            response = self.client.post("/tickets/parse")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"id": "T1"}])
        get_tickets.assert_called_once_with()

    def test_execute_returns_job(self) -> None:
        with patch.object(api.orchestrator, "execute") as execute, patch.object(api.config, "load_tickets", return_value=[]):
            response = self.client.post("/execute")
        self.assertEqual(response.status_code, 202)
        job = response.json()
        self.assertEqual(job["kind"], "execute")
        execute.assert_called_once_with()
        polled = self.client.get("/jobs/{0}".format(job["id"]))
        self.assertEqual(polled.status_code, 200)
        self.assertEqual(polled.json()["status"], "done")
        self.assertEqual(polled.json()["tickets"], [])

    def test_solve_verify_return_jobs(self) -> None:
        ticket = {"id": "T1", "status": "verifying", "solver_run_id": "run-1"}
        with (
            patch.object(api.config, "require_ticket", return_value={"id": "T1", "status": "unresolved"}),
            patch.object(api.solver, "solve") as solve,
            patch.object(api.verifier, "verify") as verify,
            patch.object(api.config, "find_ticket", return_value=ticket),
        ):
            solved = self.client.post("/tickets/T1/solve")
            verified = self.client.post("/tickets/T1/verify")
        self.assertEqual(solved.status_code, 202)
        self.assertEqual(verified.status_code, 202)
        solve.assert_called_once_with("T1")
        verify.assert_called_once_with("T1")
        job = self.client.get("/jobs/{0}".format(solved.json()["id"])).json()
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["ticket"], ticket)
        self.assertEqual(job["run_id"], "run-1")

    def test_complete_returns_ticket(self) -> None:
        archived = {"id": "T1", "status": "completed"}
        with patch.object(api.solver, "complete") as complete, patch.object(api.config, "find_ticket", return_value=archived):
            response = self.client.post("/tickets/T1/complete")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), archived)
        complete.assert_called_once_with("T1")

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
            with config.workflow_lock():
                held.set()
                release.wait()

        thread = threading.Thread(target=hold)
        thread.start()
        held.wait()
        try:
            with patch.object(api.orchestrator, "execute") as execute:
                response = self.client.post("/execute")
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"], "workflow busy")
            execute.assert_not_called()
        finally:
            release.set()
            thread.join()

    def test_run_log_returns_text(self) -> None:
        with patch.object(api.config, "read_run_log", return_value="# T1 solve\n"):
            response = self.client.get("/tickets/T1/runs/run-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ticket_id": "T1", "run_id": "run-1", "text": "# T1 solve\n"})

    def test_ticket_routes_require_login(self) -> None:
        api.app.dependency_overrides.clear()
        try:
            self.assertEqual(self.client.get("/tickets").status_code, 401)
            self.assertEqual(self.client.get("/tickets/T1").status_code, 401)
            self.assertEqual(self.client.get("/tickets/T1/runs/run-1").status_code, 401)
            self.assertEqual(self.client.get("/jobs/missing").status_code, 401)
            self.assertEqual(self.client.post("/tickets/parse").status_code, 401)
            self.assertEqual(self.client.post("/tickets/T1/solve").status_code, 401)
            self.assertEqual(self.client.post("/tickets/T1/verify").status_code, 401)
            self.assertEqual(self.client.post("/tickets/T1/complete").status_code, 401)
            self.assertEqual(self.client.post("/execute").status_code, 401)
            self.assertEqual(self.client.get("/health").status_code, 200)
        finally:
            api.app.dependency_overrides[get_current_user] = _user
