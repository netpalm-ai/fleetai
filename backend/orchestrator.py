"""Parse, then solve, then verify. Retry a failed ticket until fixed, blocked, or the attempt cap."""

from uuid import UUID

import intakes
import parser
import solver
import verifier
from config import UNRESOLVED, VERIFYING, locked

MAX_SOLVE_ATTEMPTS = 3


def _resolve_selected(user_id: UUID, ticket_ids: list[str]) -> None:
    chosen: list[str] = []
    seen: set[str] = set()
    for raw in ticket_ids:
        ticket_id = str(raw).strip()
        if not ticket_id or ticket_id in seen:
            continue
        seen.add(ticket_id)
        chosen.append(ticket_id)
    if not chosen:
        raise RuntimeError("Select a ticket.")
    allowed = set(chosen)
    for ticket_id in chosen:
        ticket = intakes.find_ticket(user_id, ticket_id)
        if ticket is None:
            raise SystemExit("ticket not found: {0}".format(ticket_id))
        if ticket["status"] == UNRESOLVED:
            print("solving {0}".format(ticket_id), flush=True)
            solver.solve(user_id, ticket_id)
    attempts = {
        item["id"]: 1
        for item in intakes.open_tickets(user_id)
        if item["id"] in allowed and item["status"] == VERIFYING
    }
    while True:
        pending = {
            item["id"]
            for item in intakes.open_tickets(user_id)
            if item["id"] in allowed and item["status"] == VERIFYING
        }
        for ticket_id in sorted(pending):
            verifier.verify(user_id, ticket_id)
        failed = [
            item["id"]
            for item in intakes.open_tickets(user_id)
            if item["id"] in pending and item["status"] == UNRESOLVED
        ]
        if not failed:
            break
        progressed = []
        for ticket_id in failed:
            if attempts.get(ticket_id, 0) >= MAX_SOLVE_ATTEMPTS:
                continue
            print("retrying {0}".format(ticket_id), flush=True)
            attempts[ticket_id] = attempts.get(ticket_id, 0) + 1
            solver.solve(user_id, ticket_id)
            ticket = intakes.find_ticket(user_id, ticket_id)
            if ticket and ticket["status"] == VERIFYING:
                progressed.append(ticket_id)
        if not progressed:
            break


@locked
def execute(user_id: UUID, session_id: UUID | None = None, ticket_ids: list[str] | None = None) -> None:
    if ticket_ids is not None:
        _resolve_selected(user_id, ticket_ids)
        return
    parser.get_tickets(user_id, session_id)
    solver.solve_tickets(user_id)
    attempts = {
        item["id"]: 1
        for item in intakes.open_tickets(user_id)
        if item["status"] == VERIFYING
    }
    while True:
        pending = {
            item["id"]
            for item in intakes.open_tickets(user_id)
            if item["status"] == VERIFYING
        }
        verifier.verify_tickets(user_id)
        failed = [
            item["id"]
            for item in intakes.open_tickets(user_id)
            if item["id"] in pending and item["status"] == UNRESOLVED
        ]
        if not failed:
            break
        progressed = []
        for ticket_id in failed:
            if attempts.get(ticket_id, 0) >= MAX_SOLVE_ATTEMPTS:
                continue
            print("retrying {0}".format(ticket_id), flush=True)
            attempts[ticket_id] = attempts.get(ticket_id, 0) + 1
            solver.solve(user_id, ticket_id)
            ticket = intakes.find_ticket(user_id, ticket_id)
            if ticket and ticket["status"] == VERIFYING:
                progressed.append(ticket_id)
        if not progressed:
            break
