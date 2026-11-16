# FleetAI agent-loop improvements (from session practice)

Yes — prompts and the outer loop should be tightened. The staff-engineer bar in `codebase/engineering.md` is already right. The gap is **how the runner uses it**: `execute()` is parse → one solve shot → one verify shot, and the solver prompt starts with “Fix this ticket.”

That is not how tickets were actually closed in production. Below is what to change, with why. Do not inject this file into the agent.

## What FleetAI is today

- Parser (Bedrock) turns email/PDF into software-defect tickets. Process asks are supposed to be dropped.
- Solver (one Cursor `Agent.prompt` in `FLEETAI_PRODUCT_ROOT`) edits the customer checkout.
- Verifier (one more Cursor run) hunts incurred bugs, strips extra complexity, re-runs focused tests.
- `complete()` is the operator’s live QA. Solve/verify must not deploy.
- Context is `engineering.md` then `code-context.md`. If the map is thin, the skill says inspect the product root.

`run_step` is a **single** Cursor call. The verifier’s “repeat until no new bug” lives only inside that one agent. `execute()` does not re-solve a ticket that verify sent back to `unresolved`.

## Should we improve it?

Yes. Not by adding more agent roles or a deployer. By making the **existing** solve/verify loop match the collaboration pattern that actually prevented regressions.

### 1. Investigate is a phase, not a footnote

**Bug in the loop:** `ticket_prompt()` leads with “Fix this ticket.” Validity (“not a defect / evidence contradicts / already in the tree”) is a later sentence. In session, acting first on “trial still runs jmd09nov01” would have merged the wrong repos.

**Change:** Solver prompt order should be:

1. Reconstruct: git status in candidate repos; if the ticket names a runtime, inspect that runtime (image tag, commit, env names — never secrets).
2. Compare ticket claims to that evidence.
3. If the premise is false or stale → `VERDICT: blocked` with the live facts. Do not patch.
4. Only then name the owning layer and edit.

`engineering.md` already says inspect when the map is thin. The prompt still sounds like an implementer. Flip that.

### 2. Gather live context when the ticket is about a running system

**Why:** Unit tests on a dirty laptop do not answer “is the latest coder on the trial app?” The trial app had **no** coder container; it called a shared service. Code-context can say that, but tickets will keep asserting the old story.

**Change:** CODE CONTEXT should tell the solver **how to disprove a runtime claim** (which host, which compose service, which env var name). Solver must not treat the email as the inventory. Parser should keep omitting deploy/retest process, but if a defect depends on “service X is on image Y”, solve is blocked until Y is checked.

### 3. Outer retry loop for incurred bugs

**Bug in the loop:** Verifier may `VERDICT: failed` → status `unresolved`. `execute()` then finishes. Nobody re-solves. In session, green Vitest still left: JSX in a `.ts` file, auto-coded rows showing “Needs review”, CI tests that only fail when Mongo is present.

**Change (orchestrator, still two roles):**

- After verify `failed`, solve that ticket again and verify again until `VERDICT: fixed`.
- Cap: `MAX_SOLVE_ATTEMPTS = 3` in `orchestrator.py`, counting the first solve. At the cap the ticket stays `unresolved`.
- Retry solve receives the truncated verify result and is told the dirty files are its own previous attempt.
- Stop a ticket if the retry solve does not reach `verifying` (blocked / no verdict). That is no progress, not success.
- After verify `fixed`, that is “tests + incurred-bug hunt”, not live QA. Status stays `fixed`; `complete()` remains operator-only.
- Optional: if verify’s result names a remaining named item as not done, do not `fixed`.

Do not add a third “QA agent”. Teach verify to fail closed, and let execute keep solve→verify until the ticket is fixed or blocked.

### 4. Tests must match CI, not only the laptop

**Why:** SNOMED scan-error tests passed locally (no Mongo reuse) and failed in Actions (Mongo URI set → 200 instead of 400/503/500). Solver would have marked `ready`.

**Change:**

- CODE CONTEXT: “run the focused file the way CI runs it” (same services, same env flags). If CI injects a DB the laptop lacks, say so, or skip-and-block.
- Verifier hunt list: tests that pass only because a dependency is missing; tests that import deleted symbols; tests with JSX in a non-JSX file.
- `ready` requires the focused command that CI would run for that repo, not “a nearby test passed.”

### 5. Cross-service contract, not per-file green

**Why:** New FE treated missing `disposition` as withheld. FE/BE overlay went live; coder image did not. Named FE items looked done in tests and failed on the wire.

**Change:**

- Before `ready`, if the change **reads stamps from another service**, list that service’s field as present in that repo (or live image) or mark the item **not done / blocked**.
- Verifier fails a client that compiles in behaviour the upstream payload cannot yet produce, unless the ticket says the client must fail closed and the named items are only the client contract.
- Named-item list must be per requirement, including “depends on service X deploy” as deferred only when the ticket said it is follow-on.

### 6. Wrong-layer and over-build are first-class incurred bugs

Session: FE grew hardcoded concept ids, conflict matrices, and copy tables; user rejected them; meaning moved to the stamping service; FE shrank.

Verifier already hunts “domain rules in the wrong layer” and “extra complexity.” Make that **fail**, not a polish pass:

- New identifier / policy / canonical-copy table in a UI/client when CODE CONTEXT says another service owns it → `VERDICT: failed` (fixtures allowed).
- New wrapper/helper/file that is not required to solve the ticket → strip or fail.
- Downstream patch that hides a missing upstream fact → fail.

Solver prompt should say “prefer moving a stamp upstream over adding a client table” and “if that needs another repo the operator forbade, stop and ask.”

### 7. Parser should not mint merge/deploy tickets from stale ops mail

**Why:** A later note asked to merge main into a branch and pipeline-deploy a trial coder that does not exist. Parser is supposed to drop process asks. If it still emits “rebuild the trial coder”, the solver will try.

**Change:** Parser prompt: omit rebuild/merge/redeploy/image-tag requests unless they describe a **software defect in product code**. “Send me the tag” is not a ticket. Validity in solve is the backstop.

### 8. Do not add agents for this

Keep parse / solve / verify / complete. Extra roles (planner, deployer, researcher) would fight dirty-tree and deploy rules.

Improve:

| Layer | What |
|---|---|
| `ticket_prompt()` | Investigate → validity → owning layer → smallest patch → CI-shaped test → named-item list → verdict |
| `verify_prompt()` | Hunt list includes CI/env skew, wrong-layer tables, fail-closed vs missing upstream, adjacent UI fall-through |
| `execute()` | Re-solve after `failed` until `fixed`, blocked, or `MAX_SOLVE_ATTEMPTS` |
| `engineering.md` | One short “investigate before patch” and “passing tests are not the runtime” already exist; add CI-shaped tests and stale-ticket block |
| `code-context.md` | How to inspect this customer’s runtime (hosts, service names, env **names** only) |

## What not to do

- Do not auto-deploy from solve/verify.
- Do not ingest this note into the Cursor prompt.
- Do not encode one customer’s hosts or concept ids into `solver.py` / `verifier.py`.
- Do not add a skills directory. One `engineering.md` remains the runner skill.

## Done looks like

A ticket whose email is wrong about the runtime is `blocked` with evidence, not a speculative merge. A client change that needs an upstream stamp is not `ready` until that stamp exists or the item is listed not done. Verify that only ran laptop tests while CI has extra services cannot `fixed`. Execute keeps solve→verify on a failed ticket until it is `fixed`, the solver blocks, or `MAX_SOLVE_ATTEMPTS` is reached. Operator `complete()` is still the only live QA.
