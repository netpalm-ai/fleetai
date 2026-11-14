"""Parse, then solve, then verify the user's tickets."""

from uuid import UUID

import config
import parser
import solver
import verifier


@config.locked
def execute(user_id: UUID, session_id: UUID | None = None) -> None:
    parser.get_tickets(user_id, session_id)
    solver.solve_tickets(user_id)
    verifier.verify_tickets(user_id)
