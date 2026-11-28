# FleetAI frontend

React + TypeScript UI for the FleetAI backend. This is the only allowed stack.
Do not add `.jsx` or `.js` under `src/`. New screens are `.tsx`. Shared types and
fetch helpers are `.ts`.

## Visual style (from netpalm.ai) — not the copy

Match the **look** of [netpalm.ai](https://netpalm.ai) (`data-theme="amber"`):
dark warm base, cream type, amber pills, glass panels, Fraunces + Hanken Grotesk.

Do **not** reuse homepage headlines, taglines, or marketing voice. No
“The AI layer your company runs on” riffs. Screens are product UI: product
intro (`/`), Sign in, Create an account, Tickets, Terms of Service.

`/` describes FleetAI in product language: multiple agents handle and resolve
tickets from user-supplied context; GitHub for the codebase; Jira and Trello
for tickets. Copy lives in `HomePage.tsx`. Do not invent extra integrations.

Tokens in `src/index.css`:

- Base `#0C0A07`, surface `#13100B`, line `#2B2418`, line-soft `#1D1810`
- Text `#F5EFE5`, muted `#ABA08D`, muted-2 `#74695A`
- Accent `#EBA85C`, accent-strong `#E68A36`
- Display **Fraunces**, body **Hanken Grotesk**
- Top radial wash + faint 120px grid

Buttons: `.btn` + `.btn-primary` (amber glass pill, dark ink) or `.btn-ghost`.
Radius `40px`. Header is sticky glass.

Wordmark: `Fleet` in `--text` + `AI` in `--accent-strong` (orange). `BrandMark`
only. No image logo.

Terms (`/terms`) is a readable legal page with the site header, not a landing
hero. Copy comes only from `src/data/termsOfService.ts`.

After sign-in, `/workspace` is the intake studio: paste or PDF ticket list, email
textarea, optional project.md context, then **Resolve tickets**. That posts
`/api/v1/tickets/inputs` then `/api/v1/execute`, polls `/api/v1/jobs/{id}`, and
lists tickets from `GET /api/v1/tickets`. No marketing hero.

Signed-in pages use a left sidebar (`AppShell`): Projects, Connectors, Settings.
`/workspace` is the signed-in home. A project in the sidebar opens that project's tickets.
`/tickets` redirects to `/workspace`.
GitHub lives only under Connectors, never in the top bar. `/settings` is account
settings (`GET/PUT /api/v1/settings`). `/connectors` is where a customer connects
GitHub. Do not mention branches, clones, or server setup there.

## Layout

```
src/api/client.ts          prefixes `/api/v1` (not a folder); cookie + CSRF
src/components/AppShell.tsx signed-in sidebar + username menu
src/components/BrandMark.tsx
src/data/termsOfService.ts mock Terms of Service (only TOS source)
src/pages/HomePage.tsx     `/` product intro
src/pages/LoginPage.tsx    `/login` → POST /api/v1/auth/login
src/pages/SignUpPage.tsx   `/signup` → POST /api/v1/auth/register
src/pages/SettingsPage.tsx `/settings` account; `/connectors` GitHub
src/components/AuthenticatorSetup.tsx  Settings section → POST /api/v1/auth/totp/setup, /enable, /disable
src/pages/ForgotPasswordPage.tsx  `/forgot` → POST /api/v1/auth/password/forgot
src/pages/ResetPasswordPage.tsx   `/reset?token=` → POST /api/v1/auth/password/reset
src/pages/TermsPage.tsx
src/pages/TicketsPage.tsx
src/session.tsx            GET /api/v1/auth/me; no localStorage accounts
```

Auth is the backend cookie session. `/signup` posts
`{username, email, first_name, last_name, password, tos_accepted}`
to `/api/v1/auth/register`. `/login` posts `{email, password, code}` to `/api/v1/auth/login`; it shows the
authenticator code field after a `401 code required`.
A `403` there means the email is not verified yet and a `429` means too many attempts; both get their own message.
`username` is the handle; sign-in uses `email`.
On load, `GET /api/v1/auth/me`. Non-GET fetches send `X-Requested-With: fleetai` and
`credentials: 'same-origin'`. 401 on `/workspace` redirects to `/login`. Do not store
passwords or accounts in localStorage. `SessionProvider` signs the user out after
`idle_limit_minutes` (from `/auth/me`) without input and shows `SessionExpired`, a
blurred overlay with a Sign in button. A 401 from a page calls `expire()` to show the
same dialog. Routes: `/` intro, `/login`, `/signup`,
`/terms`, `/workspace`, `/connectors`, `/settings`. `/tickets` redirects to `/workspace`.

## Backend

Browser calls go through `/api/v1/...`. `v1` is a URL prefix, not a directory.
Vite (dev) and nginx send `/api/v1/auth` to the auth service (`127.0.0.1:8001` /
`auth:8000`) and other `/api/v1` paths to the ticket API (`127.0.0.1:8000` /
`backend:8000`). A push that only changes `frontend/` deploys that image and
leaves auth and the API running. Types must match `backend/api.py` and
`backend/auth`. No invented API routes.
