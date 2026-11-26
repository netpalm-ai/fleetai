"""Review verifying tickets, repair bugs the solver introduced, then set fixed."""

from __future__ import annotations

import json
from uuid import UUID

import intakes
from config import FAILED, FIXED, UNRESOLVED, VERIFYING, locked, run_step, tech_ticket


def verify_prompt(ticket: dict, context: str) -> str:
    return """
Review the solver change for this ticket. Do not commit, push, or deploy. Preserve existing uncommitted work.
Do not delete a database record. Do not write SQL that removes rows, truncates a table, drops stored data, or otherwise destroys a database. Do not run a test, script, or migration against a database that already holds records.
TICKET.expected is the bar. Run CODE CONTEXT tests for every repo the solver diff touches, the way CI runs them, plus adjacent consumers CODE CONTEXT names — not only the ticket's own test file. Opposite cases too.
If the change introduced a bug, fix that bug and re-check. Repeat until expected still holds and no new bug remains.
Hunt incurred bugs: adjacent behaviour compiled away, a new write that the operator-facing surface still shows as a generic HTTP verb, sensitive payloads in logs, a test that still mocks a deleted import, tests that pass only because a CI service is missing, CI or deploy files edited when the ticket did not name them, domain rules or identifier tables added in the wrong layer, extra wrappers or files, and a client that compiles in behaviour an upstream payload cannot yet produce unless the ticket said fail-closed and listed that item not done.
Fail if named ticket items were not listed as done, not done, or deferred, or if a named behaviour was dropped and not listed.
Also refine the solver diff: drop unnecessary blocks (for example a heavy try/except around simple code), and reuse existing functions, types, and paths instead of adding a parallel copy. Do not rewrite unrelated code.
Other than that, you must fix. Do not mark it resolved while a new bug or that extra complexity is still in the tree.
Do not paste secrets, customer payloads, or source documents into the result.
Only then exactly one line: VERDICT: fixed. If you cannot make it okay, VERDICT: failed.
Process asks, screenshots, and status tables are not the bar. Ignore them.

TICKET
{ticket}

{context}
""".strip().format(ticket=json.dumps(tech_ticket(ticket), indent=2), context=context)


@locked
def verify(user_id: UUID, ticket_id: str) -> None:
    run_step(user_id, ticket_id, VERIFYING, "verify", verify_prompt, {FIXED: FIXED, FAILED: UNRESOLVED})


@locked
def verify_tickets(user_id: UUID) -> None:
    tickets = [item for item in intakes.open_tickets(user_id) if item["status"] == VERIFYING]
    if not tickets:
        print("no verifying tickets")
        return
    for ticket in tickets:
        print("verifying {0}".format(ticket["id"]), flush=True)
        verify(user_id, ticket["id"])
