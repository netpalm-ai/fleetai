"""Read the report and write tickets/unsolved_tickets.json."""

from __future__ import annotations

import json
import os

import boto3
import pymupdf

from config import (
    EMAIL_PATH,
    PDF_PATH,
    TICKETS_PATH,
    apply_workflow,
    load_tickets,
    normalize_tickets,
    product_areas,
    save_tickets,
    solved_prompt,
    ticket_where,
)

PROMPT = """Extract unsolved software defects from a source email and/or a bug-report PDF.

Use whichever sources are present. Either one is enough. If both are present, use the email for defect facts only. Ignore process asks in both.

Business labels (Open, Partially Fixed, Not Yet Fixed, closed, deferred) and process asks (retest lists, deployment dates, build numbers, status tables, screenshots, eval readiness) are not this system's workflow and not engineering work. Do not copy them into the ticket.

This system only uses unresolved, verifying, and fixed. You do not set those.

Return a JSON array. Each object must use this format only:
- id: the source id if it names one, otherwise a short slug from the title
- title
- severity
- kind: "new", unless this id was already fixed and the source reports a test of it that already ran and did not match expected behaviour, then "recurrent"
- services: names from PRODUCT AREAS when the defect matches them, else []
- context: the software defect only
- expected: the technical expected behaviour only

Include a defect even if the source gave it no id. Do not invent defects, next steps, or fixes. Do not include report_status or kind_reason.

PREVIOUSLY SOLVED
These ids are already fixed in this system. That archive is the only closed that matters. Decide in ordinary language, not by matching stock phrases.

If the writer already tested this id and the product did not do what was expected, include it. Set kind to "recurrent". In context, say what they tried and what they observed. A session id is useful if they gave one.

If they only list the id, want it retested, want screenshots or logs, or say testing will happen later, omit it. Do not restate the original archived defect.
{{solved}}

PRODUCT AREAS
{{product_areas}}

EMAIL
{{email}}

BUG REPORT
{{report}}
"""


def email_text() -> str:
    if not EMAIL_PATH.is_file():
        return ""
    return EMAIL_PATH.read_text(encoding="utf-8").strip()


def report_text() -> str:
    if not PDF_PATH.is_file():
        return ""
    document = pymupdf.open(PDF_PATH)
    text = "\n".join(page.get_text() for page in document).strip()
    document.close()
    return text


def get_tickets() -> list[dict]:
    region = (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "").strip()
    if not region:
        raise RuntimeError("AWS_REGION is required")
    email = email_text()
    report = report_text()
    if not email and not report:
        raise RuntimeError("need tickets/email.desc.txt or tickets/list.pdf")
    body = boto3.client("bedrock-runtime", region_name=region).converse(
        modelId=(os.getenv("BEDROCK_MODEL_ID") or "us.anthropic.claude-sonnet-4-6").strip(),
        messages=[{
            "role": "user",
            "content": [{"text": PROMPT.replace("{{email}}", email or "(none)").replace("{{report}}", report or "(none)").replace("{{product_areas}}", product_areas()).replace("{{solved}}", solved_prompt())}],
        }],
        inferenceConfig={"temperature": 0, "maxTokens": 16000},
    )["output"]["message"]["content"][0]["text"].strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1].removesuffix("```").strip()
    tickets = apply_workflow(normalize_tickets(json.loads(body)), load_tickets())
    save_tickets(tickets)
    return tickets


def print_tickets(tickets: list[dict]) -> None:
    print("Wrote {0} ({1} tickets)".format(TICKETS_PATH, len(tickets)))
    for ticket in tickets:
        print("{0}\t{1}\t{2}".format(ticket["id"], ticket["status"], ticket_where(ticket)))
