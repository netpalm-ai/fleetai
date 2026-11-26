# FleetAI

This adapter is the FleetAI product itself. `code-context.md` stays the customer map. Do not edit that file, compose, or CI to point a customer deploy at this checkout.

## Product root

`FLEETAI_PRODUCT_ROOT` is this git checkout, one repository (`netpalm-ai/fleetai`). `frontend/` and `backend/` are directories in that repo, not separate clones. Run git at the checkout root. Do not commit, push, or deploy.

## Repositories

| Ticket service names | Local checkout | Remote | Owns |
|---|---|---|---|
| tickets page, sign-in, sign-up, settings, connectors, session UI | `$FLEETAI_PRODUCT_ROOT/frontend` | `netpalm-ai/fleetai` | React + TypeScript. Read `frontend/AGENTS.md` before editing. |
| tickets API, parser, solver, verifier, intakes | `$FLEETAI_PRODUCT_ROOT/backend` | `netpalm-ai/fleetai` | FastAPI in `api.py`. Browser calls use `/api/v1`. Do not invent routes. |
| auth, session cookie, password, authenticator | `$FLEETAI_PRODUCT_ROOT/backend/auth` | `netpalm-ai/fleetai` | Cookie session. Same git repo as `backend/`. |

## Work rules

- Read `frontend/AGENTS.md` before a frontend change. Keep the amber glass tokens, `BrandMark`, and the existing button classes. Do not add a component library or a test runner.
- A UI ticket is about `frontend/`. Do not patch `backend/` to change layout, copy, or color.
- Jobs are in memory and addressed by `GET /jobs/{id}` only. There is no current-job route. A page may remember a job id it already received. Do not add a list-jobs or current-job route unless the ticket names that backend change.
- Do not change schema, auth, secrets, or CI unless the ticket names that work.
- If a needed file is already dirty from other work, stop. Engineering standard applies. This checkout is often the operator's working tree.

## Tests

- `frontend`: `npm run build` from `frontend/`. That is `tsc --noEmit` and the production build. There is no frontend test suite.
- `backend` parser, solver, verifier, or API: `python -m pytest tests/test_workflow.py tests/test_api.py -q` from `backend/`.
- `backend/auth`: `python -m pytest tests/test_auth.py -q` from `backend/`, with `DATABASE_URL` set. Do not treat a run without Postgres as a pass.
