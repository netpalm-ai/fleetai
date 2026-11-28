"""Watcher recover/review parsing."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import watcher


class WatcherTests(unittest.TestCase):
    def test_recover_retries_when_watch_says_retry(self) -> None:
        with TemporaryDirectory() as raw:
            clone = Path(raw)
            (clone / ".git").mkdir()
            with patch.object(watcher, "_ask", return_value="fixed identity\nWATCH: retry"):
                self.assertTrue(watcher.recover(clone, "match sidebar", "missing git identity"))

    def test_recover_fails_when_watch_says_fail(self) -> None:
        with TemporaryDirectory() as raw:
            clone = Path(raw)
            (clone / ".git").mkdir()
            with patch.object(watcher, "_ask", return_value="cannot fix\nWATCH: fail"):
                self.assertFalse(watcher.recover(clone, "match sidebar", "boom"))

    def test_review_returns_follow_up(self) -> None:
        with TemporaryDirectory() as raw:
            clone = Path(raw)
            (clone / ".git").mkdir()
            answer = "gaps remain\nWATCH: again\nINSTRUCTION\nKeep /workspace; nest project folders like ChatGPT."
            with patch.object(watcher, "_ask", return_value=answer):
                follow = watcher.review(clone, "match ChatGPT sidebar", "match ChatGPT sidebar")
        self.assertEqual(follow, "Keep /workspace; nest project folders like ChatGPT.")

    def test_review_ok_returns_none(self) -> None:
        with TemporaryDirectory() as raw:
            clone = Path(raw)
            (clone / ".git").mkdir()
            with patch.object(watcher, "_ask", return_value="looks good\nWATCH: ok"):
                self.assertIsNone(watcher.review(clone, "match ChatGPT sidebar", "match ChatGPT sidebar"))
