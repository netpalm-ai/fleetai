# fleetai

Commercial ticket runner. FleetAI is the product. The checkout at
`FLEETAI_PRODUCT_ROOT` is whichever codebase the operator points at. The
runner does not load a built-in customer map. Each user has projects.
`project_contexts` stores `user_id`, `org`, `product_name`, `codebase_context`,
and `tech_stack`. JarvisMD is stored with org HBA. FleetAI is stored with org
Netpalm.AI. A user's copy sets `user_id` and `project_id`. On the first parse, solve, or verify
for a project with no row, a Cursor agent inspects that project's checkout
and the runner stores the map. Later runs load the row.
`codebase/engineering.md` is the engineering standard injected into every
solve and verify prompt, ahead of that map.
The prompts themselves stay a short per-turn loop.
When the adapter does not name a repo, owner, test, or layer, the solver
inspects the product root before it edits. It does not deploy.

Parse reads a source email and/or a bug-report PDF, optionally a third
PDF of extra evidence, and stores the tickets in Postgres for the signed-in
user. Nothing is written to disk. A long extra document is summarized locally
before the ticket model sees it. Each unresolved ticket can then go to a
Cursor agent that edits the product checkout.

## Inputs

All three are `intakes` rows, with the bytes in Postgres. Parse needs the
email or the bug report. Either one is enough. The extra document is
optional, and a missing one is normal.

| `intakes.type` | Role |
|---|---|
| `email_desc` | Defect facts. When the bug report is also present, process asks in the email are ignored. |
| `ticket_list` | Ticket list. Paste is format `txt`. A PDF upload is format `pdf`. Text is preferred when both exist. PDF text is extracted with PyMuPDF. A page that is only an image contributes no text. |
| `project_context` | Optional evidence. Markdown from the UI is format `md`. It may fill `context` and `expected` for a defect the email or the bug report already names. It may also show that a listed item is not a software defect, in which case that item is omitted. It cannot create a ticket by itself. |

## Models

Clients are in `llm.py`. Parse uses the first two. Solve and verify use the
third. Model names are read after `.env` is loaded. A variable already set
in the environment is left as it is.

| Client | Model env | Call | When |
|---|---|---|---|
| `ollama` | `FLEETAI_SUMMARY_MODEL` | `POST {OLLAMA_HOST}/api/chat`, temperature 0 | Additional-context text longer than `FLEETAI_SUMMARY_LIMIT` |
| `bedrock` | `BEDROCK_MODEL_ID` | Bedrock Runtime `converse` or bearer `BEDROCK_API_KEY` / `AWS_BEARER_TOKEN_BEDROCK` | Every parse |
| `cursor` | `FLEETAI_CURSOR_MODEL` | Cursor SDK `Agent.prompt` in the product checkout | Solve and verify |

Ollama is skipped when there is no additional context, or when the extracted
text is already `FLEETAI_SUMMARY_LIMIT` characters or shorter. That text is sent unchanged.
The local request uses `FLEETAI_OLLAMA_CONTEXT_WINDOW` and starts the reply in the
final channel. When a summary is needed, the local model keeps defect ids, case ids,
session ids, codes, what was shown, what was stored, and the required
outcome. It drops the review method, questions, passed checks, and plans
for a later round. An empty reply is an error. Ollama must be running for that path at `OLLAMA_HOST`.

Bedrock receives the email, the bug report, the additional context or its
summary, the Repositories section of the code map, and the user's handled
tickets that are still stored. It returns a JSON array. The parser sets
workflow status itself. The model does not.

## Commands

```bash
conda activate dev
cd /Users/minh/repos/netpalm.ai/fleetai/backend

uvicorn api:app
```

The workflow is API only. `GET /health` returns the runner version when `engineering.md` is present. A project does not need a code map before the API is up; the first parse, solve, or verify stores one on `project_contexts`. `POST /tickets/inputs` stores the email, ticket list (text or PDF), and optional markdown context. `POST /tickets/{id}/solve`, `POST /tickets/{id}/verify`, and `POST /execute` return `202` and a job id. Poll `GET /jobs/{id}` until `done` or `error`. Jobs are held in memory per user and are lost on restart. `GET /tickets/{id}` reads the user's ticket. `GET /tickets/{id}/runs/{run_id}` reads the solve or verify log. `POST /tickets/{id}/complete` stays synchronous and returns the completed ticket. `GET /settings` and `PUT /settings` read and change ticket retention. Parse, solve, verify, complete, execute, and intake take one exclusive lock per user. A second writer for the same user gets `409 workflow busy`. Different users do not block each other.

Parse does not solve or verify. It needs AWS credentials
and a region. It needs Ollama only when the additional context is longer
than the cap.

## Workflow

States are `unresolved`, `verifying`, `completed`, and `fixed`. The parser
writes new tickets as `unresolved`. A new parse drops a previous
`unresolved` ticket that it does not return. It keeps a ticket that is
`verifying`, `completed`, or `fixed`.

A `fixed` or `completed` ticket that is still stored is skipped unless the
model marks it `recurrent` and `context` or `expected` differs from the
stored copy. There is no keyword list. A restated id, a retest request, or a
test that has not happened yet is omitted.

- `unresolved` — parser default. The solver may run it. A verifier fail returns here.
- `verifying` — solver returned `VERDICT: ready`.
- `fixed` — verifier reviewed the change, repaired bugs that change introduced, stripped unnecessary complexity, and returned `VERDICT: fixed`. The ticket is now handled.
- `completed` — `POST /tickets/{id}/complete` after live QA, and only from `verifying`. The ticket is now handled. This is not `fixed`.

## Retention

Open tickets are never deleted. A ticket is handled when it becomes `fixed`
or `completed`; `tickets.handled_at` records when. Its solve and verify logs
(`ticket_runs`) go with it. The tier in `product_tiers.status` sets how long
a handled ticket stays:

| Tier | Handled tickets are kept |
|---|---|
| `free` | Deleted as soon as they are handled |
| `trial` | 7 days |
| `paid` | `user_subscriptions.ticket_retention_days`, default 90. NULL keeps them permanently. The user picks 7, 30, or 90 days, or permanent, on the Settings page |

Purge runs when a ticket is handled, when a paid user changes the setting,
and hourly in the background. It also deletes deactivated intakes that no
ticket references.

The parser keeps the software defect only. Solver and verifier see `id`,
`title`, `severity`, `services`, `context`, and `expected`. Business labels
and process asks are not engineering work. `repos` is leftover metadata.
Routing is the checkout map plus `services`.

## Files

- `llm.py` — `ollama`, `bedrock`, and `cursor`
- `config.py` — ticket states, merge with handled tickets, per-user workflow lock, in-memory jobs, run logs
- `parser.py` — read the inputs, summarize when needed, ask Bedrock, save the tickets
- `solver.py` — `solve()` / `solve_tickets()`; `VERDICT: ready` sets `verifying`. `complete()` is live QA
- `verifier.py` — `verify()` / `verify_tickets()`; `VERDICT: fixed` sets `fixed`, `VERDICT: failed` sets `unresolved`
- `orchestrator.py` — `execute()`: parse, solve, verify; on verify failed, solve again until fixed, blocked, or `MAX_SOLVE_ATTEMPTS`
- `api.py` — FastAPI: `GET /health`, `GET /tickets`, `POST /tickets/inputs`, `GET /tickets/{id}`, `GET /tickets/{id}/runs/{run_id}`, `GET /jobs/{id}`, `GET /settings`, `PUT /settings`, `POST /tickets/parse`, `POST /tickets/{id}/solve`, `POST /tickets/{id}/verify`, `POST /tickets/{id}/complete`, `POST /execute`, plus `/auth/register`, `/auth/login`, `/auth/logout`, `/auth/me`
- `db.py` — psycopg pool, `backend/migrations/` at startup
- `intakes.py` — `intakes`, `tickets`, and `ticket_runs` rows, and retention. `intakes.type` is email_desc, ticket_list, or project_context. A new upload deactivates the previous row of that type for the user. Parsed tickets are upserted by `(user_id, public_id)`.
- `auth/` — Argon2id passwords, opaque session cookie `fleetai_session`
- `pyproject.toml` — package name, version, pinned dependencies
- `backend/` — API microservice. `frontend/` — web app microservice. Compose runs both.
- `codebase/code-context.md` — an example map. The runner does not load it. A project's map is `project_contexts`, joined on `projects.id`
- `tests/test_workflow.py` — workflow unit tests. They do not call the models
- `tests/test_intakes.py` — Postgres storage and retention tests

## Environment

Parse:

- `AWS_REGION`
- `AWS_BEARER_TOKEN_BEDROCK` — GitHub Actions secret. Not stored in `.env`. If unset locally, boto3 uses the default AWS credential chain.
- `BEDROCK_MODEL_ID`, `FLEETAI_BEDROCK_MAX_TOKENS`, `FLEETAI_BEDROCK_TIMEOUT`, `FLEETAI_BEDROCK_CONNECT_TIMEOUT`
- `FLEETAI_SUMMARY_MODEL`, `OLLAMA_HOST`, `FLEETAI_SUMMARY_LIMIT`, `FLEETAI_OLLAMA_TIMEOUT`, `FLEETAI_OLLAMA_MAX_TOKENS`, `FLEETAI_OLLAMA_CONTEXT_WINDOW`

Sessions:

- `SESSION_IDLE_MIN_LIMIT` — minutes of inactivity before a session ends. Default 60. Set it as the GitHub Actions variable of the same name. The server refreshes a session at most every 5 minutes, so keep it at 10 or more. The web app signs the user out after the same time without input, blurs the page, and shows a "Session expired" dialog with a Sign in button. It also shows that dialog when any call returns 401. While the user is active, the page pings `/auth/me` every 5 minutes to keep the session alive.
- `SESSION_MAX_DAYS` — absolute session lifetime. Default 30.

Email (`emails.py`, sent over SMTP with STARTTLS). Signup emails a link to `{PUBLIC_BASE_URL}/verify?token=…`. If `SMTP_HOST`, `SMTP_FROM`, or `PUBLIC_BASE_URL` is empty, nothing is sent and a warning is logged. A failed send is logged and does not fail signup. Set the variables as GitHub Actions variables for the i9 deploy and `SMTP_PASSWORD` as an Actions secret. For local runs, export them before `docker compose up`.

- `PUBLIC_BASE_URL` — the site address used in email links, for example `https://fleet.netpalm.ai`. It is configured, never taken from the request, so a forged `Host` header cannot redirect the link.
- `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_USER`, `SMTP_FROM`
- `SMTP_PASSWORD` — GitHub Actions secret

Solve and verify:

- `CURSOR_API_KEY` — GitHub Actions secret. Not stored in `.env`. GitHub will
  not return that value to a local script. Actions inject
  `${{ secrets.CURSOR_API_KEY }}`.
- `FLEETAI_PRODUCT_ROOT`, the checkout used when the user has not connected a GitHub project. A named project is checked out under `FLEETAI_PROJECTS`. Its map is the `project_contexts` row for that `project_id`.
- `FLEETAI_CURSOR_MODEL`, `FLEETAI_CURSOR_REASONING`, `FLEETAI_CURSOR_FAST`

`.env` is empty. Non-secret config is GitHub Actions variables on `ngtminh/fleetai`. Secrets are Actions secrets only:

- `CURSOR_API_KEY`
- `AWS_BEARER_TOKEN_BEDROCK`
- `POSTGRES_PASSWORD`

CI reads `${{ vars.* }}` and `${{ secrets.* }}`. Ubuntu runs backend pytest and a frontend production build. A push to `main` then deploys both services on the self-hosted macOS runner: `docker compose down`, `up --build`, prune stopped containers and dangling images (not volumes), then `GET /health` on `127.0.0.1:8000` and `GET /` on `127.0.0.1:8080`.

## Docker

`backend` is the runner API, not the customer. Tickets live in Postgres, not on disk. Product checkouts bind from `FLEETAI_PRODUCT_ROOT`. One uvicorn worker. `postgres` is `postgres:16-alpine` with named volume `pgdata`, published at `127.0.0.1:5432`. Product, tier, and feature entitlements: [erd.md](erd.md). `frontend` is the web app; nginx proxies `/api/v1/` to `backend:8000` and rate-limits `/api/v1/auth/login`. Compose publishes `127.0.0.1:8000` (API) and `127.0.0.1:8080` (UI). Auth is an HttpOnly cookie session.
Ollama on the Docker host is `http://host.docker.internal:11434`. A Mac `node_modules` or venv inside the Linux image will not run.
