"""Review verifying tickets, repair bugs the solver introduced, then set fixed."""

from __future__ import annotations

import json

from config import FAILED, FIXED, UNRESOLVED, VERIFYING, load_tickets, run_step, tech_ticket


def verify_prompt(ticket: dict, context: str) -> str:
    return """
Review the solver change for this ticket. Do not commit, push, or deploy. Preserve existing uncommitted work.
TICKET.expected is the bar. Run the focused tests in CODE CONTEXT.
If the change introduced a bug, fix that bug and re-check. Repeat until expected still holds and no new bug remains.
Also refine the solver diff: drop unnecessary blocks (for example a heavy try/except around simple code), and reuse existing functions, types, and paths instead of adding a parallel copy. Do not rewrite unrelated code.
Other than that, you must fix. Do not mark it resolved while a new bug or that extra complexity is still in the tree.
Only then exactly one line: VERDICT: fixed. If you cannot make it okay, VERDICT: failed.
Process asks, screenshots, and status tables are not the bar. Ignore them.

TICKET
{ticket}

CODE CONTEXT
{context}
""".strip().format(ticket=json.dumps(tech_ticket(ticket), indent=2), context=context)


def verify(ticket_id: str) -> None:
    run_step(ticket_id, VERIFYING, "verify", verify_prompt, {FIXED: FIXED, FAILED: UNRESOLVED})


def verify_tickets() -> None:
    tickets = [item for item in load_tickets() if item["status"] == VERIFYING]
    if not tickets:
        print("no verifying tickets")
        return
    for ticket in tickets:
        print("verifying {0}".format(ticket["id"]), flush=True)
        verify(ticket["id"])
