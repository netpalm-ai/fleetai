# FleetAI

## Product

FleetAI

## Org

Netpalm.AI

## Tech stack

React, TypeScript, FastAPI, Postgres

## Product root

`FLEETAI_PRODUCT_ROOT` is the directory of git clones for the project being solved. This product is one clone, `fleetai` (`netpalm-ai/fleetai`). `frontend/` and `backend/` are directories inside that clone, not separate repositories. Run git inside `fleetai/`.

The required branch is `fleetai/dev`. Do not commit, push, or deploy. A change on `fleetai/dev` does not update the running site. The i9 deploy builds from `main` only.

## Repositories

| Ticket service names | Local checkout | Remote | Owns |
|---|---|---|---|
| tickets page, sign-in, sign-up, settings, connectors, session UI | `$FLEETAI_PRODUCT_ROOT/fleetai/frontend` | `netpalm-ai/fleetai` | React + TypeScript. Read `fleetai/frontend/AGENTS.md` before editing. Same git repository as the other rows. |
| tickets API, parser, solver, verifier, intakes | `$FLEETAI_PRODUCT_ROOT/fleetai/backend` | `netpalm-ai/fleetai` | FastAPI in `api.py`. Browser calls use `/api/v1`. Do not invent routes. Same git repository as `fleetai/frontend`. |
| auth, session cookie, password, authenticator | `$FLEETAI_PRODUCT_ROOT/fleetai/backend/auth` | `netpalm-ai/fleetai` | Cookie session. Same git repository as `fleetai/backend`. |

## Runtime flow

`browser -> /api/v1/auth (session cookie) or /api/v1 (tickets and jobs) -> Postgres`

- Sign-in, password, and authenticator: `fleetai/backend/auth`.
- The ticket list and Resolve: `fleetai/frontend` and `fleetai/backend`. The project selected on the tickets page is the project being solved. Use that project's code context, not another product's.
- Jobs stay in memory on the API process and are read with `GET /jobs/{id}`. There is no current-job route.
- A UI ticket is about `fleetai/frontend`. Do not patch `fleetai/backend` to change layout, copy, or color.

## Deploy

- i9 builds images from `main` and serves those images. It does not serve this working tree.
- This checkout is `fleetai/dev`. Do not merge it, push it, or deploy it.

## Data handling

Never print passwords, reset tokens, authenticator codes, session cookies, or GitHub tokens. Ids, timestamps, and counts only.

## Work rules

- Read `fleetai/frontend/AGENTS.md` before a frontend change. Keep the amber glass tokens, `BrandMark`, and the existing button classes. Do not add a component library or a test runner.
- Self-improve reviews pages in order (`/`, `/login`, `/signup`, `/verify`, `/forgot`, `/reset`, `/terms`, `/workspace`, `/connectors`, `/settings`), then reviews each product script under `frontend/src`, `backend/*.py`, and `backend/auth`, before it writes tickets. Public auth/intro pages must not use the signed-in sidebar.
- Do not change schema, auth, secrets, or CI unless the ticket names that work.
- If a needed file is already dirty from other work, stop. Engineering standard applies.

## Tests

- `fleetai/frontend`: `npm run build` from `fleetai/frontend`. That is `tsc --noEmit` and the production build. There is no frontend test suite.
- `fleetai/backend` parser, solver, verifier, or API: `python -m pytest tests/test_workflow.py tests/test_api.py -q` from `fleetai/backend`.
- `fleetai/backend/auth`: `python -m pytest tests/test_auth.py -q` from `fleetai/backend`, with `DATABASE_URL` set. Do not treat a run without Postgres as a pass.
