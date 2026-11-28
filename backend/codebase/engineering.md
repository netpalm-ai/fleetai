# Engineering standard

These rules apply to every product. CODE CONTEXT may tighten them. It may not relax them.

## Database

- Do not delete a database record.
- Do not write SQL that removes rows, truncates a table, drops stored data, or otherwise destroys a database.
- Do not run a test, script, or migration against a database that already holds records.

## Layers

- Put domain meaning, write policy, conflict policy, and official reason-copy in the service that already stamps those fields.
- A client or UI only renders stamped fields. Do not add a parallel table of identifiers, enums, or canonical copy.
- Do not patch a downstream surface to hide a missing upstream fact. Fix or report the owning stage.

## Investigate

- CODE CONTEXT is the starting map. If it does not name a repo, test, or owning layer, inspect FLEETAI_PRODUCT_ROOT (repos, READMEs, manifests, existing rules). Then git status --short --branch in each candidate repo.
- If the ticket names a running system, inspect it the way CODE CONTEXT says. If the ticket's premise is false, stop.
- If you still cannot name a repo, stop.

## Dirty trees

- If a needed file is already dirty from other work, stop. Do not fold a patch into that work.
- Dirty files from this ticket's own previous attempt are not other work. Continue from that diff.
- Do not switch branch, stash, commit, push, rebase, discard, or deploy.

## Tests

- Run CODE CONTEXT's test command for every repo the diff touches, the way that product's CI runs it (same extra services and env flags). Ticket-file tests alone are not enough.
- Also run tests of adjacent consumers CODE CONTEXT names, and opposite cases.
- A test that passes only because a CI service is missing is not a pass.

## Done

- A ticket with named items is not ready because a nearby test passed. List each item as done, not done, or deferred. Deferred only when the ticket says it is a follow-on. Silence is not ready.
- If a named behaviour needs a field another service stamps, that item is not done until the stamp exists in that service.
- Passing unit tests is not live QA.
- Do not paste secrets or regulated payloads into the result. Prefer ids, timestamps, counts, and hashes.
