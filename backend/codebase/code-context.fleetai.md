# FleetAI

## Product

FleetAI

## Org

Netpalm.AI

## Tech stack

React, TypeScript, FastAPI, Postgres

## Product root

`FLEETAI_PRODUCT_ROOT` is the directory of git clones for the project being solved. This product is one clone, `fleetai` (`netpalm-ai/fleetai`). `frontend/` and `backend/` are directories inside that clone, not separate repositories. Run git inside `fleetai/`.

The required branch is `fleetai/dev`. Normal solve and verify work does not commit, push, or deploy. A change on `fleetai/dev` alone does not update the running site. Production images build from `main` only.

## Repositories

| Service names | Local checkout | Remote | Owns |
|---|---|---|---|
| workspace page, sign-in, sign-up, settings, connectors, session UI, AppShell | `$FLEETAI_PRODUCT_ROOT/fleetai/frontend` | `netpalm-ai/fleetai` | React + TypeScript. Read `fleetai/frontend/AGENTS.md` before editing. Signed-in product is **Workspace** at `/workspace`; do not name a screen, route, or label Tickets. `AppShell` sidebar only when the session has a username. Same git repository as the other rows. |
| tickets API, parser, solver, verifier, intakes, orchestrator, selflooper, reviewer, watcher | `$FLEETAI_PRODUCT_ROOT/fleetai/backend` | `netpalm-ai/fleetai` | FastAPI in `api.py`. Browser calls use `/api/v1`. Mutating routes require `X-Requested-With: fleetai` (CSRF). Do not invent routes. Same git repository as `fleetai/frontend`. |
| auth, session cookie, password, authenticator | `$FLEETAI_PRODUCT_ROOT/fleetai/backend/auth` | `netpalm-ai/fleetai` | Cookie session. Production auth image builds from repo `auth/` but copies this package. Same git repository as `fleetai/backend`. |

## Runtime flow

`browser -> /api/v1/auth (session cookie) or /api/v1 (tickets, jobs, GitHub, settings) -> Postgres`

- Sign-in, password, and authenticator: `fleetai/backend/auth`, served on `/api/v1/auth`.
- Signed-in users land on `/workspace` (intake studio: inputs, **Resolve**, ticket list). Project selection is `?project=` on `/workspace`. There is no `/tickets` page.
- The ticket list and Resolve: `fleetai/frontend` and `fleetai/backend`. The project selected in Workspace is the project being solved. Use that project's code context, not another product's.
- Non-GET browser calls and API mutating routes require CSRF (`X-Requested-With: fleetai`). Frontend sets this in `src/api/client.ts`; backend enforces `auth.deps.require_csrf`.
- Jobs stay in memory on the API process and are read with `GET /jobs/{id}`. There is no current-job route.
- GitHub OAuth tokens are stored Fernet-encrypted with `AUTH_SECRET_KEY` in `connections.py`.
- `memories` rows (`kind` `rule` or `feedback`) load as **PREVENT** via `db.prevent_lines()` into solver, verifier, reviewer, watcher, and selflooper prompts.
- Admin self-improve: `POST /api/v1/self-improve` with `{instruction}` (admin only, CSRF). Runs `selflooper.run_instruction`: `reviewer` page walk then script walk → tickets → `orchestrator.execute` → tests → `publish` (merge `fleetai/dev` into `main` and push). `watcher.recover` on failure; `watcher.review` may request another pass. Instruction text is stored with `db.remember("feedback", …)`.
- CLI `python -m selflooper` with no argument resolves open tickets; with an argument runs one instruction.
- A UI ticket is about `fleetai/frontend`. Do not patch `fleetai/backend` to change layout, copy, or color.

## Deploy

- Push to `main` triggers CI and deploy on the i9 runner. Served images come from `main`.
- `selflooper.publish` is the automated self-improve deploy path: commit on `fleetai/dev`, push `fleetai/dev`, merge into `main`, push `main`, return to `fleetai/dev`. Local git identity is set to `FleetAI <fleetai@netpalm.ai>` before commit.
- This working checkout is normally `fleetai/dev`. Do not merge, push, or deploy from ordinary solve/verify unless the ticket explicitly requires it.

## Data handling

Never print passwords, reset tokens, authenticator codes, session cookies, or GitHub tokens (plain or decrypted). Ids, timestamps, and counts only.

## Work rules

- Read `fleetai/frontend/AGENTS.md` before a frontend change. Keep the amber glass tokens, `BrandMark`, and the existing button classes. Do not add a component library or a test runner.
- Workspace, not Tickets: signed-in home is `/workspace`. Public routes (`/`, `/login`, `/signup`, `/verify`, `/forgot`, `/reset`, `/terms`) must not show the signed-in `AppShell` sidebar.
- Self-improve (admin): `reviewer` walks product pages in order (`/`, `/login`, `/signup`, `/verify`, `/forgot`, `/reset`, `/terms`, `/workspace`, `/connectors`, `/settings`), then every product script under `frontend/src`, `backend/*.py`, and `backend/auth` (tests skipped), then emits tickets. Follow **PREVENT** and `AGENTS.md`.
- `watcher` recovers from run failures without implementing the instruction; after a successful pass it re-walks pages and may emit a follow-up instruction.
- Follow **PREVENT** in all agent prompts. A line there is a mistake that must not be repeated.
- Do not change schema, auth, secrets, or CI unless the ticket names that work.
- If a needed file is already dirty from other work, stop. Engineering standard applies.

## Tests

- `fleetai/frontend`: `npm run build` from `fleetai/frontend`. That is `tsc --noEmit` and the production build. There is no frontend test suite.
- `fleetai/backend` parser, solver, verifier, or API: `python -m pytest tests/test_workflow.py tests/test_api.py -q` from `fleetai/backend`.
- `fleetai/backend/auth`: `python -m pytest tests/test_auth.py -q` from `fleetai/backend`, with `DATABASE_URL` set. Do not treat a run without Postgres as a pass.
- Self-improve path: `tests/test_selflooper.py`, `tests/test_reviewer.py`, and `tests/test_watcher.py` when changing those modules.
