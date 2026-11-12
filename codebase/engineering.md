# Engineering standard

These rules apply to every product. CODE CONTEXT may tighten them. It may not relax them.

## Change

- Solve only the requested problem.
- Edit existing code. Do not add files, helpers, wrappers, or dependencies unless the ticket cannot be solved otherwise.
- No TODOs, placeholders, commented-out code, unused imports, invented APIs, or invented business rules.
- Do not change CI, deploy, auth, secrets, schema, or model settings unless the ticket and the operator both named that work.

## Layers

- Put domain meaning, write policy, conflict policy, and official reason-copy in the service that already stamps those fields.
- A client or UI only renders stamped fields. Do not add a parallel table of identifiers, enums, or canonical copy.
- Do not patch a downstream surface to hide a missing upstream fact. Fix or report the owning stage.

## Investigate

- CODE CONTEXT is the starting map. If it does not name a repo, test, or owning layer, inspect FLEETAI_PRODUCT_ROOT (repos, READMEs, manifests, existing rules). Then git status --short --branch in each candidate repo.
- If you still cannot name a repo, stop.

## Dirty trees

- If a needed file is already dirty from other work, stop. Do not fold a patch into that work.
- Do not switch branch, stash, commit, push, rebase, discard, or deploy.

## Done

- A ticket with named items is not ready because a nearby test passed. List each item as done, not done, or deferred. Deferred only when the ticket says it is a follow-on. Silence is not ready.
- Passing unit tests is not live QA.
- Do not paste secrets or regulated payloads into the result. Prefer ids, timestamps, counts, and hashes.
