# fleetai

Parse the evaluator email and/or a bug-report PDF into tickets. An optional
evidence PDF is summarized locally with Ollama when it is long, then Claude
Sonnet on Bedrock writes the tickets. Each unresolved ticket can go to a
local Cursor agent. The product repos and how to work in them are in
`codebase/code-context.md`. Set `FLEETAI_PRODUCT_ROOT` to the folder that
contains those checkouts.

```bash
conda activate dev
python orchestrator.py                 # parse, solve, verify, archive solved
python main.py                         # list tickets
python main.py complete JMD-30SEP-05   # live QA only; sets completed, not fixed
```

See `docs/project.md`.
