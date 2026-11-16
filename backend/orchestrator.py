"""Parse, then solve, then verify. Retry a failed ticket until fixed, blocked, or the attempt cap."""

from uuid import UUID

import intakes
import parser
import solver
import verifier
from config import UNRESOLVED, VERIFYING, locked

MAX_SOLVE_ATTEMPTS = 3


@locked
def execute(user_id: UUID, session_id: UUID | None = None) -> None:
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
