# fleetai

Parse the evaluator email and/or a bug-report PDF into tickets. An optional
evidence PDF is summarized locally with Ollama when it is long, then Claude
Sonnet on Bedrock writes the tickets. Each unresolved ticket can go to a
local Cursor agent. The product repos and how to work in them are in
`backend/codebase/code-context.md`. Set `FLEETAI_PRODUCT_ROOT` to the folder that
contains those checkouts. To point the solver at this repo instead, set
`FLEETAI_PRODUCT_ROOT` to this checkout and `FLEETAI_CODE_CONTEXT` to
`backend/codebase/code-context.fleetai.md`. `backend/` is the API. `frontend/` is the web app.

```bash
conda activate dev
cd backend
uvicorn api:app                        # needs Postgres; see docs/project.md
```

```bash
cd frontend
npm install
npm run dev                            # http://127.0.0.1:8080  (proxies /api/v1 to :8000)
```

See `docs/project.md`.
