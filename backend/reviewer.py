"""Page-by-page product review for self-improve, then turn findings into tickets."""

from __future__ import annotations

import json
from pathlib import Path

import db

_MAX = 4000

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
{{"route":"{route}","ok":true}}
or
{{"route":"{route}","ok":false,"problems":["..."],"fix":"one concrete fix for this page"}}
"""

_PLAN = """You finished a page-by-page walkthrough of FleetAI. Turn the findings into engineering tickets.
Do not edit files. Do not commit, push, or deploy. Follow PREVENT.

Walkthrough findings (JSON array, one object per page):
{findings}

OPERATOR INSTRUCTION
{instruction}

CODE CONTEXT
{context}

EXISTING IDS
{existing}

Rules:
- Cover real gaps from the walkthrough. Prefer the operator instruction, but always ticket clear PREVENT or AGENTS.md violations even if the operator did not name them.
- Skip pages that are ok.
- Smallest set of tickets. One page can be more than one ticket only when the fixes are separate.
- Do not invent work that the findings do not support.

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
        raise RuntimeError("page review was not a JSON object")
    data = json.loads(body[start : end + 1])
    if not isinstance(data, dict):
        raise RuntimeError("page review was not a JSON object")
    return data


def _read_files(clone: Path, files: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for relative in files:
        path = clone / relative
        if not path.is_file():
            chunks.append("{0}\n(missing)".format(relative))
            continue
        text = path.read_text(encoding="utf-8")
        if len(text) > 12000:
            text = text[:12000] + "\n..."
        chunks.append("{0}\n{1}".format(relative, text))
    return "\n\n".join(chunks)


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
                    "route": page["route"],
                    "ok": False,
                    "problems": ["page review did not return JSON"],
                    "fix": "Re-review {0} and fix concrete product issues.".format(page["route"]),
                }
            )
            continue
        item["route"] = page["route"]
        findings.append(item)
    return findings


def plan_tickets(findings: list[dict], instruction: str, context: str, existing: list[str]) -> str:
    return _ask(
        _PLAN.format(
            findings=json.dumps(findings, indent=2)[:12000],
            instruction=_clip(instruction),
            context=_clip(context, 8000),
            existing="\n".join(existing) or "(none)",
        )
    )


def review_to_tickets(clone: Path, instruction: str, context: str, existing: list[str]) -> str:
    findings = audit_pages(clone, instruction)
    print("review findings {0}".format(len(findings)), flush=True)
    return plan_tickets(findings, instruction, context, existing)
