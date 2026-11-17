# Phase 5 accessibility evidence (AC-17)

Assertions: `P5-MANUAL-KEYBOARD`, `P5-MANUAL-A11Y-SCAN`. Fill this in by hand. Automated
checks don't replace it (spec §16).

| Field | Value |
| --- | --- |
| Tester | |
| Date (UTC) | |
| Commit SHA tested | |
| Browser and version | |
| OS | |
| Screen reader (if used) | |
| Base URL | |

## Setup

1. Start the service locally with an owner token and a reviewer token (README / AGENTS.md
   "Gustavo" section), or use the test deployment.
2. Have `sample_files/valid.xlsx` and a workbook with findings ready, for example the
   one built by `test_remediation.build`.
3. Put the mouse away. Use only Tab, Shift+Tab, Enter, Space, the arrow keys and
   Escape. Record every step, including failures.

## Keyboard walkthrough

For each step, record Pass/Fail, where focus was visible, and what was announced (if a
screen reader was used).

| # | Step | Expected | Pass/Fail | Notes |
| --- | --- | --- | --- | --- |
| 1 | Load the page; press Tab repeatedly from the top | Focus moves token → file → "Upload as new workbook" → (disabled "Upload as new version" skipped) → "Response JSON"; outline always visible | | |
| 2 | Type the owner token | Characters masked; label "Access token" announced | | |
| 3 | On the file input press Enter/Space, choose the workbook | Native file dialog opens and returns focus to the input | | |
| 4 | Activate "Upload as new workbook" with Enter | "Validating and uploading..." then "Audit is processing..." announced politely | | |
| 5 | Wait for the audit | Status text announces the result; workspace appears after the upload controls | | |
| 6 | Tab through the findings | Each finding's "Action" select and value inputs are reachable and labelled; reason text readable | | |
| 7 | Pick a decision with the arrow keys; edit a value | Select and inputs work without a mouse | | |
| 8 | Activate "Submit selected decisions" | "Generating and verifying a separate copy..." announced; then the corrected-copy message | | |
| 9 | Activate "Download corrected workbook" | File downloads; focus stays on the button | | |
| 10 | Activate "Download unchanged source" and "Download audit report" | Both download | | |
| 11 | Activate "Run a new audit", then "Refresh results" | Status updates announced | | |
| 12 | Tab to the history table; activate a "View" button | That version's results load; note where focus lands afterwards (UI-6 review note) | | |
| 13 | Trigger an error: clear the token and activate "Refresh results" | Error text appears in the alert region and is announced immediately | | |
| 14 | Upload a non-.xlsx file | Clear text error; no stale progress text left beside it | | |
| 15 | Reload, enter the reviewer token, open the same workbook | "Read-only review access." shown; no decision controls | | |
| 16 | Open and close "Response JSON" with Enter | Expands and collapses; no trap | | |
| 17 | Delete flow (pending UI-7 / D9) | Delete control reachable, confirmation names the workbook, result announced, workspace cleared | | Not available until D9 is chosen |
| 18 | Whole walkthrough | Never stuck (no trap); tab order follows the visual order | | |

## Automated scan (pending D10)

Scanner, version and command: ______________________

| Page state | Violations (critical / serious / moderate / minor) | Rule IDs | Fixed? |
| --- | --- | --- | --- |
| Initial page | | | |
| Audit processing | | | |
| Findings with decision controls (owner) | | | |
| Findings as reviewer (read-only) | | | |
| Failed audit / error alert shown | | | |
| Corrected copy ready | | | |
| History table | | | |
| Delete confirmation (after UI-7) | | | |

## Contrast check

Computed values from UI-5 (PHASE5_TASKS.md). Confirm them with a contrast tool on the
rendered page.

| Text / background | Computed | Measured | Pass (4.5:1) |
| --- | --- | --- | --- |
| Body `#172637` on white | 15.34:1 | | |
| Body `#172637` on `#f1f5f8` | 13.99:1 | | |
| Button `#ffffff` on `#174b77` | 9.09:1 | | |
| Error `#9b1717` on white | 8.30:1 | | |
| Disabled button (opacity .5) | 2.56:1 | | Open: D8 |
| Native inputs and file button (browser defaults) | n/a | | |

## Result

- Keyboard walkthrough complete without a mouse: yes / no
- Open problems found (with step numbers):
- Signed off by:
