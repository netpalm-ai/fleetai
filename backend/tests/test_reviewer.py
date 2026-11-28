"""Page-by-page and script-by-script reviewer for self-improve."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import reviewer


class ReviewerTests(unittest.TestCase):
    def test_audit_walks_each_page(self) -> None:
        calls = {"n": 0}

        def ask(prompt: str) -> str:
            calls["n"] += 1
            page = reviewer.PAGES[calls["n"] - 1]
            self.assertIn(page["route"], prompt)
            self.assertIn(page["files"][0], prompt)
            return json.dumps({"kind": "page", "path": page["route"], "ok": True})

        with TemporaryDirectory() as raw:
            clone = Path(raw)
            for page in reviewer.PAGES:
                for relative in page["files"]:
                    path = clone / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("// {0}\n".format(relative), encoding="utf-8")
            with patch.object(reviewer, "_ask", side_effect=ask), patch.object(
                reviewer.db, "prevent_lines", return_value="(none)"
            ):
                findings = reviewer.audit_pages(clone, "improve the product")
        self.assertEqual(calls["n"], len(reviewer.PAGES))
        self.assertEqual([item["path"] for item in findings], [page["route"] for page in reviewer.PAGES])

    def test_list_and_audit_scripts(self) -> None:
        with TemporaryDirectory() as raw:
            clone = Path(raw)
            (clone / "frontend" / "src" / "pages").mkdir(parents=True)
            (clone / "frontend" / "src" / "pages" / "HomePage.tsx").write_text("export {}", encoding="utf-8")
            (clone / "backend").mkdir()
            (clone / "backend" / "api.py").write_text("x=1\n", encoding="utf-8")
            (clone / "backend" / "tests").mkdir()
            (clone / "backend" / "tests" / "test_api.py").write_text("x=1\n", encoding="utf-8")
            (clone / "backend" / "auth").mkdir()
            (clone / "backend" / "auth" / "routes.py").write_text("x=1\n", encoding="utf-8")
            scripts = reviewer.list_scripts(clone)
            self.assertEqual(
                scripts,
                [
                    "backend/api.py",
                    "backend/auth/routes.py",
                    "frontend/src/pages/HomePage.tsx",
                ],
            )
            seen: list[str] = []

            def ask(prompt: str) -> str:
                path = [item for item in scripts if item in prompt][0]
                seen.append(path)
                return json.dumps({"kind": "script", "path": path, "ok": True})

            with patch.object(reviewer, "_ask", side_effect=ask), patch.object(
                reviewer.db, "prevent_lines", return_value="(none)"
            ):
                findings = reviewer.audit_scripts(clone, "improve scripts")
        self.assertEqual(seen, scripts)
        self.assertTrue(all(item["ok"] for item in findings))

    def test_review_to_tickets_runs_pages_then_scripts(self) -> None:
        order: list[str] = []

        def pages(clone, instruction):
            order.append("pages")
            return [{"kind": "page", "path": "/", "ok": True}]

        def scripts(clone, instruction):
            order.append("scripts")
            return [{"kind": "script", "path": "backend/api.py", "ok": False, "problems": ["csrf"], "fix": "add csrf"}]

        with patch.object(reviewer, "audit_pages", side_effect=pages), patch.object(
            reviewer, "audit_scripts", side_effect=scripts
        ), patch.object(
            reviewer,
            "plan_tickets",
            return_value='[{"id":"csrf","title":"CSRF","severity":"high","services":[],"context":"api.py","expected":"csrf"}]',
        ) as plan:
            text = reviewer.review_to_tickets(Path("/tmp"), "harden api", "CTX", [])
        self.assertEqual(order, ["pages", "scripts"])
        self.assertIn("csrf", text)
        self.assertEqual(plan.call_args.args[0][1]["path"], "backend/api.py")

    def test_plan_tickets_asks_with_findings(self) -> None:
        findings = [{"kind": "page", "path": "/signup", "ok": False, "problems": ["sidebar"], "fix": "drop shell"}]
        with patch.object(
            reviewer,
            "_ask",
            return_value='[{"id":"fix-signup","title":"Signup","severity":"high","services":[],"context":"AppShell","expected":"no sidebar"}]',
        ) as ask:
            text = reviewer.plan_tickets(findings, "fix signup", "CODE", ["T1"])
        self.assertIn("fix-signup", text)
        self.assertIn("/signup", ask.call_args.args[0])
