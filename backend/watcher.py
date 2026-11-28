"""Cursor watcher for self-improve: recover from run failures and re-check the result."""

from __future__ import annotations

from pathlib import Path

import db

_MAX_ERROR = 4000
_MAX_INSTRUCTION = 4000

_RECOVER = """You are the FleetAI watcher. A self-improve run failed before it finished.
Fix only the blocker so the same instruction can run again. Do not implement the instruction.
Do not commit, push, or deploy. Preserve unrelated uncommitted work when you can.
Follow PREVENT. A line there is a mistake that must not be repeated.

Typical blockers: missing git user.name/user.email, a dirty FleetAI checkout left from a failed run,
a merge conflict leftover, or a tooling error in selflooper publish. Prefer a lasting code fix when
the bug is in FleetAI itself; reset only the FleetAI checkout dirt that blocks the next run.

PREVENT
{prevent}

INSTRUCTION
{instruction}

ERROR
{error}

When the blocker is fixed, end with exactly one line: WATCH: retry
If you cannot fix it, end with exactly one line: WATCH: fail
"""

_REVIEW = """You are the FleetAI watcher. Self-improve finished a pass. Walk the product page by page
(home, login, signup, verify, forgot, reset, terms, workspace, connectors, settings) and double-check
the checkout against the original instruction and PREVENT. Do not commit, push, or deploy. Do not edit
files in this step. Follow PREVENT. A line there is a mistake that must not be repeated.

Fail the pass if a public auth/intro page still shows the signed-in product sidebar, if Workspace was
renamed back to Tickets, or if a named instruction item is still wrong.

PREVENT
{prevent}

ORIGINAL INSTRUCTION
{original}

LAST INSTRUCTION RUN
{current}

If the original instruction is fully met and the page walk finds no PREVENT/AGENTS breach, end with
exactly one line: WATCH: ok
If gaps remain, end with:
WATCH: again
INSTRUCTION
<one follow-up instruction that names the pages that still fail and what to fix>
"""


def _clip(text: str, limit: int) -> str:
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit]


def _ask(prompt: str) -> str:
    from llm import cursor

    result = cursor.run(prompt)
    return (result.result or "").strip()


def _watch_line(text: str) -> str:
    for line in reversed((text or "").splitlines()):
        stripped = line.strip()
        if stripped.startswith("WATCH:"):
            return stripped[len("WATCH:") :].strip().lower()
    return ""


def recover(clone: Path, instruction: str, error: str) -> bool:
    if not (clone / ".git").is_dir():
        return False
    answer = _ask(
        _RECOVER.format(
            prevent=db.prevent_lines(),
            instruction=_clip(instruction, _MAX_INSTRUCTION),
            error=_clip(error, _MAX_ERROR),
        )
    )
    return _watch_line(answer) == "retry"


def review(clone: Path, original: str, current: str) -> str | None:
    if not (clone / ".git").is_dir():
        return None
    answer = _ask(
        _REVIEW.format(
            prevent=db.prevent_lines(),
            original=_clip(original, _MAX_INSTRUCTION),
            current=_clip(current, _MAX_INSTRUCTION),
        )
    )
    if _watch_line(answer) != "again":
        return None
    marker = "INSTRUCTION"
    start = answer.rfind(marker)
    if start < 0:
        return None
    body = answer[start + len(marker) :].strip()
    if body.lower().startswith("watch:"):
        return None
    follow = body.strip()
    if not follow or follow == current.strip() or follow == original.strip():
        return None
    return follow[:_MAX_INSTRUCTION]
