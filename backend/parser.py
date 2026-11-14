"""Read the report and write tickets/unsolved_tickets.json."""

from __future__ import annotations

import json

import pymupdf

from config import (
    ADDITIONAL_CONTEXT_PATH,
    CONTEXT_MD_PATH,
    EMAIL_PATH,
    LIST_TEXT_PATH,
    PDF_PATH,
    TICKETS_PATH,
    apply_workflow,
    load_tickets,
    locked,
    normalize_tickets,
    product_areas,
    save_tickets,
    solved_prompt,
    ticket_where,
)
from llm import bedrock, ollama

PROMPT = """Extract unsolved software defects from a source email and/or a bug-report PDF. Additional context is optional. A missing additional-context document is normal and is not a reason to skip tickets.

Use whichever of the email and the bug report are present. Either one of those two is enough. If both are present, use the email for defect facts only. Ignore process asks in both. Do not require additional context.

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

ADDITIONAL CONTEXT
Optional. If this section is "(none)", ignore it and decide the tickets from the email and the bug report only.
If text is present, use it as evidence for a defect the email or the bug report already names. It may fill context and expected. It may also show that a listed item is not a software defect, in which case omit that item. Do not create a ticket that only this section names.
{{additional_context}}
"""


def email_text() -> str:
    if not EMAIL_PATH.is_file():
        return ""
    return EMAIL_PATH.read_text(encoding="utf-8").strip()


def _pdf_text(path) -> str:
    if not path.is_file():
        return ""
    document = pymupdf.open(path)
    text = "\n".join(page.get_text() for page in document).strip()
    document.close()
    return text


def report_text() -> str:
    if LIST_TEXT_PATH.is_file():
        return LIST_TEXT_PATH.read_text(encoding="utf-8").strip()
    return _pdf_text(PDF_PATH)


def additional_context_text() -> str:
    if CONTEXT_MD_PATH.is_file():
        return CONTEXT_MD_PATH.read_text(encoding="utf-8").strip()
    return _pdf_text(ADDITIONAL_CONTEXT_PATH)


@locked
def get_tickets() -> list[dict]:
    email = email_text()
    report = report_text()
    if not email and not report:
        raise RuntimeError("need an email or a ticket list")
    raw_additional = additional_context_text()
    additional = ollama.summarize(raw_additional)
    if raw_additional and len(additional) != len(raw_additional):
        print("Summarized additional context {0} -> {1} chars".format(len(raw_additional), len(additional)))
    body = bedrock.complete(
        PROMPT.replace("{{email}}", email or "(none)").replace("{{report}}", report or "(none)").replace("{{additional_context}}", additional or "(none)").replace("{{product_areas}}", product_areas()).replace("{{solved}}", solved_prompt())
    )
    if body.startswith("```"):
        body = body.split("\n", 1)[1].removesuffix("```").strip()
    tickets = apply_workflow(normalize_tickets(json.loads(body)), load_tickets())
    save_tickets(tickets)
    return tickets


def print_tickets(tickets: list[dict]) -> None:
    print("Wrote {0} ({1} tickets)".format(TICKETS_PATH, len(tickets)))
    for ticket in tickets:
        print("{0}\t{1}\t{2}".format(ticket["id"], ticket["status"], ticket_where(ticket)))
