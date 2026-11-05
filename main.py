"""CLI: one step, or the full pipeline."""

from __future__ import annotations

import sys

import orchestrator
import parser
import solver
import verifier

USAGE = "usage: python main.py [parse|list|run|solve|solve <id>|verify|verify <id>|complete <id>|<id>]"


def main() -> None:
    args = sys.argv[1:]
    if not args or args == ["list"]:
        solver.list_tickets()
    elif args == ["parse"]:
        parser.print_tickets(parser.get_tickets())
    elif args == ["solve"]:
        solver.solve_tickets()
    elif args == ["run"]:
        orchestrator.run()
    elif args == ["verify"]:
        verifier.verify_tickets()
    elif len(args) == 2 and args[0] == "solve":
        solver.solve(args[1])
    elif len(args) == 2 and args[0] == "verify":
        verifier.verify(args[1])
    elif len(args) == 2 and args[0] == "complete":
        solver.complete(args[1])
    elif len(args) == 1:
        solver.solve(args[0])
    else:
        raise SystemExit(USAGE)


if __name__ == "__main__":
    main()
