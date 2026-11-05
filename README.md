# fleetai

Parse the evaluator email and/or a PDF into tickets, then send each
unresolved ticket to a local Cursor agent. The product repos and how
to work in them are in
`codebase/code-context.md`. Set `FLEETAI_PRODUCT_ROOT` to the folder that
contains those checkouts.

```bash
conda activate dev
python orchestrator.py                 # parse, solve, verify, archive solved
python main.py                         # list tickets
python main.py complete JMD-30SEP-05   # live QA only; sets completed, not fixed
```

See `docs/project.md`.
