# Dev rules

## Change

- Solve only the requested problem.
- Make the smallest change. Use the fewest lines that solve it.
- Edit existing code. Do not add files, helpers, wrappers, or dependencies unless the ticket cannot be solved otherwise.
- No TODOs, placeholders, commented-out code, unused imports, invented APIs, or invented business rules.
- Do not change CI, deploy, auth, secrets, schema, or model settings unless the ticket and the operator both named that work.
- Reuse existing functions, types, and paths. Do not add a parallel copy. Do not rewrite unrelated code.

## Tests

When you add a test, read the tests that already cover that behavior. Do not add a test that repeats one already there.
