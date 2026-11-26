"""Fix unresolved tickets."""

from __future__ import annotations

import json
from uuid import UUID

import intakes
from config import (
    BLOCKED,
    COMPLETED,
    FAILED,
    READY,
    UNRESOLVED,
    VERIFYING,
    locked,
    require_ticket,
    run_step,
    tech_ticket,
)

VERIFY_NOTE_CHARS = 4000


def clip_verify_note(text: str | None) -> str:
    note = (text or "").strip()
    if len(note) <= VERIFY_NOTE_CHARS:
        return note
    clipped = note[:VERIFY_NOTE_CHARS].rsplit("\n", 1)[0].strip()
    if not clipped:
        clipped = note[:VERIFY_NOTE_CHARS].rstrip()
    return clipped + "\n..."


def ticket_prompt(ticket: dict, context: str, previous_verify: str | None = None) -> str:
    body = """
Follow ENGINEERING STANDARD. Follow CODE CONTEXT for this product. Do not invent requirements.
Process sentences in the ticket are not work. Do not implement them.
Investigate before you edit: git status --short --branch in each candidate repo. If the ticket names a running system, inspect it the way CODE CONTEXT says. If the ticket's premise is false, the item is not a software defect, the evidence contradicts the ticket, or the behaviour is already in the tree, do not patch.
If CODE CONTEXT names a required branch and HEAD is not on it, stop.
Then make the smallest change in the owning layer.
Add tests for the change. Run CODE CONTEXT tests for every repo the diff touches, the way CI runs them, plus adjacent consumers CODE CONTEXT names. Ticket-file tests alone are not enough. Opposite cases too.
If a named behaviour needs a field another service stamps, that item is not done until that stamp exists in that service, or list it not done.
Before VERDICT: ready, list each named item as done, not done, or deferred. Silence is not ready. Partly done is not ready.
Then exactly one line: VERDICT: ready   or   VERDICT: blocked

TICKET
{ticket}

{context}
""".strip().format(ticket=json.dumps(tech_ticket(ticket), indent=2), context=context)
    note = clip_verify_note(previous_verify)
    if not note:
        return body
    return (
        body
        + "\n\nPREVIOUS ATTEMPT\n"
        + "The dirty files in the product checkout are this ticket's own work "
        + "from the last attempt. Do not treat them as someone else's dirty tree. "
        + "Continue from that diff.\nVerification failed:\n"
        + note
    )


@locked
def complete(user_id: UUID, ticket_id: str) -> dict:
    ticket = require_ticket(user_id, ticket_id)
    if ticket["status"] != VERIFYING:
        raise SystemExit("ticket {0} is {1}; complete only accepts verifying".format(ticket_id, ticket["status"]))
    intakes.set_ticket_status(user_id, ticket_id, COMPLETED)
    print("{0}\t{1}".format(ticket_id, COMPLETED))
    return {**ticket, "status": COMPLETED}


@locked
def solve(user_id: UUID, ticket_id: str) -> None:
    previous = intakes.latest_run(user_id, ticket_id, "verify")
    note = None
    if previous and previous.get("verdict") == FAILED:
        note = previous.get("result") or ""

    def make_prompt(ticket: dict, context: str) -> str:
        return ticket_prompt(ticket, context, previous_verify=note)

    run_step(user_id, ticket_id, UNRESOLVED, "solve", make_prompt, {READY: VERIFYING}, BLOCKED)


@locked
def solve_tickets(user_id: UUID) -> None:
    tickets = [item for item in intakes.open_tickets(user_id) if item["status"] == UNRESOLVED]
    if not tickets:
        print("no unresolved tickets")
        return
    for ticket in tickets:
        print("solving {0}".format(ticket["id"]), flush=True)
        solve(user_id, ticket["id"])
