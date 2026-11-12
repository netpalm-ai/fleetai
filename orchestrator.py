"""Parse, then solve, then verify, then archive solved tickets."""

import config
import parser
import solver
import verifier


@config.locked
def execute() -> None:
    parser.get_tickets()
    solver.solve_tickets()
    verifier.verify_tickets()
    config.archive_solved()


if __name__ == "__main__":
    execute()
