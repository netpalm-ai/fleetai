"""Page-by-page reviewer for self-improve."""

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
            return json.dumps({"route": page["route"], "ok": True})

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
        self.assertEqual([item["route"] for item in findings], [page["route"] for page in reviewer.PAGES])

    def test_plan_tickets_asks_with_findings(self) -> None:
        findings = [{"route": "/signup", "ok": False, "problems": ["sidebar"], "fix": "drop shell"}]
        with patch.object(
            reviewer,
            "_ask",
            return_value='[{"id":"fix-signup","title":"Signup","severity":"high","services":[],"context":"AppShell","expected":"no sidebar"}]',
        ) as ask:
            text = reviewer.plan_tickets(findings, "fix signup", "CODE", ["T1"])
        self.assertIn("fix-signup", text)
        self.assertIn("/signup", ask.call_args.args[0])
