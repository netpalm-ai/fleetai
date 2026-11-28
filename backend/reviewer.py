"""Page-by-page and script-by-script review for self-improve, then tickets."""

from __future__ import annotations

import json
from pathlib import Path

import db

_MAX = 4000
_SCRIPT_CHARS = 12000

# Product surfaces a human would click through, in order.
PAGES = (
    {
        "id": "home",
        "route": "/",
        "files": ("frontend/src/pages/HomePage.tsx", "frontend/src/App.tsx"),
    },
    {
        "id": "login",
        "route": "/login",
        "files": ("frontend/src/pages/LoginPage.tsx", "frontend/src/App.tsx"),
    },
    {
        "id": "signup",
        "route": "/signup",
        "files": ("frontend/src/pages/SignUpPage.tsx", "frontend/src/App.tsx"),
    },
    {
        "id": "verify",
        "route": "/verify",
        "files": ("frontend/src/pages/VerifyPage.tsx",),
    },
    {
        "id": "forgot",
        "route": "/forgot",
        "files": ("frontend/src/pages/ForgotPasswordPage.tsx",),
    },
    {
        "id": "reset",
        "route": "/reset",
        "files": ("frontend/src/pages/ResetPasswordPage.tsx",),
    },
    {
        "id": "terms",
        "route": "/terms",
        "files": ("frontend/src/pages/TermsPage.tsx",),
    },
    {
        "id": "workspace",
        "route": "/workspace",
        "files": (
            "frontend/src/pages/WorkspacePage.tsx",
            "frontend/src/components/AppShell.tsx",
            "frontend/src/App.tsx",
        ),
    },
    {
        "id": "connectors",
        "route": "/connectors",
        "files": ("frontend/src/pages/SettingsPage.tsx", "frontend/src/components/AppShell.tsx"),
    },
    {
        "id": "settings",
        "route": "/settings",
        "files": ("frontend/src/pages/SettingsPage.tsx", "frontend/src/components/AppShell.tsx"),
    },
)

_SCRIPT_DIRS = (
    ("frontend/src", (".ts", ".tsx")),
    ("backend", (".py",)),
    ("backend/auth", (".py",)),
)

_SKIP_NAME = {
    "test_api.py",
    "test_auth.py",
    "test_github.py",
    "test_intakes.py",
    "test_reviewer.py",
    "test_selflooper.py",
    "test_watcher.py",
    "test_workflow.py",
}

_PAGE = """You are reviewing FleetAI like a staff engineer doing a product walkthrough.
This is page {index}/{total}: {route} ({page_id}).
Read every file listed below in the checkout. Also read frontend/AGENTS.md and follow PREVENT.
Do not edit files. Do not commit, push, or deploy.

Judge this page alone: layout, information architecture, copy, routing/shell, and whether it matches a normal product page of this kind.
Public auth/intro pages must not show the signed-in product sidebar. Signed-in pages use AppShell.
Do not invent features. Prefer concrete code problems over taste essays.

PREVENT
{prevent}

OPERATOR INSTRUCTION (context for what they care about)
{instruction}

FILES
{files}

Return JSON only:
{{"kind":"page","path":"{route}","ok":true}}
or
{{"kind":"page","path":"{route}","ok":false,"problems":["..."],"fix":"one concrete fix for this page"}}
"""

_SCRIPT = """You are reviewing one FleetAI script like a staff engineer before deciding what to improve.
This is script {index}/{total}: {path}
Read the file below. Follow PREVENT and, for frontend files, frontend/AGENTS.md / DEV RULES.
Do not edit files. Do not commit, push, or deploy.

Judge this script alone: correctness, security, dead/duplicated code, wrong layer, product naming,
and whether it should change for the operator instruction. Prefer concrete problems. Do not invent
features. If the script is fine, say ok.

PREVENT
{prevent}

OPERATOR INSTRUCTION (context for what they care about)
{instruction}

FILE
{path}
{body}

Return JSON only:
{{"kind":"script","path":"{path}","ok":true}}
or
{{"kind":"script","path":"{path}","ok":false,"problems":["..."],"fix":"one concrete fix for this script"}}
"""

_PLAN = """You finished a FleetAI walkthrough: every product page, then every product script.
Decide which findings deserve work. Do not edit files. Do not commit, push, or deploy. Follow PREVENT.

Findings (JSON array; kind is page or script):
{findings}

OPERATOR INSTRUCTION
{instruction}

CODE CONTEXT
{context}

EXISTING IDS
{existing}

Rules:
- Only ticket scripts/pages that are not ok. Prefer the operator instruction, but always ticket clear
  PREVENT, AGENTS.md, or security violations even if the operator did not name them.
- Smallest set of tickets. Do not invent work the findings do not support.
- Name the files to edit in context.

Return a JSON array only. Each object must have:
- id: a new short slug. Do not reuse an existing id
- title
- severity
- services: names from CODE CONTEXT, else []
- context: the change, naming the files to edit
- expected: the behaviour after the change
"""


def _clip(text: str, limit: int = _MAX) -> str:
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit]


def _ask(prompt: str) -> str:
    from llm import cursor

    result = cursor.run(prompt)
    return (result.result or "").strip()


def _json_object(text: str) -> dict:
    body = (text or "").strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1].removesuffix("```").strip()
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("review was not a JSON object")
    data = json.loads(body[start : end + 1])
    if not isinstance(data, dict):
        raise RuntimeError("review was not a JSON object")
    return data


def _read_files(clone: Path, files: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for relative in files:
        path = clone / relative
        if not path.is_file():
            chunks.append("{0}\n(missing)".format(relative))
            continue
        text = path.read_text(encoding="utf-8")
        if len(text) > _SCRIPT_CHARS:
            text = text[:_SCRIPT_CHARS] + "\n..."
        chunks.append("{0}\n{1}".format(relative, text))
    return "\n\n".join(chunks)


def _skip_script(relative: str) -> bool:
    name = Path(relative).name
    if name in _SKIP_NAME or name.startswith("test_"):
        return True
    parts = relative.split("/")
    return "tests" in parts or "migrations" in parts or "__pycache__" in parts or "node_modules" in parts


def list_scripts(clone: Path) -> list[str]:
    found: list[str] = []
    for root, suffixes in _SCRIPT_DIRS:
        base = clone / root
        if not base.is_dir():
            continue
        if root == "backend":
            for path in sorted(base.iterdir()):
                if path.is_file() and path.suffix in suffixes:
                    relative = path.relative_to(clone).as_posix()
                    if not _skip_script(relative):
                        found.append(relative)
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix in suffixes:
                relative = path.relative_to(clone).as_posix()
                if not _skip_script(relative):
                    found.append(relative)
    # stable unique
    return sorted(set(found))


def audit_pages(clone: Path, instruction: str) -> list[dict]:
    prevent = db.prevent_lines()
    scoped = _clip(instruction)
    findings: list[dict] = []
    total = len(PAGES)
    for index, page in enumerate(PAGES, start=1):
        print("review page {0} {1}".format(page["route"], page["id"]), flush=True)
        answer = _ask(
            _PAGE.format(
                index=index,
                total=total,
                route=page["route"],
                page_id=page["id"],
                prevent=prevent,
                instruction=scoped,
                files=_read_files(clone, page["files"]),
            )
        )
        try:
            item = _json_object(answer)
        except (RuntimeError, json.JSONDecodeError):
            findings.append(
                {
                    "kind": "page",
                    "path": page["route"],
                    "ok": False,
                    "problems": ["page review did not return JSON"],
                    "fix": "Re-review {0} and fix concrete product issues.".format(page["route"]),
                }
            )
            continue
        item["kind"] = "page"
        item["path"] = page["route"]
        findings.append(item)
    return findings


def audit_scripts(clone: Path, instruction: str) -> list[dict]:
    prevent = db.prevent_lines()
    scoped = _clip(instruction)
    scripts = list_scripts(clone)
    findings: list[dict] = []
    total = len(scripts)
    for index, relative in enumerate(scripts, start=1):
        print("review script {0}".format(relative), flush=True)
        path = clone / relative
        body = path.read_text(encoding="utf-8") if path.is_file() else "(missing)"
        if len(body) > _SCRIPT_CHARS:
            body = body[:_SCRIPT_CHARS] + "\n..."
        answer = _ask(
            _SCRIPT.format(
                index=index,
                total=total,
                path=relative,
                prevent=prevent,
                instruction=scoped,
                body=body,
            )
        )
        try:
            item = _json_object(answer)
        except (RuntimeError, json.JSONDecodeError):
            findings.append(
                {
                    "kind": "script",
                    "path": relative,
                    "ok": False,
                    "problems": ["script review did not return JSON"],
                    "fix": "Re-review {0} and fix concrete issues.".format(relative),
                }
            )
            continue
        item["kind"] = "script"
        item["path"] = relative
        findings.append(item)
    return findings


def plan_tickets(findings: list[dict], instruction: str, context: str, existing: list[str]) -> str:
    return _ask(
        _PLAN.format(
            findings=json.dumps(findings, indent=2)[:16000],
            instruction=_clip(instruction),
            context=_clip(context, 8000),
            existing="\n".join(existing) or "(none)",
        )
    )


def review_to_tickets(clone: Path, instruction: str, context: str, existing: list[str]) -> str:
    findings = audit_pages(clone, instruction)
    findings.extend(audit_scripts(clone, instruction))
    print("review findings {0}".format(len(findings)), flush=True)
    return plan_tickets(findings, instruction, context, existing)
