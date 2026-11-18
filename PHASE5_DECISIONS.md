# Phase 5 decisions needed

The agent writes an entry here whenever a task depends on a choice that the specification,
code or AGENTS.md doesn't settle (see the rules in `PHASE5_TASKS.md`). Jon picks an
option, and the pod confirms anything that affects the shared contract. Once an option is
chosen, write it under **Chosen** and the agent implements it.

## Entry format

```
## D<n>: <short question>  (blocks: <task IDs>)
Status: OPEN | CHOSEN (option <x>, <date>)
Context: <what is ambiguous and why, with spec section or file references>

1. <option name>: <what it does>. Pros: ... Cons: ... Code size: small/medium/large.
2. ...
(1 to 5 options, each meaningfully different, not variations of one idea.
 Mark at most one "(Recommended)" and say why.)

Chosen: <filled in by Jon>
```

## Known open questions

These are already known to need a decision. The agent writes the options when it first
reaches the blocked task.

- Deletion of schedules and notifications: those tables exist only on the unmerged
  `haruki/phase5-schedule` branch (blocks DEL-1).
- How deletion reaches backups and stored copies: RDS automated backups are kept for
  1 day, and spec §10 requires documenting this (blocks DEL-6).
- Design of the durable deletion reservation (blocks DEL-4, DEL-5).
- The reviewer grant model: `REVIEWER_GRANTS_JSON` currently grants access to every
  workbook an owner has, not to individual workbooks (blocks ACC-2).
- "No plaintext passwords": the service uses bearer tokens stored in
  `API_TOKENS_JSON`/Secrets Manager, not passwords (blocks ACC-4).
- Which automated accessibility scanner to use, and how to run it without adding
  dependencies (blocks UI-6).

## Entries

## D1: How fine-grained is a reviewer grant?  (blocks: ACC-2)
Status: OPEN
Context: Spec §4 says "Explicitly granted reviewers can read ... an ungranted reviewer is
denied", but doesn't say what a grant covers. Today `REVIEWER_GRANTS_JSON` maps a reviewer
to a list of owners (`{"reviewer": ["owner"]}`), so one grant covers every workbook that
owner has now or uploads later, in every namespace. Any subject listed as a key is treated
as read-only everywhere (`phase4_service.py` `lookup`, `upload_to`, `review`). The pack has
no grant endpoint, and the P5-ACCESS-*-GRANTED-REVIEWER / -UNGRANTED-REVIEWER cases only
check 200/403 for a preconfigured reviewer, so the tester can't create grants itself.
Separately, ACC-2's delete-route reviewer cases (P5-ACCESS-DELETE-GRANTED-REVIEWER,
-UNGRANTED-REVIEWER) can't be tested until DEL-1 adds the route, whichever option is chosen.

1. Keep owner-wide grants (Recommended): treat the configured reviewer-to-owner entry as the
   explicit grant, document this in docs/phase5_security.md, and finish ACC-2 with tests
   only. Pros: no behavior change; works with the tester, which can only use preconfigured
   grants; matches the Phase 4 tests and the reviewer gate already passing. Cons: a grant
   silently covers the owner's future workbooks; revoking it needs a config change and a
   restart; no per-workbook control. Code size: small (tests and a doc paragraph).
2. Per-workbook grants in config: allow `REVIEWER_GRANTS_JSON` values to name workbook IDs
   (for example `{"reviewer": {"owner": ["workbook-..."]}}`), checked in `lookup`.
   Pros: each grant names exactly what it covers. Cons: workbook IDs exist only after
   upload, so an operator must edit config and restart after each upload; the hosted
   tester can't grant the workbooks it creates, so the GRANTED-REVIEWER cases would fail
   unless a wildcard is kept. Code size: medium.
3. Owner-managed grants through the API: a new table and owner-only endpoints to grant and
   revoke a reviewer per workbook. Pros: genuinely explicit and revocable by the owner; no
   restart. Cons: adds endpoints outside specification 3.0.0, so it needs pod agreement
   (rule 8) and Team 9 parity; the tester still can't use it without a plan change.
   Code size: large.

Why 1 is recommended: it is the only option the shared tests can exercise without a
contract change, and the spec's wording is satisfied when a grant has to be configured
explicitly per reviewer.

Chosen:

## D2: Should plain HTTP be rejected rather than redirected?  (blocks: none; ACC-4 gap)
Status: OPEN
Context: REQ-14 says "HTTPS only". On the EC2 demo, Caddy listens on port 80 and, by
default, redirects to HTTPS (`scripts/deploy-ec2-demo.ps1` lines 47-48, 66). A client that
sends `Authorization: Bearer ...` over HTTP has already exposed the token before the
redirect. Spec §5 also says "Do not redirect project requests". The ECS stack's HTTP
behavior isn't visible in `infrastructure/aws.yaml`. The app sends no HSTS header.
See docs/phase5_security.md.

1. Keep the redirect and document it: no change. Pros: zero risk; browsers that type
   `http://` still reach the site. Cons: a token sent over HTTP is exposed; arguably
   conflicts with §5's "do not redirect". Code size: none.
2. Reject HTTP for project paths in Caddy (Recommended): in the Caddyfile, keep port 80 only
   for ACME certificate challenges and return an error such as 403 for everything else, and
   add a `Strict-Transport-Security` header on HTTPS. Pros: meets "HTTPS only" and §5;
   HSTS stops repeat browser visits from using HTTP. Cons: changes the deploy script
   (a human must redeploy); a user typing `http://` sees an error page. Code size: small
   (a few Caddyfile lines in the EC2 deploy script; a human applies them on the live instance).
3. App-level guard: middleware that refuses requests whose `X-Forwarded-Proto` is `http` and
   adds HSTS. Pros: works behind any proxy, including ECS, and is testable locally.
   Cons: relies on the proxy setting that header correctly; uvicorn would need
   `--proxy-headers` and trusted proxy settings, and a spoofed header is possible when
   the app is exposed directly. Code size: small to medium.

Why 2 is recommended: it fixes the exposure where it happens (at the TLS front end), and
the only HTTP traffic it keeps is the certificate challenge.

Chosen:

## D3: Are plaintext bearer tokens acceptable under "no plaintext passwords"?  (blocks: none; ACC-4 gap)
Status: OPEN
Context: The service has no passwords. `API_TOKENS_JSON` and `TEST_ADMIN_TOKENS_JSON` map
plaintext tokens to users. They are kept in Secrets Manager (ECS) or a root-only env file
(EC2 demo) and compared in memory with `secrets.compare_digest` (`phase4_service.py` `user`).
Anyone who can read the secret or the env file can use every token.

1. Accept and document (Recommended): tokens are random (48 or 64 characters), are not
   user-chosen passwords, and are stored only in access-controlled secret stores. Pros: no
   change; tokens are high-entropy, so hashing protects much less than it does for
   passwords. Cons: a leaked secret store reveals usable tokens. Code size: none (the
   doc already states it).
2. Store SHA-256 hashes of tokens: configuration maps `sha256(token)` to a user, and
   `user` hashes the presented token before comparing. Pros: a leaked config holds no
   usable tokens; small change. Cons: every deployment's secret has to be regenerated in the
   new format (a human, on AWS); a format change other teams' testers must be told about if
   they configure tokens. Code size: small (about 5 lines plus test setup changes).
3. Replace tokens with username/password login and salted password hashes (for example
   `hashlib.scrypt`) issuing short-lived tokens. Pros: matches the literal "password"
   wording. Cons: a new login endpoint outside specification 3.0.0 (pod agreement, rule 8);
   the shared tester uses bearer tokens. Code size: large.

Why 1 is recommended: REQ-14's concern is user passwords, and there are none. Random
bearer tokens in a managed secret store is standard practice. Option 2 is a cheap
hardening if the pod wants it.

Chosen:

## D4: How does deletion remove schedules and notifications that this branch doesn't have?  (blocks: none; DEL-1 part)
Status: OPEN
Context: Spec §10 says a 204 comes only after "notification records and schedules" are
removed too, and P5-DELETE-COMPLETE / -OLD-URLS check the schedule and notification URLs.
The schedule table (`p5_schedules`) and Op 11/G exist only on the unmerged
`haruki/phase5-schedule` branch. Notifications (Op 12) don't exist anywhere yet. DEL-1
deletes everything this branch stores, in one transaction (`phase4_service.py`
`delete_workbook`). The schedule and notification URLs return 404 here today only because
those routes don't exist.

1. Extend at merge time (Recommended): when `haruki/phase5-schedule` (and later the
   notifications work) is merged into this branch, add `p5_schedules` and the notification
   table to the `DELETE ... WHERE workbook_id=?` list in `delete_workbook`, plus their URLs to
   tests/test_phase5_delete.py. Record this as a merge checklist item for whoever merges.
   Pros: no speculative code; the change is one table name per feature. Cons: relies on
   the merger remembering it (mitigated by the checklist); the schedule URL assertions
   can't run until then. Code size: small (later).
2. Owner-registered cleanup hook: give `create_app` a list of per-workbook cleanup functions
   that Phase 5 modules register, and have `delete_workbook` call each one inside its
   transaction. Pros: a scheduling module plugs itself in without editing the delete
   route. Cons: a new extension point with no current user (against minimal-code); Haruki's
   branch would have to adopt it. Code size: small to medium.
3. Merge the schedule branch first: a person merges `haruki/phase5-schedule` into
   `Jon-Gus_branch` (the agent may not merge, rule 1), then DEL-1 is extended and tested
   against real schedules before DEL-2 starts. Pros: deletion is verified against real
   schedule rows now. Cons: it pulls schedule work into this list's scope (out of scope
   per PHASE5_TASKS.md) and needs a human merge first. Code size: small (after the merge).

Why 1 is recommended: it keeps this branch inside its scope and adds nothing until the
tables exist, and the remaining change is mechanical.

Chosen:

## D5: Design of the durable deletion reservation and recoverable cleanup  (blocks: DEL-4, DEL-5)
Status: OPEN
Context: Spec §10 requires "a durable deletion reservation and recoverable cleanup": on a
partial failure, return 500 `DELETION_FAILED`, keep the cleanup intent, answer 404 to
ordinary reads and writes, let the owner's retry finish the same cleanup, and give other
identities no access to the reservation. Spec §12 also lists 409 `DELETION_IN_PROGRESS`
without saying when it applies. P5-DELETE-RECOVER needs a forced failure partway through,
and P5-LOCAL-DELETE-RESTART needs restart recovery. Today (DEL-1 to DEL-3) the delete is a
single database transaction (`phase4_service.py` `delete_workbook`). It is atomic, so a
"partial" failure can't happen: any error rolls back and the workbook stays intact. The
spec doesn't say where the reservation lives, how the cleanup is split into steps, or how
concurrent DELETEs behave while a reservation exists.

1. Reservation table plus stepwise cleanup (Recommended): a new table
   `p5_deletions (workbook_id, owner, namespace, created)`. Transaction 1 runs today's
   checks (auth, active work, the DEL-3 fault) and inserts the reservation. Each table is
   then deleted in its own committed step, and the reservation row is removed last.
   `lookup` returns 404 for any workbook with a reservation, except for the owner's DELETE,
   which resumes the remaining steps (every step is idempotent). Any exception after
   transaction 1 returns 500 `DELETION_FAILED` and leaves the reservation in place.
   `Runner.recover()` resumes every reservation at startup (DEL-5). A second DELETE that
   arrives while one is mid-flight in another request waits on `fence` and then resumes,
   so `DELETION_IN_PROGRESS` isn't used.
   Pros: matches §10 literally; the partial failure and restart tests are meaningful; the
   reservation holds no content (just IDs). Cons: one extra table and a check in `lookup`
   on every route; more transactions per delete. Code size: medium.
2. Same as option 1, but 409 `DELETION_IN_PROGRESS` for overlapping deletes: identical
   storage and recovery, but a DELETE that finds a reservation created by a request
   still running (tracked by a short lease, as for uploads) returns 409
   `DELETION_IN_PROGRESS` instead of joining. Only a stale reservation (the request
   failed or the lease expired) is resumed by the owner's retry. Writers that hit a
   reservation also get 409 `DELETION_IN_PROGRESS` instead of 404.
   Pros: gives the §12 code a concrete meaning; concurrent deletes never do duplicate work.
   Cons: conflicts with §10's "make the workbook unavailable to ordinary reads/writes with
   404" for writers (or needs a split: reads 404, writes 409); one more lease to manage.
   Code size: medium.
3. Keep the single atomic transaction and record the intent only for restarts: the
   reservation row is inserted and removed inside the same transaction as all the
   deletes, so a failure rolls everything back and the workbook stays readable (allowed by
   §10: "A failed request that is known to have made no destructive change may leave the
   original readable"). DEL-4/DEL-5 become documentation plus a rollback test.
   Pros: smallest; no partial states exist. Cons: arguably doesn't satisfy "use a durable
   deletion reservation and recoverable cleanup"; P5-DELETE-RECOVER ("partial ...
   failure hides workbook, retains intent") can't be shown, because no partial state
   exists; a very large workbook is deleted in one long transaction against the 30 s
   DELETE bound. Code size: small.

Why 1 is recommended: it is the most direct reading of §10 and makes both local
assertions testable. `DELETION_IN_PROGRESS` can be adopted later (option 2) if the pod
gives it a meaning.

Chosen:

## D6: How are backups and copies kept from resurrecting a deleted workbook?  (blocks: none; DEL-6 gap)
Status: OPEN
Context: Spec §10 says deletion also covers "application-managed copies/backups that would
otherwise preserve that content" and "A restore must never resurrect an acknowledged
deletion"; only content-free evidence such as an opaque deletion key may remain. Today
(docs/phase5_security.md, "Deletion, backups and copies"): RDS keeps 1 day of automated
backups plus a non-expiring final snapshot on stack deletion or replacement
(`infrastructure/aws.yaml` lines 60-61, 73); the EC2 release script writes a
`pre-deploy-<release>.sqlite3` copy on every release and never prunes it; SQLite keeps
deleted pages until reused. Nothing records deleted IDs outside the database, so any
restore brings deleted workbooks back.

1. Deletion ledger outside the restore scope, plus bounded copies (Recommended): append
   each acknowledged deletion's opaque workbook ID and time to a ledger that isn't in the
   database backups (for example a small append-only file on a separate volume on EC2, or
   CloudWatch Logs / an S3 object on ECS), and on startup re-delete any ledger ID found in
   the database. Also: prune pre-deploy SQLite copies after a successful release (or keep
   at most one, at most 1 day), set `DeletionPolicy: Delete` or document manual snapshot
   deletion, and enable `PRAGMA secure_delete=ON` for SQLite. Pros: a restore of any
   backup converges to "deleted" at the next start; keeps disaster recovery; the ledger
   holds only opaque IDs. Cons: a second store to keep durable; touches the release
   scripts and the template (a human deploys); RDS backups still hold content for up to a
   day (documented as the recovery window). Code size: medium.
2. No backups that can hold deleted content: set RDS `BackupRetentionPeriod: 0` and
   `DeletionPolicy: Delete`, drop the pre-deploy SQLite copies (or delete them as soon as
   the post-deploy check passes), and enable `secure_delete`. Pros: simplest to reason
   about, because no copy outlives a deletion; no new code path. Cons: no point-in-time
   recovery and no rollback copy, so a bad release or corrupted database loses all data;
   RDS doesn't allow read replicas without backups. Code size: small (config and script
   edits only).
3. Per-workbook encryption keys ("crypto-shredding"): encrypt each workbook's bytes and
   metadata with its own key stored in a separate key table or KMS. Deletion destroys the
   key, so backups keep only unreadable ciphertext. Pros: backups stay useful for every
   other workbook; deletion reaches every copy at once. Cons: the key store itself must be
   outside the backups, or a restore brings keys back too; large change to storage and
   every read path; JSON payloads (findings, filenames) need encrypting as well.
   Code size: large.

Why 1 is recommended: it is the only option that both keeps recovery possible and makes
"a restore never resurrects a deletion" true by construction, at moderate cost.

Chosen:

## D7: How does deletion guarantee no future scheduled audit or reminder runs?  (blocks: DEL-7)
Status: OPEN
Context: Spec §10 says no future audit or reminder may run for a deleted workbook
(P5-DELETE-CANCEL-FUTURE), and a delete racing a scheduler claim must have one winner.
`haruki/phase5-schedule` stores schedules in `p5_schedules` (keyed by `workbook_id`,
`phase5_schedule.py`), but scheduled-audit dispatch and reminders aren't written anywhere
yet, and none of it is on `Jon-Gus_branch`. D4 covers removing the schedule and
notification rows; this entry covers the dispatcher side.

1. Row removal plus claim re-check (Recommended): deletion removes the `p5_schedules` row
   in the same transaction (D4 option 1). The future dispatcher and reminder code must
   claim work inside a write transaction that first calls `fence(db, workbook_id)` (added
   in DEL-2) and re-reads the schedule row, skipping it if it's gone. Write this as a
   requirement for Haruki's dispatcher, and add P5-DELETE-CANCEL-FUTURE as a test when the
   two branches meet. Pros: no state beyond what already exists; the same lock already
   serializes delete against uploads and audits. Cons: correctness depends on the
   dispatcher following the rule; nothing to test on this branch until the merge.
   Code size: small (later, on merge).
2. Content-free cancellation record: deletion writes an opaque `(workbook_id, cancelled_at)`
   row to a cancellation table that the dispatcher and reminder code must check before
   running anything, kept until the next restart or sweep. Pros: an explicit,
   inspectable cancellation that also survives a race in which a dispatcher read the
   schedule just before the delete. Cons: a second source of truth next to row
   removal; the extra table only helps if the dispatcher ignores the fence; overlaps
   with D5 and D6 (reservation, ledger), which could carry the same ID. Code size: small
   to medium.
3. Merge first, then implement: a person merges `haruki/phase5-schedule` (and later the
   dispatcher) into `Jon-Gus_branch`; then deletion and cancellation are implemented and
   tested against the real scheduler under this task list. Pros: a real end-to-end test
   of P5-DELETE-CANCEL-FUTURE. Cons: pulls scheduling into this list's scope (marked out
   of scope) and waits on work not started yet. Code size: small (after the merge).

Why 1 is recommended: the transaction plus `fence` design from DEL-1/DEL-2 already gives
"one consistent winner". The dispatcher only has to use it, which is a one-paragraph
requirement rather than new machinery.

Chosen:

## D8: Disabled buttons are 2.56:1. Change their look, or rely on the WCAG exemption?  (blocks: UI-5)
Status: OPEN
Context: UI-5 requires 4.5:1 for normal text "in every state the page uses".
`button:disabled{opacity:.5}` in `static/index.html` renders white on effectively
`#8ba5bb` = 2.56:1 (`#new-version` before the first upload; `#submit-decisions` when no
finding is editable). WCAG 2.1 SC 1.4.3 exempts "text ... that [is] part of an inactive user
interface component", so this passes WCAG but fails the task's wording. Every other pair
passes (list under UI-5). Any fix changes how the page looks, so the item requires a
decision.

1. Keep it and document the exemption: no change; record in the evidence doc (UI-9) that
   disabled controls rely on SC 1.4.3's inactive-component exception. Pros: no visual
   change; conformant with WCAG 2.1 AA as written. Cons: low-vision users may not be able
   to read what a disabled button would do; doesn't meet the task's "every state".
   Code size: none.
2. Explicit disabled colors that pass (Recommended): replace `opacity:.5` with, for example,
   `button:disabled{background:#d5dde5;color:#172637;cursor:not-allowed}` (11.18:1), so
   disabled buttons become light grey with dark text, clearly different from the dark blue
   enabled ones. Pros: readable in every state; still visibly "off"; one CSS line, testable
   by the contrast check. Cons: changes the look of two buttons; the light-grey button is
   only 1.37:1 against the white page, so its shape is less distinct (allowed for inactive
   components). Code size: small.
3. Don't disable at all: keep the buttons enabled, mark them `aria-disabled="true"`, and
   when activated show a text explanation in the alert region ("Upload a workbook first").
   Pros: always readable and discoverable by keyboard and screen readers, with an
   explanation instead of silence. Cons: a behavior change (clicking does something new);
   more script; still needs a style to signal the state. Code size: small to medium.

Why 2 is recommended: it satisfies the task's stricter "every state" reading with a
one-line CSS change and no behavior change.

Chosen:

## D9: What does the delete control look like, and how is it shown only to owners?  (blocks: UI-7)
Status: OPEN
Context: Spec §16: owners can "delete a workbook after an explicit confirmation identifying
it", completed by keyboard, with the result announced. DEL-1 provides
`DELETE /api/v1/workbooks/{id}` (204; 403 for reviewers; 409 `ACTIVE_OPERATION` while work
is running). `static/index.html` has no delete control. The page can't directly tell an
owner from a reviewer (there is no identity endpoint). The only hint is the review
response, where reviewers get `allowedActions: []` on every item (`phase4_service.py`
`review`). Both the confirmation style and the owner check change what users see, so
rule 6 applies.

All options share: the control lives in `#workspace` next to the other workbook actions;
it is shown only when the latest review gave the caller any `allowedActions` (owners) and
is hidden otherwise, with the server's 403 as the real guard; the result ("Workbook ...
deleted." or the API error, for example 409 `ACTIVE_OPERATION`) goes to the
`#status`/`#error` live regions from UI-4; after a 204, the workspace is hidden and the
state cleared.

1. Inline confirmation step (Recommended): a "Delete workbook..." button reveals a small
   `<fieldset>` reading "Permanently delete workbook <fileName> (<workbookId>), including
   all versions, reports and corrected copies? This cannot be undone." with "Delete
   permanently" and "Cancel" buttons. Focus moves to "Cancel", and Cancel returns focus
   to the trigger. Pros: fully in-page, so it's announced by screen readers and styled like
   the rest; names the workbook explicitly; native buttons satisfy UI-6. Cons: about 15
   lines of script plus markup; the one place where focus is moved programmatically
   (UI-6's test currently forbids `focus()`, so that check would be relaxed for this flow).
   Code size: small to medium.
2. Native `window.confirm()` with the workbook named in the message: one confirm call
   before the DELETE. Pros: smallest change (about 5 lines); the browser dialog is
   keyboard-operable and announced by screen readers; no focus management needed.
   Cons: unstyled, and its wording and button labels ("OK"/"Cancel") can't be changed;
   browsers can suppress repeated dialogs; some testers treat native dialogs as weaker
   evidence for AC-17. Code size: small.
3. Typed confirmation: the user must type the workbook's file name into a labelled input
   before "Delete permanently" is enabled. Pros: strongest protection against an
   accidental deletion; no dialog. Cons: more effort, especially with assistive technology;
   relies on a disabled button (see D8 contrast); file names can be long or contain
   characters that are hard to type. Code size: medium.

Why 1 is recommended: it meets §16's "explicit confirmation identifying it" in a way that
is fully keyboard- and screen-reader-friendly and stays consistent with the page, at a
modest size.

Chosen:

## D10: Which automated accessibility scanner, and who runs it?  (blocks: UI-8)
Status: OPEN
Context: Spec §16 requires "an automated accessibility scan and manual keyboard
inspection"; P5-MANUAL-A11Y-SCAN wants scan results as evidence. The interface is a
single page whose important states are built by script: the initial form, the
processing status, findings with decision controls, a failed audit (error alert), the
corrected-copy download, history, and later the delete confirmation (UI-7). The
standard-library tests (UI-2 to UI-6) can't see script-built DOM. Every real scanner is
a new tool or dependency (Node or a browser), which rule 9 doesn't let the agent add.

1. axe-core CLI, run by a person against a local server (Recommended): with Node and Chrome
   on the reviewer's machine, run `npx @axe-core/cli <url>` (WCAG 2.1 A/AA tags) for each
   state, driving the page by hand between scans, and paste the violation counts into the
   UI-9 evidence tables. Nothing is added to the repo. Pros: the most widely used rules
   engine; scans the live DOM, including script-built controls; no repo dependency.
   Cons: manual and not repeatable in CI; needs Node on the scanning machine.
   Code size: none (doc steps only).
2. Browser-built-in or extension tools (Chrome Lighthouse accessibility audit, or the axe
   DevTools / WAVE extension), run by a person on each state with a screenshot as
   evidence. Pros: zero setup beyond a browser; easy screenshots for the evidence file.
   Cons: least repeatable; Lighthouse runs only a subset of axe rules; results depend on
   the person's clicks. Code size: none.
3. Automated browser scan in the test suite: add Playwright plus axe-core (Python
   `playwright` + `axe-playwright-python`, or Node `pa11y-ci`) as dev dependencies, and a
   test that starts the app, walks the states (upload a fixture, wait for findings,
   submit a decision, and so on) and fails on any WCAG A/AA violation. Pros: repeatable on
   every change; covers script-built states automatically; strongest evidence. Cons: new
   dev dependencies and about 150 MB of browsers; slower tests; CI setup; the team must
   approve the dependencies (rule 9). Code size: medium.

Why 1 is recommended: it gives real, full-DOM scan evidence for AC-17 now, without adding
dependencies. Option 3 is the better long-term choice if the team accepts the tooling.

Chosen:
