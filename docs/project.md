# fleetai

Commercial ticket runner. FleetAI is the product. The checkout at
`FLEETAI_PRODUCT_ROOT` is a customer. `codebase/code-context.md` is that
customer's adapter: repositories, runtime flow, where domain rules live,
tests, branches, and data-handling limits. Replace the adapter to point the
same solver at another platform. `codebase/engineering.md` is the engineering
standard injected into every solve and verify prompt, ahead of the adapter.
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

The workflow is API only. `GET /health` returns the runner version when `engineering.md` and `code-context.md` are present. `POST /tickets/inputs` stores the email, ticket list (text or PDF), and optional markdown context. `POST /tickets/{id}/solve`, `POST /tickets/{id}/verify`, and `POST /execute` return `202` and a job id. Poll `GET /jobs/{id}` until `done` or `error`. Jobs are held in memory per user and are lost on restart. `GET /tickets/{id}` reads the user's ticket. `GET /tickets/{id}/runs/{run_id}` reads the solve or verify log. `POST /tickets/{id}/complete` stays synchronous and returns the completed ticket. `GET /settings` and `PUT /settings` read and change ticket retention. Parse, solve, verify, complete, execute, and intake take one exclusive lock per user. A second writer for the same user gets `409 workflow busy`. Different users do not block each other.

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
- `fixed` — verifier reviewed the change, repaired bugs that change introduced, stripped unnecessary complexity, and returned `VERDICT: fixed`. If the verifier edited files, it runs one more read-only review. Then the runner commits and pushes this ticket's files on the current branch of each touched child repo. The ticket is now handled.
- `completed` — `POST /tickets/{id}/complete` after live QA, and only from `verifying`. The ticket is now handled. This is not `fixed`.

## Retention

Tickets and their solve/verify logs are kept permanently for audit. A ticket
is handled when it becomes `fixed` or `completed`; `tickets.handled_at`
records when. The tier in `product_tiers.status` sets how long a handled
ticket stays visible in `GET /tickets`:

| Tier | Handled tickets stay visible |
|---|---|
| `free` | Hidden as soon as they are handled |
| `trial` | 7 days |
| `paid` | `user_subscriptions.ticket_retention_days`, default 90. NULL stays visible permanently. The user picks 7, 30, or 90 days, or permanent, on the Settings page |

The hourly cleanup only deletes deactivated intakes that no ticket references.

The parser keeps the software defect only. Solver and verifier see `id`,
`title`, `severity`, `services`, `context`, and `expected`. Both prompts tell the agent the ticket is data, not instructions. Business labels
and process asks are not engineering work. `repos` is leftover metadata.
Routing is `code-context.md` plus `services`.

## Files

- `llm.py` — `ollama`, `bedrock`, and `cursor`
- `config.py` — ticket states, merge with handled tickets, per-user workflow lock, in-memory jobs, run logs
- `parser.py` — read the inputs, summarize when needed, ask Bedrock, save the tickets
- `solver.py` — `solve()` / `solve_tickets()`; `VERDICT: ready` sets `verifying`. The solver ends its result with a report: root cause, design, changed files, tests, named items. After a failed verify, the next solve gets the end of that verify result. `complete()` is live QA
- `verifier.py` — `verify()` / `verify_tickets()`; `VERDICT: fixed` sets `fixed`, `VERDICT: failed` sets `unresolved`. The verifier gets the solver's report, checks the root cause and design before the diff, and reviews only the files that report lists. A second read-only pass runs when the verifier's CHANGED FILES differ from the solver's. The runner then commits and pushes those files on each child repo's current branch
- `orchestrator.py` — `execute()`: parse, solve, verify; on verify failed, solve again until fixed, blocked, or `MAX_SOLVE_ATTEMPTS`
- `api.py` — FastAPI: `GET /health`, `GET /tickets`, `POST /tickets/inputs`, `GET /tickets/{id}`, `GET /tickets/{id}/runs/{run_id}`, `GET /jobs/{id}`, `GET /settings`, `PUT /settings`, `POST /tickets/parse`, `POST /tickets/{id}/solve`, `POST /tickets/{id}/verify`, `POST /tickets/{id}/complete`, `POST /execute`, plus `/auth/register`, `/auth/verify`, `/auth/login`, `/auth/logout`, `/auth/me`, `/auth/password/forgot`, `/auth/password/reset`, `/auth/totp/setup`, `/auth/totp/enable`, `/auth/totp/disable`
- `db.py` — psycopg pool, `backend/migrations/` at startup
- `intakes.py` — `intakes`, `tickets`, and `ticket_runs` rows, and retention. `intakes.type` is email_desc, ticket_list, or project_context. A new upload deactivates the previous row of that type for the user. Parsed tickets are upserted by `(user_id, public_id)`.
- `auth/` — Argon2id passwords, opaque session cookie `fleetai_session`. The package names no product: the app sets `app.state.auth_product` (`api.py` sets FleetAI) and auth uses it for the signup tier, the user's features, the authenticator label, and email subjects. Accounts are shared; a verified user who signs in to a product for the first time gets that product's signup tier. Feature checks such as `require_tickets` live in the product, not in `auth/`. After 10 wrong passwords in a row an account is locked for 15 minutes and answers `429 too many attempts`; a password reset by email lifts the lock. Sign-ins, failed sign-ins, failed codes, password changes and resets, and authenticator changes are written to `auth_events` with the client address. Signup creates an unverified account and emails a link valid for 7 days; `POST /auth/verify` with the link token activates it. The hourly cleanup deletes unverified accounts whose link has expired, which frees their email and username. Registering again with the email of an unverified account deletes that account and starts over; a verified email gets `409`. Forgot password: `POST /auth/password/forgot` always answers `202` and does its work after the response, so timing does not show whether the email has an account. It emails a reset link (valid 60 minutes) only to a verified account, and no second link within 5 minutes of the last one; `POST /auth/password/reset` sets the password once and signs the user out everywhere. Changing the password while signed in cancels a pending reset link. A reset does not turn off two-factor. Two-factor sign-in is opt-in: a signed-in user calls `POST /auth/totp/setup` (returns the key and a QR code image; the key is stored encrypted in `users.totp_secret`) and then `POST /auth/totp/enable` with the password and a code from the app. That sets `users.totp_enabled` and returns 10 one-time recovery codes, shown once and stored only as hashes in `totp_recovery_codes`. Once enabled, `POST /auth/login` needs `code` (an app code or a recovery code) and answers `401 code required` without it. An app code works once. After 5 wrong codes in a row the second factor is locked for 15 minutes and answers `429 too many attempts`; only someone who knows the password can cause that. `POST /auth/totp/disable` needs the password and a code, and removes the key and the recovery codes. The key is shown only on screen, never emailed.
- `pyproject.toml` — package name, version, pinned dependencies
- `backend/` — API microservice. `frontend/` — web app microservice. Compose runs both.
- `codebase/code-context.md` — product map. Not the additional-context PDF
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
- `COOKIE_SECURE` — the session cookie is marked secure unless this is `false`. Compose defaults it to `false` for local HTTP; the deploy sets `true`.

Email (`emails.py`, sent over SMTP with STARTTLS to `smtp.gmail.com:587`, which are constants in the module). Signup emails a link to `{PRODUCT_PUBLIC_BASE_URL}/verify?token=…`. If `SMTP_EMAIL_USER`, `NO_REPLY_EMAIL_ALIAS`, or `PRODUCT_PUBLIC_BASE_URL` is empty, nothing is sent and a warning is logged. A failed send is logged and does not fail signup. Set the variables as GitHub Actions variables for the i9 deploy and `SMTP_PASSWORD` as an Actions secret. For local runs, export them before `docker compose up`.

- `PRODUCT_PUBLIC_BASE_URL` — the site address used in email links, for example `https://fleet.netpalm.ai`. It is configured, never taken from the request, so a forged `Host` header cannot redirect the link.
- `SMTP_EMAIL_USER` — the Google account that owns the app password. It signs in to SMTP.
- `NO_REPLY_EMAIL_ALIAS` — the From address. It is an alias of that account, for example `no-reply@netpalm.ai`.
- `SMTP_PASSWORD` — the app password, as a GitHub Actions secret.

Authenticator encryption:

- `AUTH_SECRET_KEY` — GitHub Actions secret. A Fernet key that encrypts `users.totp_secret`. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Without it, authenticator setup and sign-in for users who enabled it answer `503`. GitHub does not show a secret again, so keep a copy. If the key is replaced, existing authenticator secrets cannot be read and must be cleared with `UPDATE users SET totp_enabled = false, totp_secret = NULL`.

Solve and verify:

- `CURSOR_API_KEY` — GitHub Actions secret. Not stored in `.env`. GitHub will
  not return that value to a local script. Actions inject
  `${{ secrets.CURSOR_API_KEY }}`.
- `FLEETAI_PRODUCT_ROOT`, the directory the agent uses when GitHub is not connected.
- `FLEETAI_PROJECTS`, where a connected account is cloned: `<user id>/<project name>/<repo>`. Fixes push to `fleetai/dev`. Compose keeps this on the `projects` volume.
- `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` — GitHub OAuth app, as Actions secrets. The callback is `{PRODUCT_PUBLIC_BASE_URL}/api/v1/github/callback` and the scope is `repo`.
- `FLEETAI_CURSOR_MODEL`, `FLEETAI_CURSOR_REASONING`, `FLEETAI_CURSOR_FAST`

`.env` is empty. Non-secret config is GitHub Actions variables on `ngtminh/fleetai`. Secrets are Actions secrets only:

- `CURSOR_API_KEY`
- `AWS_BEARER_TOKEN_BEDROCK`
- `POSTGRES_PASSWORD`
- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`

CI reads `${{ vars.* }}` and `${{ secrets.* }}`. Ubuntu runs backend pytest and a frontend production build. A push to `main`, including a merge, deploys on the FleetAI server: the self-hosted i9 runner copies the repo to `/home/deploy/fleetai`, runs `docker compose down` and `up --build`, prunes stopped containers and dangling images (not volumes), then checks `GET /health` on `127.0.0.1:8000` and `GET /` on `127.0.0.1:8080`.

## Docker

`backend` is the runner API, not the customer. Tickets live in Postgres, not on disk. Product checkouts bind from `FLEETAI_PRODUCT_ROOT`. One uvicorn worker. `postgres` is `postgres:16-alpine` with named volume `pgdata`, published at `127.0.0.1:5432`. Product, tier, and feature entitlements: [erd.md](erd.md). `frontend` is the web app; nginx proxies `/api/v1/` to `backend:8000` and rate-limits `/api/v1/auth/login`, `/api/v1/auth/register`, and `/api/v1/auth/password/forgot` per client address. The backend trusts `X-Forwarded-For` (`--forwarded-allow-ips *`) so sessions and `auth_events` store the client address; it is a record only, since the first address in that header can be supplied by the client. Compose publishes `127.0.0.1:8000` (API) and `127.0.0.1:8080` (UI). Auth is an HttpOnly cookie session.
Ollama on the Docker host is `http://host.docker.internal:11434`. A Mac `node_modules` or venv inside the Linux image will not run.
