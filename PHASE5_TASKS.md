# Phase 5 tasks: access control, deletion, interface accessibility

Branch: `Jon-Gus_branch` (based on `Gustavo` `c880566`). Scope: REQ-14 and REQ-15
(interface part), acceptance tests AC-15, AC-16 and AC-17, Operation 14, and the
`deletion_failures` fault.

## How to run this list unattended

Start a session in this folder, switch to auto mode or accept-edits mode, and run:

```
/loop Work on PHASE5_TASKS.md: take the first item marked [ ], follow the Rules section exactly, then stop this iteration. End the loop when no [ ] items remain.
```

## Rules (read every iteration)

1. **Branch.** Work only on `Jon-Gus_branch`. Never create, switch or delete branches,
   and never push, merge, rebase or reset.
2. **Minimal code.** Load the `minimal-code` skill before writing code, and follow it.
3. **One item per iteration.** Take the first `[ ]` item in order. Read its sources, write
   the code and the tests that prove its "Done when" line, then run
   `python scripts/test_gate.py`. It must print `GATE PASSED`. Never edit
   `scripts/test_baseline.json` or run the gate with `--update`, and don't fix the
   inherited failing tests.
4. **Commit.** Stage only the files the item changed (by name; never `git add -A` or
   `git add .`). Commit with the message `Phase 5 <ID>: <summary>`, ending with a blank
   line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Don't commit
   `AGENTS.md`, `CLAUDE.md`, `PHASE5_TASKS.md`, `PHASE5_DECISIONS.md`,
   `PHASE5_REPORT.md`, `.claude/`,
   `scripts/test_gate.py`, `scripts/test_baseline.json`, `Lab2/` or the PDF.
5. **Mark progress.** Change `[ ]` to `[x]` and add one line under the item: the commit
   SHA and what was verified.
6. **Ambiguity: give options, don't choose.** If an item depends on a choice that the
   Phase 5 specification, the code or AGENTS.md doesn't settle, don't implement any
   choice. Add an entry to `PHASE5_DECISIONS.md` with **1 to 5 meaningfully different
   options**, using the format in that file. Each option needs its pros, cons and code
   size, and at most one can be marked recommended. Mark the item `[B] (D<n>)` and move
   on to the next item. This always applies to:
   - interface accessibility choices that change what users see or do (AC-17), and how
     it is scanned or evidenced;
   - deletion behavior not spelled out in spec §10 (what is removed, when, and how
     failures are recovered);
   - access rules not spelled out in spec §4 (who may read or change what).

   When an entry in `PHASE5_DECISIONS.md` is `CHOSEN`, set its item back to `[ ]` and
   implement the chosen option.
7. **Human-only work.** Items marked `[H]` need a person (Excel, a browser, a
   deployment). The agent only writes the checklist or evidence template the item
   asks for, then leaves the item as `[H]`.
8. **Shared contract.** Paths, status codes, error codes and response shapes must match
   specification 3.0.0 exactly. Read it with
   `MSYS_NO_PATHCONV=1 git show origin/Logan-tester-phase5:ref/Phase5_Agent_Context_Pack/Phase5_Shared_Specification.md`.
   Assertion texts are in `phase5-test-plan.json` in the same folder; search it by
   `test_id`. Never change an existing endpoint's behavior beyond what the item says.
9. **Never:** run `scripts/deploy-*.ps1` or `update-ec2-demo.ps1`, call AWS, read `.env`
   or secrets, add dependencies, or change files outside this repo.
10. **Stop condition.** When no `[ ]` items remain, fill in the "Final summary" section of
    `PHASE5_REPORT.md` (see rule 11) and end the loop.
11. **Report for manual review.** At the end of every iteration, before stopping, append
    one entry to the "Log" section of `PHASE5_REPORT.md`, using the entry format in
    that file. Write it for a reviewer who wasn't watching:
    - **Outcome:** done, blocked, human-only or failed, with the commit SHA if there is one.
    - **Changes:** each file changed and what changed in it, in plain words. Include
      any endpoint, status code, error code or database table added or changed.
    - **Decisions and assumptions:** every judgment call the specification didn't
      dictate, however small (naming, where code lives, what a test covers and what it
      leaves out), and why. Link decision entries as `D<n>`.
    - **Verification:** the tests added, the gate result line, and anything that was
      **not** verified.
    - **Review notes:** risks, shortcuts, behavior that differs from the specification,
      and the exact places a reviewer should look first.

    Append only: never edit or remove earlier entries. If something in an earlier entry
    turns out to be wrong, add a correction in the new entry. An iteration that stops
    because of an error still writes its entry.

Test conventions: put new tests in `tests/test_phase5_<area>.py`, and build the app the
way `tests/test_phase4_service.py` does (temporary database, `create_app(...)` with
explicit tokens and reviewer grants).

## Access control (REQ-14, AC-15)

- [ ] **ACC-1: Check the order of access checks on the existing routes.** Spec §4
  requires this order: authenticate, check the test session, find the resource in its
  namespace, authorize, and only then validate state and body. An unknown or
  wrong-namespace resource returns 404, and an identified same-namespace resource that
  belongs to someone else returns 403. Workbook bytes are never read before
  authorization.
  Done when: one table-driven test covers operations 3–10, S, V and R for the owner, a
  granted reviewer, an ungranted reviewer, a foreign user, no token, an invalid token
  and a test-admin, and it passes. (Assertions: the inherited `P4-ACCESS-*` group.)
- [ ] **ACC-2: Reviewer permissions.** Granted reviewers can read but never upload,
  re-audit, remediate or delete. Ungranted reviewers are denied like a foreign user.
  Done when: tests cover the reviewer cases in ACC-1 and the reviewer cases of the
  delete route from DEL-1. If the current owner-wide grant model in
  `REVIEWER_GRANTS_JSON` conflicts with the word "explicitly" in the spec, write a
  decision entry.
- [ ] **ACC-3: Denials reveal nothing.** The bodies and headers of 401, 403 and 404
  responses contain no filename, hash, owner, version or audit ID, and no timestamp
  from the resource.
  Done when: a test asserts this for each denial type on at least one route per
  resource kind.
- [ ] **ACC-4: Transport and credential review.** Read `infrastructure/aws.yaml`,
  `Dockerfile` and `scripts/` (read only, never run them), and record whether plain HTTP
  is rejected or redirected, and how tokens are stored. The answer goes in
  `docs/phase5_security.md`, under 40 lines.
  Done when: that document exists and states the current behavior with file
  references. Any gap (for example tokens stored in plaintext) becomes a decision entry,
  not a code change. (Assertion: `P5-MANUAL-HTTPS-CREDENTIALS`.)

## Deletion (Operation 14, AC-16)

- [ ] **DEL-1: `DELETE /api/v1/workbooks/{workbookId}`.** Owner only. Returns 204 with
  no body after removing the workbook's versions, source bytes, audits, findings and
  review context, reports, decisions, remediations, outputs, history, idempotency
  records (`p4_keys`), finished jobs, and the rows in the legacy `versions`/`audits`
  tables. Afterwards every old URL returns 404, a repeated DELETE returns 404, and other
  workbooks and namespaces are unchanged. The route appears in OpenAPI with its error
  responses.
  Done when: tests pass for `P5-DELETE-COMPLETE`, `P5-DELETE-OLD-URLS`,
  `P5-DELETE-REPEAT`, `P5-DELETE-OTHER-DATA`, `P5-DELETE-RETAIN-TESTER` and all nine
  `P5-ACCESS-DELETE-*` cases. Schedules and notifications don't exist on this branch,
  so that part is decided by a decision entry.
- [ ] **DEL-2: Block deletion during active work.** An active audit, remediation or
  upload returns 409 `ACTIVE_OPERATION` and changes nothing. While a deletion is in
  progress, new uploads, re-audits and remediations for that workbook are refused, so a
  race has exactly one consistent winner.
  Done when: tests pass for `P5-DELETE-ACTIVE-AUDIT`, `P5-DELETE-ACTIVE-REMEDIATION`,
  `P5-DELETE-ACTIVE-UPLOAD` and `P5-DELETE-RACE`.
- [ ] **DEL-3: The `deletion_failures` fault.** Test sessions accept
  `setup.faults.deletion_failures: 1`, following the spec §11 rules (exactly the integer
  1, unknown keys rejected, one use only, counter kept durably, rejected requests don't
  use it up). The next valid owner DELETE in that session fails with 500
  `TEST_DELETION_FAILURE` before anything is removed, the workbook stays readable, and
  a retry returns 204. Ordinary data is never affected.
  Done when: tests pass for `P5-FAULT-DELETION`, `P5-DELETE-FAIL-ONCE` and the
  `P5-FAULT-REJECT-*` cases that apply to this key.
- [ ] **DEL-4: Recoverable deletion.** Keep a durable deletion reservation. If a real
  partial failure happens, return 500 `DELETION_FAILED`, return 404 to ordinary reads and
  writes of that workbook, and keep the reservation. A retry by the owner finishes the
  cleanup, and other users get no access to the reservation.
  Done when: a local test that forces a storage failure partway through passes
  (`P5-DELETE-RECOVER`).
- [ ] **DEL-5: Resume deletion after a restart.** Startup recovery
  (`phase4_jobs.Runner.recover`) finishes pending deletions, so a deleted workbook never
  comes back.
  Done when: a restart test passes (`P5-LOCAL-DELETE-RESTART`).
- [ ] **DEL-6: Backups and stored copies.** Document in `docs/phase5_security.md` how
  deletion reaches PostgreSQL rows, RDS automated backups (kept 1 day) and any copies
  the application manages, and why a restore can't bring back an acknowledged deletion.
  Done when: that section exists. Any policy choice becomes a decision entry.
  (Assertions: `P5-DELETE-RESTORE`, `P5-DELETE-OBJECT-VERSIONS`,
  `P5-MANUAL-DELETE-BACKUPS`.)
- [ ] **DEL-7: Cancel scheduled work.** No audit or reminder runs for a deleted workbook
  (`P5-DELETE-CANCEL-FUTURE`). The scheduler isn't on this branch, so write a decision
  entry and mark this item `[B]`, unless that entry is already `CHOSEN`.

## Interface accessibility (REQ-15, AC-17, spec §16)

- [ ] **UI-1: Inventory the interface.** List every control, input, status message and
  error display in `static/index.html` under this item, as a short checklist. No code.
  Done when: the list is written here.
- [ ] **UI-2: Labels and names.** Every input has a programmatic label, and every button
  and link has an accessible name.
  Done when: a test parses `static/index.html` with the standard-library `html.parser`
  and asserts this.
- [ ] **UI-3: Visible focus.** Every interactive element has a visible `:focus-visible`
  style, and no `outline: none` is left without a replacement.
  Done when: the CSS is fixed and the UI-2 test also checks this rule.
- [ ] **UI-4: Errors and status as text.** Errors are shown as text next to their
  control or in a `role="alert"` region. Progress and status updates are announced
  through an `aria-live="polite"` region, never by color alone.
  Done when: the markup is fixed and the UI-2 test checks that the live regions exist.
- [ ] **UI-5: Contrast.** Normal text is at least 4.5:1 and large text at least 3:1, in
  every state the page uses.
  Done when: each text/background color pair is listed with its computed ratio under this
  item, and every failing pair is fixed. If fixing one changes the page's look, write a
  decision entry instead.
- [ ] **UI-6: Keyboard operation.** The order follows the visual flow, there is no
  positive `tabindex` and no keyboard trap, and every action works with Enter or Space.
  Done when: the markup is fixed and the UI-2 test asserts there is no positive
  `tabindex` and no clickable non-button elements.
- [ ] **UI-7: Delete control.** Add an owner-only delete control for DEL-1, with an
  explicit confirmation that names the workbook (spec §16). It works by keyboard, and
  the result is announced in the live region.
  Done when: DEL-1 is done and the UI-2 test covers the new control.
- [ ] **UI-8: Automated scan.** Choose and run a scanner on every screen. Adding a
  scanner means a new dependency or tool, so start with a decision entry and mark this
  item `[B]` until it is chosen.
- [H] **UI-9: Manual keyboard walkthrough and scan evidence.** The agent writes
  `docs/phase5_accessibility_evidence.md`: a step list for completing upload, findings,
  corrections, download and delete by keyboard only, plus blank tables for the scan
  results and contrast checks. Jon carries it out.
  (Assertions: `P5-MANUAL-KEYBOARD`, `P5-MANUAL-A11Y-SCAN`.)

## Out of scope for this list

Scheduling, reminders, notifications, the test clock, fault types other than
`deletion_failures`, performance (AC-18) and the tester. Haruki and Logan own those, and
this list must not touch them.
