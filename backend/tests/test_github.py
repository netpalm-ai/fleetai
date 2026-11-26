"""GitHub grant: connect, choose repos, clone under the product root, push fleetai/dev."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import api
import config
import db
import connections
from auth.sessions import COOKIE_NAME
from tests.signing import register_verify_login

CSRF = {"X-Requested-With": "fleetai"}
EMAIL = "ada@example.com"
PASSWORD = "correct-horse"
GITHUB_ENV = {
    "GITHUB_CLIENT_ID": "client-id",
    "GITHUB_CLIENT_SECRET": "client-secret",
    "PRODUCT_PUBLIC_BASE_URL": "https://fleet.example.com",
    "AUTH_SECRET_KEY": Fernet.generate_key().decode(),
}


@unittest.skipUnless(os.getenv("DATABASE_URL"), "DATABASE_URL is required")
class GithubConnectTests(unittest.TestCase):
    def setUp(self) -> None:
        key = patch.dict(os.environ, GITHUB_ENV)
        key.start()
        self.addCleanup(key.stop)
        self.cm = TestClient(api.app)
        self.client = self.cm.__enter__()
        with db.get_pool().connection() as conn:
            conn.execute("TRUNCATE users CASCADE")
            conn.commit()
        self.user_id = register_verify_login(
            self.client, email=EMAIL, password=PASSWORD, username="ada"
        )
        self.assertIn(COOKIE_NAME, self.client.cookies)

    def tearDown(self) -> None:
        self.cm.__exit__(None, None, None)

    def test_connect_sends_the_user_to_github(self) -> None:
        started = self.client.get("/github/connect", follow_redirects=False)
        self.assertEqual(started.status_code, 302)
        location = started.headers["location"]
        self.assertTrue(location.startswith("https://github.com/login/oauth/authorize?"))
        self.assertIn("client_id=client-id", location)
        self.assertIn("scope=repo", location)
        self.assertIn("redirect_uri=https%3A%2F%2Ffleet.example.com%2Fapi%2Fv1%2Fgithub%2Fcallback", location)

    def test_callback_stores_an_encrypted_token(self) -> None:
        self.client.cookies.set(connections.github.STATE_COOKIE, "state-1")
        with patch.object(connections.github, "exchange_code", return_value=("gho_secret", "octocat")):
            done = self.client.get("/github/callback?code=abc&state=state-1", follow_redirects=False)
        self.assertEqual(done.status_code, 302)
        self.assertIn("/connectors?github=connected", done.headers["location"])
        with db.get_pool().connection() as conn:
            stored = conn.execute(
                "SELECT github_login, access_token FROM github_connections WHERE user_id = %s",
                (self.user_id,),
            ).fetchone()
        self.assertEqual(stored["github_login"], "octocat")
        self.assertNotIn("gho_secret", stored["access_token"])
        self.assertEqual(connections.github._decrypt(stored["access_token"]), "gho_secret")

    def test_callback_rejects_a_mismatched_state(self) -> None:
        self.client.cookies.set(connections.github.STATE_COOKIE, "state-1")
        done = self.client.get("/github/callback?code=abc&state=other", follow_redirects=False)
        self.assertIn("github=failed", done.headers["location"])
        with db.get_pool().connection() as conn:
            count = conn.execute("SELECT count(*) AS n FROM github_connections").fetchone()["n"]
        self.assertEqual(count, 0)

    def test_only_granted_repositories_can_be_saved(self) -> None:
        connections.github.save_connection(self.user_id, "octocat", "gho_secret")
        with patch.object(connections.github, "list_repos", return_value=["acme/api"]):
            saved = self.client.put(
                "/github/repos", json={"project": "acme", "repos": ["acme/api"]}, headers=CSRF
            )
            rejected = self.client.put(
                "/github/repos", json={"project": "acme", "repos": ["other/nope"]}, headers=CSRF
            )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["project"], "acme")
        self.assertEqual(saved.json()["repos"], [{"full_name": "acme/api", "selected": True}])
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(connections.github.selected_repos(self.user_id), ["acme/api"])
        with db.get_pool().connection() as conn:
            repo = conn.execute(
                """
                SELECT r.full_name
                FROM github_repos r
                JOIN projects p ON p.id = r.project_id AND p.user_id = r.user_id
                WHERE r.user_id = %s
                """,
                (self.user_id,),
            ).fetchone()
        self.assertEqual(repo["full_name"], "acme/api")
        project_id = connections.active_project_id(self.user_id)
        self.assertIsNotNone(project_id)
        connections.save_project_context(
            project_id,
            self.user_id,
            "# Acme\n\n## Repositories\n\n| api | api | acme/api | api |\n",
            "go",
            "acme",
            "JarvisMD",
        )
        self.assertIn("## Repositories", connections.project_context(project_id))
        with db.get_pool().connection() as conn:
            row = conn.execute(
                """
                SELECT c.user_id, c.org, c.product_name, c.tech_stack, p.name
                FROM project_contexts c
                JOIN projects p ON p.id = c.project_id AND p.user_id = c.user_id
                WHERE c.project_id = %s
                """,
                (project_id,),
            ).fetchone()
        self.assertEqual(row["user_id"], self.user_id)
        self.assertEqual(row["name"], "acme")
        self.assertEqual(row["org"], "acme")
        self.assertEqual(row["product_name"], "JarvisMD")
        self.assertEqual(row["tech_stack"], "go")

    def test_catalog_holds_jarvismd_and_fleetai(self) -> None:
        with db.get_pool().connection() as conn:
            rows = conn.execute(
                """
                SELECT org, product_name, codebase_context
                FROM project_contexts
                WHERE project_id IS NULL
                ORDER BY product_name
                """
            ).fetchall()
        self.assertEqual(
            [(row["org"], row["product_name"]) for row in rows],
            [("Netpalm.AI", "FleetAI"), ("HBA", "JarvisMD")],
        )
        self.assertIn("## Product", rows[0]["codebase_context"])
        self.assertIn("FleetAI", rows[0]["codebase_context"])
        self.assertIn("## Org", rows[0]["codebase_context"])
        self.assertIn("Netpalm.AI", rows[0]["codebase_context"])
        self.assertIn("## Tech stack", rows[0]["codebase_context"])
        self.assertIn("React, TypeScript, FastAPI, Postgres", rows[0]["codebase_context"])
        self.assertIn("$FLEETAI_PRODUCT_ROOT/fleetai/frontend", rows[0]["codebase_context"])
        self.assertIn("fleetai/dev", rows[0]["codebase_context"])
        self.assertIn("## Repositories", rows[0]["codebase_context"])
        self.assertIn("jmd-frontend", rows[1]["codebase_context"])

    def test_a_different_github_account_clears_the_saved_project(self) -> None:
        connections.github.save_connection(self.user_id, "octocat", "gho_secret")
        with patch.object(connections.github, "list_repos", return_value=["acme/api"]):
            connections.github.save_repos(self.user_id, "acme", ["acme/api"])
        connections.github.save_connection(self.user_id, "other", "gho_other")
        self.assertEqual(connections.github.selected_repos(self.user_id), [])
        with db.get_pool().connection() as conn:
            project = conn.execute(
                "SELECT project_name, project_id FROM github_connections WHERE user_id = %s",
                (self.user_id,),
            ).fetchone()
        self.assertIsNone(project["project_name"])
        self.assertIsNone(project["project_id"])

    def test_status_keeps_a_saved_repo_missing_from_github(self) -> None:
        connections.github.save_connection(self.user_id, "octocat", "gho_secret")
        with patch.object(connections.github, "list_repos", return_value=["acme/api"]):
            connections.github.save_repos(self.user_id, "acme", ["acme/api"])
        with patch.object(connections.github, "list_repos", return_value=["acme/web"]):
            shown = self.client.get("/github")
        self.assertEqual(shown.status_code, 200)
        self.assertEqual(
            shown.json()["repos"],
            [
                {"full_name": "acme/web", "selected": False},
                {"full_name": "acme/api", "selected": True},
            ],
        )

    def test_fleetai_project_clones_its_repository(self) -> None:
        connections.github.save_connection(self.user_id, "octocat", "gho_secret")
        with db.get_pool().connection() as conn:
            project_id = connections.upsert_project(conn, self.user_id, "FleetAI")
            conn.commit()
        calls: list[tuple] = []

        def fake_git(cwd, token, *args):
            calls.append((Path(cwd).name, args))
            if args[-1:] == ("refs/heads/fleetai/dev",):
                raise RuntimeError("missing")
            return ""

        with TemporaryDirectory() as raw:
            with patch.dict(os.environ, {"FLEETAI_PROJECTS": raw}), patch.object(connections.github, "git", side_effect=fake_git):
                checkout = connections.github.prepare(self.user_id, project_id)
        self.assertEqual(checkout.root, Path(raw) / str(self.user_id) / "FleetAI")
        self.assertEqual(calls[0], ("FleetAI", ("clone", "--origin", "origin", "--", "https://github.com/netpalm-ai/fleetai.git", "fleetai")))
        self.assertEqual(calls[-1][1], ("checkout", "-B", "fleetai/dev", "origin/fleetai/dev"))

    def test_fleetai_clone_does_not_require_github(self) -> None:
        with db.get_pool().connection() as conn:
            project_id = connections.upsert_project(conn, self.user_id, "FleetAI")
            conn.commit()
        calls: list[tuple] = []

        def fake_git(cwd, token, *args):
            calls.append((token, args))
            if args[-1:] == ("refs/heads/fleetai/dev",):
                raise RuntimeError("missing")
            return ""

        with TemporaryDirectory() as raw:
            with patch.dict(os.environ, {"FLEETAI_PROJECTS": raw}), patch.object(connections.github, "git", side_effect=fake_git):
                checkout = connections.github.prepare(self.user_id, project_id)
        self.assertIsNone(checkout.token)
        self.assertIsNone(calls[0][0])
        self.assertIn("https://github.com/netpalm-ai/fleetai.git", calls[0][1])

    def test_rejected_github_token_retries_without_it(self) -> None:
        calls: list[list[str]] = []

        def fake_run(command, cwd, capture_output, text):
            calls.append(command)
            if any(part.startswith("http.extraheader=") for part in command):
                return subprocess.CompletedProcess(
                    command,
                    128,
                    "",
                    "fatal: could not read Username for 'https://github.com': No such device or address",
                )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch("connections.subprocess.run", side_effect=fake_run):
            connections.github.git(Path("/tmp"), "gho_secret", "ls-remote", "https://github.com/netpalm-ai/fleetai.git")
        self.assertEqual(len(calls), 2)
        self.assertTrue(any(part.startswith("http.extraheader=") for part in calls[0]))
        self.assertFalse(any(part.startswith("http.extraheader=") for part in calls[1]))

    def test_prepare_clones_under_the_product_root_and_uses_fleetai_dev(self) -> None:
        connections.github.save_connection(self.user_id, "octocat", "gho_secret")
        with patch.object(connections.github, "list_repos", return_value=["acme/api"]):
            connections.github.save_repos(self.user_id, "acme", ["acme/api"])
        calls: list[tuple] = []

        def fake_git(cwd, token, *args):
            calls.append((Path(cwd).name, token, args))
            if args[-1:] == ("refs/heads/fleetai/dev",):
                raise RuntimeError("missing")
            return ""

        with TemporaryDirectory() as raw:
            with patch.dict(os.environ, {"FLEETAI_PROJECTS": raw}), patch.object(connections.github, "git", side_effect=fake_git):
                checkout = connections.github.prepare(self.user_id)
        self.assertEqual(checkout.root, Path(raw) / str(self.user_id) / "acme")
        self.assertEqual(checkout.branch, "fleetai/dev")
        self.assertEqual(checkout.token, "gho_secret")
        self.assertEqual(calls[0][2][:3], ("clone", "--origin", "origin"))
        self.assertIn("https://github.com/acme/api.git", calls[0][2])
        self.assertNotIn("gho_secret", " ".join(calls[0][2]))
        self.assertEqual(calls[-1][2], ("checkout", "-B", "fleetai/dev", "origin/fleetai/dev"))

    def test_push_uses_the_granted_token_and_fleetai_dev(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            repo = root / "api"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
            (repo / "login.py").write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
            (repo / "login.py").write_text("new\n", encoding="utf-8")
            pushed: list[tuple] = []

            def fake_git(cwd, token, *args):
                if args[:1] == ("push",):
                    pushed.append((token, args))
                    return ""
                return subprocess.run(
                    ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
                ).stdout

            checkout = config.Checkout(root=root, token="gho_secret", branch="fleetai/dev")
            token = config.activate_checkout(checkout)
            try:
                with patch.object(connections.github, "git", side_effect=fake_git):
                    config.push_ticket("T1", "CHANGED FILES:\napi/login.py\nVERDICT: fixed")
            finally:
                config.restore_checkout(token)
            self.assertEqual(pushed, [("gho_secret", ("push", "origin", "HEAD:fleetai/dev"))])
            message = subprocess.run(
                ["git", "log", "-1", "--pretty=%s"], cwd=repo, check=True, capture_output=True, text=True
            ).stdout.strip()
            self.assertEqual(message, "fleetai: T1")
