---
name: minimal-code
description: Write the least code that completes a task. Load before implementing or changing any code in this repo, including every PHASE5_TASKS.md item, and apply it to every diff before committing.
---

# Minimal code

The goal is the smallest correct diff: fewer lines to review, fewer places to break, and
nothing the team has to maintain that the task didn't need.

## Before writing

1. Reread the task's "Done when" line. Build only that. Don't build for later items, other
   phases or hypothetical callers.
2. Search for existing code that already does part of the job, and call it or extend it in
   place. In this repo, check `phase4_service.py` (`lookup`, `user`, `check_active`,
   `ApiError`), `phase4_store.py`, `phase4_jobs.py`, `test_interface.py` and the existing
   test helpers in `tests/` before adding anything new.
3. Prefer changing an existing function over adding a new one, a new function over a new
   class, and a new function over a new module.

## While writing

- No new dependencies. If a task can't be done without one, stop and record it in
  `PHASE5_DECISIONS.md` instead.
- No speculative options, flags, config keys, abstract base classes, registries or
  plugin points.
- No defensive code for situations the code can't reach. Validate at the boundary
  (request parsing, file input) only.
- Don't refactor, rename, reformat or "tidy" code the task doesn't require. Leave the
  inherited failing tests alone.
- Comments only where the reason isn't obvious from the code. No docstrings restating
  the function name.
- Tests: write the fewest tests that prove the "Done when" line, including its
  rejection and denial cases. Reuse existing fixtures and helpers. Prefer one table-driven
  test (`subTest`) over many near-copies.
- HTML/CSS for accessibility: fix the markup (labels, roles, focus styles, contrast
  values) rather than adding JavaScript or a framework.

## Before committing

Review `git diff` and remove anything the task didn't strictly need: unused imports,
helpers called once that could be inlined, duplicated logic, debug output and
commented-out code. If the diff touches a file unrelated to the task, revert that part.
Then run `python scripts/test_gate.py`; it must print `GATE PASSED`.
