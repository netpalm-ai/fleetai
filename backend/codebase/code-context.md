# JarvisMD / HBA product code

This file is the customer adapter. The runner does not assume this product.

## Product root

`FLEETAI_PRODUCT_ROOT` is the directory that contains these independent Git repositories (on a laptop often `/Users/minh/repos/hba`). Run Git commands inside the child repo you are changing.

Read `$FLEETAI_PRODUCT_ROOT/.cursor/rules/hba-platform-handoff.mdc` first.

SSH aliases are in `/Users/minh/.ssh/config`. Use `ssh <alias>`. Do not
copy keys or edit that file unless the user asks.

## Repositories

| Ticket service names | Local checkout | Remote | Owns |
|---|---|---|---|
| page load, session activity, annotated transcript UI, copy icon, timestamps, survey, UK time | `$FLEETAI_PRODUCT_ROOT/jmd-frontend` | `cto-hba/jmd-frontend` | React/Vite SPA. Regional URLs and flags: public/server-profiles.json |
| annotated transcript pipeline, clinical summary persistence, Save & complete, evaluation snapshots | `$FLEETAI_PRODUCT_ROOT/jarvismd-backend` | `cto-hba/jarvismd-backend` | FastAPI session APIs, annotation, Summary, SNOMED proxy, GP apply audit |
| transcription, live transcript, recording gaps, resume/audio | `$FLEETAI_PRODUCT_ROOT/transcribe` | `cto-hba/transcribe` | Socket.IO STT. App is transcribe/backend |
| speaker annotation LLM, Summary generation | `$FLEETAI_PRODUCT_ROOT/nlp-services` | `healthbridge-inc/nlp-services` | Celery NLP worker for speaker annotation and Summary generation |
| GP consult template | `$FLEETAI_PRODUCT_ROOT/jmd-gp-consult-template` | `healthbridge-inc/jmd-gp-consult-template` | GP template UI + extract API. Vendor into jmd-frontend after UI changes |
| SNOMED-CT coder | `$FLEETAI_PRODUCT_ROOT/snomed` | `cto-hba/snomed` | SNOMED coding service on its own VM. Browser must not call it |
| chatbot | `$FLEETAI_PRODUCT_ROOT/ask-jarvismd` | `healthbridge-inc/ask-jarvismd` | Ask JarvisMD chatbot |
| credits | `$FLEETAI_PRODUCT_ROOT/credit-manager` | `healthbridge-inc/credit-manager` | Internal credit API |
| FHIR / SystmOne local probe | `$FLEETAI_PRODUCT_ROOT/jmd-xycare` | `healthbridge-inc/jmd-xycare` | Local XYClient/SystmOne probes, not the hosted app |
| world dashboard | `$FLEETAI_PRODUCT_ROOT/jmd-world-dashboard` | `healthbridge-inc/jmd-world-dashboard` | Fleet dashboard |
| public site | `$FLEETAI_PRODUCT_ROOT/healthbridge-homepage` | `cto-hba/healthbridge-homepage` | HBA public website |
| template source notes | `$FLEETAI_PRODUCT_ROOT/jmd-templates` | `cto-hba/jmd-templates` | Template source notes. Not the packaged GP module |

## Runtime flow

`browser mic -> transcribe Socket.IO -> transcript Mongo -> backend normalize -> NLP annotation -> annotated transcript -> Summary -> SNOMED suggestions -> clinician edits -> Save & complete`

- Recording disconnect, resume, or live text: `transcribe/backend`, then the frontend recording context.
- Live text present and annotated text missing: `jarvismd-backend` annotation and `nlp-services`. Compare word counts first. Do not start in the coder.
- Summary omission: prove the fact is in the annotated input, then Summary endpoints and NLP Summary. Do not patch `snomed` to fill a missing summary line.
- SNOMED panel display: `jmd-frontend` reads stamped fields. A clinical rule change belongs in `snomed`.
- GP template UI: edit `jmd-gp-consult-template`, then `npm run vendor:gp-consult-templates -- ../jmd-gp-consult-template` in `jmd-frontend`. Changing the template repo alone does not update the SPA.

## Where domain rules live

Clinical meaning belongs in `$FLEETAI_PRODUCT_ROOT/snomed` (`disposition.py`, `allergen_class.py`, scanner output, `POST /api/snomed/disposition`): what a row is, whether it may be coded, withheld copy keyed by `polarity_reason` or `match_type`, allergen class, absence versus allergy, `conflicts_with`, confirm labels, and allergy vocabulary.

`jarvismd-backend` passes scan rows through unchanged, including missing keys (leave them missing; do not stamp `null` or `false`). It may restamp a frozen completed-consult row by calling SNOMED. It does not invent clinical rules.

`jmd-frontend` only renders fields the service already stamped: `disposition`, `withheld_note`, `confirm_label`, `is_absence`, `allergen_class`, `conflicts_with`, `allergy_vocabulary`. Exact UI copy the clinical safety officer specified may be rendered from those fields. The SPA must not own a parallel table of codes, polarity reasons, or what NKDA means.

Reject a frontend diff that adds literal SNOMED concept ids (for example `409137002`) outside a test fixture, a `polarity_reason` or `match_type` map to withheld sentences (`WITHHELD_NOTES` lives in `snomed/disposition.py`), or an `ABSENCE_ACCEPT_REASONS` or allergen-class conflict table that does not read `conflicts_with` and `allergen_class` from the row. If the panel is compensating for text missing from the annotated transcript or Summary, fix that upstream or report it.

A ticket that looks frontend-only but is a clinical rule routes to `snomed`. If the user said to ask before changing `jarvismd-backend`, stop and report.

## Data handling

Never print secrets. Never paste transcripts, FHIR, or clinical note text into tickets, commits, prompts, or run logs. Session ids, timestamps, counts, and hashes only. Audit stores action, codes, disposition, and polarity_reason — not extracted terms, candidate, evidence, or note text.

## UK evaluation target

"UK" means `https://jarvismd-trial.xycare.co.uk`, not the older HBA UK VM.

| Role | SSH alias |
|---|---|
| UK deploy / runtime | `staging-uk-jmd-xycare-cicd` |
| UK VM admin | `staging-uk-jmd-xycare-admin` |
| Older HBA UK VM | `prod-uk-jmd` |
| SNOMED host | `snomed-uk` |
| Dev JarvisMD VM | `dev-javismd` |
| AU / SG / KH / MX / CA | `prod-au-cicd`, `prod-sg-cicd`, `prod-kh`, `prod-mex-cicd`, `prod-canada-cicd` |

Frontend profile `uk-xycare` points REST and `/transcribe` at the Xycare origin.

## Work rules

- Prefer the local checkout over cloning the remote.
- Check `git status --short --branch` in each affected child repo first.
- Keep existing uncommitted work. Do not switch branches.
- Do not commit, push, or deploy unless the user authorized it.
- UK backend develop/CI branch is `staging/uk-xycare`. `prod/uk` is a no-op in CI.
- `staging/uk-xycare` has no XYCare write-back. Do not import `app.services.xyfhir`.
- If jarvismd-backend is not on `staging/uk-xycare`, stop and say so.
- Frontend `main` does not auto-deploy to the Xycare UK container.
- Happy-path tests are not enough. Check adjacent callers and opposite cases.

## Tests

Find the test file next to the changed module, then run that file.
Do not skip tests because this map is short. Do not run an unrelated
full suite when a focused file covers the change.

- `jmd-frontend`: `NODE_OPTIONS=--localstorage-file=/tmp/jmd-vitest-localstorage npm run test:run -- <file>` from the repo root. Also `npm run build` for UI/API client changes.
- `jmd-gp-consult-template`: `npm test -- --runInBand` then vendor into `jmd-frontend`.
- `transcribe/backend`: `npm test` and `npm run build`. Live AWS tests skip without credentials.
- `jarvismd-backend`: Python 3.13 only. From `app/`: `python -m pytest app/tests/unit/<module> -q`. macOS system Python 3.9 cannot collect the suite.
- `nlp-services`: `python -m pytest tests/test_<area>.py -q` in an env that has the worker deps.
- `snomed`: `pytest tests/` on that repo. The browser must not call it.
