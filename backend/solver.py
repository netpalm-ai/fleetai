"""Fix unresolved tickets."""

from __future__ import annotations

import json
from uuid import UUID

import intakes
from config import (
    BLOCKED,
    COMPLETED,
    READY,
    UNRESOLVED,
    VERIFYING,
    locked,
    require_ticket,
    run_step,
    tech_ticket,
)


def ticket_prompt(ticket: dict, context: str) -> str:
    return """
Fix this ticket. Follow ENGINEERING STANDARD. Follow CODE CONTEXT for this product. Do not invent requirements.
Process sentences in the ticket are not work. Do not implement them.
If CODE CONTEXT names a required branch and HEAD is not on it, stop.
If the item is not a software defect, the evidence contradicts the ticket, or the behaviour is already in the tree, do not patch.
Add a focused test when the change is code.
Before VERDICT: ready, list each named item as done, not done, or deferred. Silence is not ready. Partly done is not ready.
Then exactly one line: VERDICT: ready   or   VERDICT: blocked

TICKET
{ticket}

{context}
""".strip().format(ticket=json.dumps(tech_ticket(ticket), indent=2), context=context)


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
    run_step(user_id, ticket_id, UNRESOLVED, "solve", ticket_prompt, {READY: VERIFYING}, BLOCKED)


@locked
def solve_tickets(user_id: UUID) -> None:
    tickets = [item for item in intakes.open_tickets(user_id) if item["status"] == UNRESOLVED]
    if not tickets:
        print("no unresolved tickets")
        return
    for ticket in tickets:
        print("solving {0}".format(ticket["id"]), flush=True)
        solve(user_id, ticket["id"])
