# fleetai

Parse the evaluator email and/or a bug-report PDF into tickets. An optional
evidence PDF is summarized locally with Ollama when it is long, then Claude
Sonnet on Bedrock writes the tickets. Each unresolved ticket can go to a
local Cursor agent. Each user's project has its own map in `project_contexts`,
joined by `project_id`. The first run for a project inspects that checkout
and stores the org, product name, codebase context, and tech stack. JarvisMD is org HBA. FleetAI is org Netpalm.AI.
`backend/` is the API. `frontend/` is the web app.

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
