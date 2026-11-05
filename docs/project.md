# fleetai

Reads a bug report and the evaluator email, asks Claude Sonnet on Amazon
Bedrock for the tickets that are still open, then can hand each unresolved
ticket to a local Cursor agent.

The product code is not in this repo. `codebase/code-context.md` is the map:
repositories, how they fit together, tests, and branch rules. Set
`FLEETAI_PRODUCT_ROOT` to the folder that contains those checkouts.

## Commands

```bash
conda activate dev
cd /Users/minh/repos/netpalm.ai/fleetai

python main.py parse              # email and/or PDF -> tickets/unsolved_tickets.json
python main.py                    # list tickets and their state
python main.py run                # parse, solve, verify, archive solved
python orchestrator.py            # same pipeline
python main.py JMD-30SEP-05       # solve one unresolved ticket
python main.py verify             # verify every verifying ticket
python main.py verify JMD-30SEP-05
python main.py complete JMD-30SEP-05
```

The parser writes new tickets as `unresolved` and does not rewrite tickets
that are already `verifying`. After the pipeline, `fixed` and `completed`
tickets move to `tickets/solved/<id>.json`. A later parse compares each
incoming ticket to that archive: restating it on a retest list is skipped.
The parser decides in ordinary language whether a completed test of that id
did not match expected behaviour. If so it sets kind `recurrent` and new
context; then the ticket comes back as `unresolved`. There is no keyword list. If the working list is empty, the previous `email.desc.txt`
and `list.pdf` move there too.

- `unresolved` — parser default; solver may run it; verifier fail returns here
- `verifying` — solver returned `VERDICT: ready`
- `fixed` — verifier reviewed the change, repaired introduced bugs, stripped unnecessary complexity, and returned `VERDICT: fixed`; then archived
- `completed` — `python main.py complete <id>` after live QA; then archived

Parser extracts the software defect only. Solver and verifier see
`id`, `title`, `severity`, `services`, `context`, and `expected`. Business
labels and process asks are not production work. Workflow is only
`unresolved`, `verifying`, `fixed`.
`repos` is leftover metadata. Routing is `code-context.md` plus `services`.

## Files

- `config.py` — ticket paths and workflow. Reads the code context file.
- `parser.py` — `get_tickets()` from `tickets/email.desc.txt` and/or `tickets/list.pdf` (need at least one); PRODUCT AREAS is the Repositories section of the code map
- `solver.py` — `solve()` / `solve_tickets()`; `VERDICT: ready` → `verifying`
- `verifier.py` — `verify()` / `verify_tickets()`; review and repair introduced bugs; `VERDICT: fixed` → `fixed`, fail → `unresolved`
- `orchestrator.py` — `run()`: get tickets, solve, verify, archive solved
- `main.py` — CLI for one step, or `run` for the pipeline
- `codebase/code-context.md` — product map supplied for the current codebase
- `tickets/unsolved_tickets.json` — open ticket list with `status`
- `tickets/solved/<id>.json` — archived `fixed` / `completed` tickets
- `tickets/runs/<ticket-id>-<run-id>.md` — solve/verify log (gitignored)
- `tests/test_workflow.py` — workflow unit tests

## Environment

- `AWS_REGION` / `AWS_DEFAULT_REGION` and AWS credentials for the parser
- `BEDROCK_MODEL_ID` optional, defaults to Claude Sonnet 4.6
- `CURSOR_API_KEY` for the solver. Stored as a GitHub Actions secret on
  `ngtminh/fleetai`. GitHub will not return secret values to a local script.
  Local runs read the gitignored `.env`. Actions can inject
  `${{ secrets.CURSOR_API_KEY }}`.
- `FLEETAI_PRODUCT_ROOT` required for solve and verify
- `FLEETAI_CURSOR_MODEL` optional, defaults to `grok-4.6` with high + fast
