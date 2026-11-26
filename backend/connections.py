"""External grants. GitHub clones the customer's repos and pushes fleetai/dev."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from typing import NamedTuple
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

import config
import db

_REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CATALOG_REPOS = {"FleetAI": ("netpalm-ai/fleetai",)}
_TIMEOUT = 30


class _Grant(NamedTuple):
    login: str
    token: str
    project: str


class GithubConnection:
    """One GitHub account for a FleetAI user."""

    STATE_COOKIE = "github_oauth_state"
    WORK_BRANCH = "fleetai/dev"

    def configured(self) -> bool:
        return bool(self._client_id() and self._client_secret() and self._public_base())

    def _client_id(self) -> str:
        return (os.getenv("GITHUB_CLIENT_ID") or "").strip()

    def _client_secret(self) -> str:
        return (os.getenv("GITHUB_CLIENT_SECRET") or "").strip()

    def _public_base(self) -> str:
        return (os.getenv("PRODUCT_PUBLIC_BASE_URL") or "").strip().rstrip("/")

    def redirect_uri(self) -> str:
        return self._public_base() + "/api/v1/github/callback"

    def authorize_url(self, state: str) -> str:
        query = urllib.parse.urlencode(
            {
                "client_id": self._client_id(),
                "redirect_uri": self.redirect_uri(),
                "scope": "repo",
                "state": state,
            }
        )
        return "https://github.com/login/oauth/authorize?" + query

    def _cipher(self) -> Fernet:
        try:
            return Fernet((os.getenv("AUTH_SECRET_KEY") or "").encode())
        except ValueError as exc:
            raise RuntimeError("AUTH_SECRET_KEY is missing or not a valid key") from exc

    def _encrypt(self, token: str) -> str:
        return self._cipher().encrypt(token.encode()).decode()

    def _decrypt(self, stored: str) -> str:
        try:
            return self._cipher().decrypt(stored.encode()).decode()
        except (InvalidToken, ValueError) as exc:
            raise RuntimeError("GitHub connection cannot be read") from exc

    def _github(self, method: str, url: str, token: str | None = None, body: dict | None = None) -> tuple[dict, object]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "application/json", "User-Agent": "fleetai"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                payload = json.load(response)
                return dict(response.headers), payload
        except urllib.error.HTTPError as exc:
            raise RuntimeError("GitHub answered {0}".format(exc.code)) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("GitHub request failed") from exc

    def exchange_code(self, code: str) -> tuple[str, str]:
        _, payload = self._github(
            "POST",
            "https://github.com/login/oauth/access_token",
            body={
                "client_id": self._client_id(),
                "client_secret": self._client_secret(),
                "code": code,
                "redirect_uri": self.redirect_uri(),
            },
        )
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise RuntimeError("GitHub did not return a token")
        token = str(payload["access_token"])
        _, user = self._github("GET", "https://api.github.com/user", token=token)
        if not isinstance(user, dict) or not user.get("login"):
            raise RuntimeError("GitHub did not return an account")
        return token, str(user["login"])

    def save_connection(self, user_id: UUID, login: str, token: str) -> None:
        with db.get_pool().connection() as conn:
            previous = conn.execute(
                "SELECT github_login FROM github_connections WHERE user_id = %s",
                (user_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO github_connections (user_id, github_login, access_token)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE
                SET github_login = EXCLUDED.github_login,
                    access_token = EXCLUDED.access_token,
                    connected_at = now()
                """,
                (user_id, login, self._encrypt(token)),
            )
            if previous is not None and str(previous["github_login"]) != login:
                conn.execute(
                    "UPDATE github_connections SET project_name = NULL, project_id = NULL WHERE user_id = %s",
                    (user_id,),
                )
                conn.execute("DELETE FROM github_repos WHERE user_id = %s", (user_id,))
            conn.commit()

    def disconnect(self, user_id: UUID) -> None:
        with db.get_pool().connection() as conn:
            conn.execute("DELETE FROM github_connections WHERE user_id = %s", (user_id,))
            conn.execute("DELETE FROM github_repos WHERE user_id = %s", (user_id,))
            conn.commit()

    def _connection(self, user_id: UUID) -> _Grant | None:
        if db.pool is None:
            return None
        with db.get_pool().connection() as conn:
            row = conn.execute(
                "SELECT github_login, access_token, project_name FROM github_connections WHERE user_id = %s",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return _Grant(str(row["github_login"]), self._decrypt(str(row["access_token"])), str(row["project_name"] or ""))

    def selected_repos(self, user_id: UUID) -> list[str]:
        with db.get_pool().connection() as conn:
            rows = conn.execute(
                "SELECT full_name FROM github_repos WHERE user_id = %s ORDER BY full_name",
                (user_id,),
            ).fetchall()
        return [str(row["full_name"]) for row in rows]

    def list_repos(self, token: str) -> list[str]:
        names: list[str] = []
        url = "https://api.github.com/user/repos?per_page=100&sort=full_name&affiliation=owner,organization_member"
        for _ in range(5):
            headers, payload = self._github("GET", url, token=token)
            if not isinstance(payload, list):
                raise RuntimeError("GitHub did not return repositories")
            for repo in payload:
                if not isinstance(repo, dict) or repo.get("archived"):
                    continue
                full_name = str(repo.get("full_name") or "")
                try:
                    self._repo_dir(full_name)
                except RuntimeError:
                    continue
                names.append(full_name)
            link = headers.get("Link") or headers.get("link") or ""
            nxt = ""
            for part in link.split(","):
                if 'rel="next"' in part:
                    nxt = part.split(";")[0].strip().strip("<>")
            if not nxt:
                break
            url = nxt
        return names

    def status(self, user_id: UUID) -> dict:
        if not self.configured():
            return {"configured": False, "connected": False, "login": None, "project": None, "repos": []}
        found = self._connection(user_id)
        if found is None:
            return {"configured": True, "connected": False, "login": None, "project": None, "repos": []}
        chosen = set(self.selected_repos(user_id))
        listed = self.list_repos(found.token)
        names = list(dict.fromkeys(listed + sorted(chosen - set(listed))))
        repos = [{"full_name": name, "selected": name in chosen} for name in names]
        return {"configured": True, "connected": True, "login": found.login, "project": found.project or None, "repos": repos}

    def save_repos(self, user_id: UUID, project: str, names: list[str]) -> None:
        found = self._connection(user_id)
        if found is None:
            raise RuntimeError("GitHub is not connected")
        project_name = project.strip()
        if not _PROJECT_NAME.match(project_name):
            raise RuntimeError("invalid project name")
        clean = []
        seen: set[str] = set()
        for name in names:
            self._repo_dir(name)
            if name in seen:
                continue
            seen.add(name)
            clean.append(name)
        allowed = set(self.list_repos(found.token))
        unknown = [name for name in clean if name not in allowed]
        if unknown:
            raise RuntimeError("repository is not granted: {0}".format(unknown[0]))
        with db.get_pool().connection() as conn:
            project_id = upsert_project(conn, user_id, project_name)
            conn.execute(
                "UPDATE github_connections SET project_name = %s, project_id = %s WHERE user_id = %s",
                (project_name, project_id, user_id),
            )
            conn.execute("DELETE FROM github_repos WHERE user_id = %s", (user_id,))
            for name in clean:
                conn.execute(
                    "INSERT INTO github_repos (user_id, project_id, full_name) VALUES (%s, %s, %s)",
                    (user_id, project_id, name),
                )
            conn.commit()

    def _repo_dir(self, full_name: str) -> str:
        if not _REPO_NAME.match(full_name):
            raise RuntimeError("invalid repository")
        name = full_name.split("/", 1)[1]
        if name in {".", ".."} or name.startswith("-"):
            raise RuntimeError("invalid repository")
        return name

    def _has_ref(self, cwd, token: str | None, ref: str) -> bool:
        try:
            self.git(cwd, token, "rev-parse", "--verify", "--quiet", ref)
        except RuntimeError:
            return False
        return True

    def _checkout_work_branch(self, dest, token: str) -> None:
        remote = "origin/" + self.WORK_BRANCH
        if not self._has_ref(dest, token, "refs/remotes/" + remote):
            self.git(dest, token, "checkout", "-B", self.WORK_BRANCH)
            return
        if self._has_ref(dest, token, "refs/heads/" + self.WORK_BRANCH):
            self.git(dest, token, "checkout", self.WORK_BRANCH)
            self.git(dest, token, "merge", "--ff-only", remote)
            return
        self.git(dest, token, "checkout", "-B", self.WORK_BRANCH, remote)

    def _run_git(self, cwd, token: str | None, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        command = ["git"]
        if token:
            command.extend(["-c", "http.extraheader=AUTHORIZATION: bearer {0}".format(token)])
        return subprocess.run(command + list(args), cwd=cwd, capture_output=True, text=True)

    def git(self, cwd, token: str | None, *args: str) -> str:
        result = self._run_git(cwd, token, args)
        detail = (result.stderr or result.stdout or "").lower()
        rejected = "could not read username" in detail or "authentication failed" in detail or "invalid username or token" in detail
        if result.returncode != 0 and token and rejected:
            result = self._run_git(cwd, None, args)
        if result.returncode != 0:
            lines = (result.stderr or result.stdout or "git failed").strip().splitlines()
            raise RuntimeError(lines[-1] if lines else "git failed")
        return result.stdout

    def project_repos(self, user_id: UUID, project_id: UUID) -> list[str]:
        with db.get_pool().connection() as conn:
            rows = conn.execute(
                """
                SELECT full_name FROM github_repos
                WHERE user_id = %s AND project_id = %s
                ORDER BY full_name
                """,
                (user_id, project_id),
            ).fetchall()
        names = [str(row["full_name"]) for row in rows]
        for repo in CATALOG_REPOS.get(project_name(project_id) or "", ()):
            if repo not in names:
                names.append(repo)
        return names

    def prepare(self, user_id: UUID, project_id: UUID | None = None) -> config.Checkout | None:
        found = self._connection(user_id)
        if project_id is None:
            if found is None:
                return None
            repos = self.selected_repos(user_id)
            project = found.project
            if not project:
                raise RuntimeError("name the project in Settings")
            if not repos:
                raise RuntimeError("choose GitHub repositories in Settings")
        else:
            project = project_name(project_id) or ""
            repos = self.project_repos(user_id, project_id)
            if not project:
                raise RuntimeError("name the project in Settings")
            if not repos:
                return None
            catalog = set(CATALOG_REPOS.get(project, ()))
            if found is None and any(repo not in catalog for repo in repos):
                raise RuntimeError("GitHub is not connected")
        token = found.token if found is not None else None
        root = config.projects_root() / str(user_id) / project
        root.mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        dirs: list[tuple[str, str]] = []
        for full_name in repos:
            name = self._repo_dir(full_name)
            if name in seen:
                raise RuntimeError("two repositories share the name {0}".format(name))
            seen.add(name)
            dirs.append((full_name, name))
        for full_name, name in dirs:
            dest = root / name
            remote = "https://github.com/{0}.git".format(full_name)
            if not (dest / ".git").is_dir():
                self.git(root, token, "clone", "--origin", "origin", "--", remote, name)
            else:
                self.git(dest, token, "fetch", "--prune", "origin")
            self._checkout_work_branch(dest, token)
        return config.Checkout(root=root, token=token, branch=self.WORK_BRANCH)

    @contextmanager
    def checkout_for(self, user_id: UUID, project_id: UUID | None = None):
        prepared = self.prepare(user_id, project_id)
        if prepared is None:
            yield
            return
        token = config.activate_checkout(prepared)
        try:
            yield
        finally:
            config.restore_checkout(token)


def upsert_project(conn, user_id: UUID, name: str) -> UUID:
    row = conn.execute(
        """
        INSERT INTO projects (user_id, name) VALUES (%s, %s)
        ON CONFLICT (user_id, name) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (user_id, name),
    ).fetchone()
    return row["id"]


def list_projects(user_id: UUID) -> list[dict]:
    with db.get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.name, c.org, c.product_name
            FROM projects p
            LEFT JOIN project_contexts c ON c.project_id = p.id
            WHERE p.user_id = %s
            ORDER BY p.name
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def active_project_id(user_id: UUID) -> UUID | None:
    if db.pool is None:
        return None
    with db.get_pool().connection() as conn:
        row = conn.execute(
            "SELECT project_id FROM github_connections WHERE user_id = %s",
            (user_id,),
        ).fetchone()
    if row is None or row["project_id"] is None:
        return None
    return row["project_id"]


def project_name(project_id: UUID) -> str | None:
    with db.get_pool().connection() as conn:
        row = conn.execute("SELECT name FROM projects WHERE id = %s", (project_id,)).fetchone()
    if row is None:
        return None
    return str(row["name"])


def project_context(project_id: UUID) -> str | None:
    with db.get_pool().connection() as conn:
        row = conn.execute(
            "SELECT codebase_context FROM project_contexts WHERE project_id = %s",
            (project_id,),
        ).fetchone()
    if row is None:
        return None
    return str(row["codebase_context"])


def catalog_context(product_name: str) -> tuple[str, str, str] | None:
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT org, codebase_context, tech_stack
            FROM project_contexts
            WHERE project_id IS NULL AND product_name = %s
            """,
            (product_name,),
        ).fetchone()
    if row is None:
        return None
    return str(row["org"]), str(row["codebase_context"]), str(row["tech_stack"])


def save_project_context(project_id: UUID, user_id: UUID, codebase_context: str, tech_stack: str, org: str, product_name: str) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO project_contexts (project_id, user_id, org, product_name, codebase_context, tech_stack)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id) WHERE project_id IS NOT NULL
            DO UPDATE
            SET user_id = EXCLUDED.user_id,
                org = EXCLUDED.org,
                product_name = EXCLUDED.product_name,
                codebase_context = EXCLUDED.codebase_context,
                tech_stack = EXCLUDED.tech_stack,
                updated_at = now()
            """,
            (project_id, user_id, org, product_name, codebase_context, tech_stack),
        )
        conn.commit()


github = GithubConnection()
