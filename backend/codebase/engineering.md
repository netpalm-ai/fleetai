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
- If the ticket names a running system, inspect it the way CODE CONTEXT says. If the ticket's premise is false, stop.
- If you still cannot name a repo, stop.

## Root cause

- Find the cause before you design a fix. Follow the failing behaviour through the code to the line that produces it. If the ticket names a running system, read its stored data or logs too.
- State the cause in one sentence: which function in which repo does what wrong, and for which input. If you cannot, stop. A change you cannot explain this way is a guess.
- Fix the cause. A guard, default, retry, or catch added where the symptom shows is not a fix unless that place owns the rule.

## Design

Settle these before the first edit.

- Owner: the one module that should change, and why it owns the rule. If the smallest diff and the owning module disagree, the owner wins.
- Contract: each field, type, endpoint, event, or stored shape the change alters, and every consumer of it. Stored data and callers that are not released with this change must keep working.
- Alternative: the simplest other fix, and why it is worse.
- Failure: what the new code does with missing data, an error from a dependency, and a repeated or concurrent call.
- Fit: write it the way that file already does it: naming, error handling, logging, test style. Reuse what exists before adding anything.
- Size: no option, flag, or abstraction that has one caller. The reviewer who owns the module should have nothing to remove.
- If the same cause breaks other callers, fix it where they share it. Report related defects you found and did not change.

## Dirty trees

- If a needed file is already dirty from other work, stop. Do not fold a patch into that work.
- Dirty files from this ticket's own previous attempt are not other work. Continue from that diff.
- Do not switch branch, stash, rebase, discard, or deploy.
- Do not commit or push while solving or while verifying may still change the diff.

## Ship

- After the ticket is fixed, commit only this ticket's files on the current branch of each touched child repo, then push that branch.
- One commit per child repo. Message: `fleetai: <ticket-id>`.
- Never force-push, never amend a commit you did not just create, never push a different branch, never commit someone else's dirty files.

## Tests

- Write the regression test first and see it fail for the stated cause. Then fix. A test that passes without the fix proves nothing.
- Run CODE CONTEXT's test command for every repo the diff touches, the way that product's CI runs it (same extra services and env flags). Ticket-file tests alone are not enough.
- Also run tests of adjacent consumers CODE CONTEXT names, and opposite cases.
- A test that passes only because a CI service is missing is not a pass.

## Done

- A ticket with named items is not ready because a nearby test passed. List each item as done, not done, or deferred. Deferred only when the ticket says it is a follow-on. Silence is not ready.
- If a named behaviour needs a field another service stamps, that item is not done until the stamp exists in that service.
- Passing unit tests is not live QA.
- Do not paste secrets or regulated payloads into the result. Prefer ids, timestamps, counts, and hashes.
