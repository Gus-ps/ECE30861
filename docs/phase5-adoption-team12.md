# Phase 5 adoption record: Team 12 column (draft)

Draft of Team 12's column in `ref/Phase5_Agent_Context_Pack/ADOPTION.md` (specification 3.0.0,
pack 3.0.0, ruleset 2.0.0, suite target 3.0.0). The pack copy stays byte-for-byte, because
`ADOPTION.md` is covered by the pack's `SHA256SUMS.txt`, so the values are kept here until both
teams fill in the shared record together.

Nothing here is an agreement, a fixture approval or a passing result against a real system.
"Pending" means unknown or not yet done. No credentials are recorded here.

Hashes are SHA256 of the committed (LF) bytes, as of 2026-11-17. A Windows checkout with
`core.autocrlf` holds the JSON files with CRLF, so their on-disk hashes differ there. Workbooks are
binary (`.gitattributes`) and hash the same everywhere. Regenerating the manifest or fixtures
changes these values, so recompute them at release.

| Field | Team 12 |
| --- | --- |
| Specification adoption reviewer and date | Pending: a Team 12 reviewer and date |
| Agreement channel or evidence | Pending |
| Adopted pack SHA256 | Pending: agree with Team 9 what is hashed. Team 12 holds pack 3.0.0 byte-for-byte in `ref/Phase5_Agent_Context_Pack/`, with `SHA256SUMS.txt` SHA256 `d38adb9fc05f149f0e8d4c0f9d350a928178d3702725ee129b63922a50bea30d`. The pack's own `validate_pack.py` fails only its last check on Windows (a path-separator bug in the script; to report to Team 9). |
| System base URL | `https://13.184.14.226.sslip.io/`. Pending: confirm the exact registered string (trailing slash), since the tester matches exact strings |
| Tester base URL | Pending |
| Target release SHA or tag | Pending (Team 12 system, deployment branch `origin/Gustavo`) |
| Tester release SHA or tag | Pending (branch `Logan-tester-phase5`, not yet committed) |
| Runnable manifest version and hash | `3.0.0-team12-draft`, `tester/fixtures/manifest_phase5.json` SHA256 `384f0c2a188457416d494aa66c3e573c9b9b5685fd7fdb033e9b87b0d9615074`. Generated from the plan by `scripts/build_phase5_manifest.py`: 357 hosted cases, all with checks |
| Fixture and expectations hashes | `tester/fixtures/expectations_phase5.json` `9a50b328a46ece5d50f335898da0848c8158348ff5f8d0e528be1827fcf0bb08` (Phase 4 pack 2.1.1 entries unchanged, plus `performance_250000_cells.xlsx` `cc5113ac0e868e12c11565b97603f93607cf16b5b472a26bec5bc902b2d73ea1`). Phase 4 pack `tester/fixtures/phase4/expectations.json` `2d51a46b93cbc05bc27aed8d04383b35042f1eb10a16167ec2c64a38e1a00cab` |
| Private access provisioning location | Pending. The tester needs per target userA, userB, reviewer and test-admin. Team 9 (2026-11-17): proceed with those four; the 5 access cases needing `reviewer-ungranted` or `test-admin-2` skip, naming the missing identity |
| Team design version and mapping URL/hash | Draft 1.0.0, `tester/fixtures/design_map_team12.json` SHA256 `73e88b6220e1d8533bd20f0c0b7cdf008b015979e9ad2234c00c4dddb9767c26`, mappingUrl `https://github.com/Gus-ps/ECE30861/blob/Logan-tester-phase5/tester/fixtures/design_map_team12.json`. Pending: Team 12 review, and a final URL on a stable branch or tag |
| Own-team trusted target identity configuration reviewed | Pending. Configured by `TESTER_TEAM_ID=team12` and `TARGET_TEAMS_JSON` (exact base URLs, `deploy/tester.env.example`) |
| Actual setup/run limits registered | Pending registration. Values: tester setup 45 s, run up to 2,430 s (2,400 s suite plus 30 s guard), system setup 30 s; deploy proxies allow 2,460 s. Team 9 sets its tester proxy timeout and renewable deployment protection lease to 2,700 s each, and its deployer defers while a run is protected |
| Own-system report with model coverage | Pending: no real run yet. Rehearsal against the stand-in only: 349 pass, 8 skip, model 38/38, stored bytes equal the run response |
| Reciprocal report without model coverage | Pending: Team 9 reports its Phase 5 system routes, clock and all seven fault controls deployed (system `https://3.139.178.70.sslip.io/system`, tester `https://3.139.178.70.sslip.io/tester`, both without a trailing slash). Run window, and both release SHAs or tags, to be agreed |
| Human fixture review records | Pending: Phase 4 pack review bundle sent to Team 9. `performance_250000_cells`: one Team 9 reviewer verified the bundle and workbook hashes, counted exactly 250,000 nonempty cells in the formal table and agreed with HTTP 202, AUDIT_COMPLETE, no findings and no limitations (2026-11-17, by email). The two-reviewer form is still pending |
| Excel and real-world precision evidence | Pending. Phase 4 fixture opens are recorded in the pack, and `performance_250000_cells` opened without a repair prompt on 2026-11-17 (its `excel_open`; reviewer, Excel version and platform still to fill in). Correction outputs have not been opened |
| Accessibility and five-run performance evidence | Pending. P5-PERFORMANCE-RUN-1 to -5 and -COMPARE are built and record upload and end-to-end times; queue and engine times need the system's own evidence |
| Deletion and backup/restore evidence | Pending (system) |
| Queue scheduling and notification monitoring evidence | Pending (system) |

## Deviations and shared decisions (owner: Team 12 tester)

Team 9 answered each of these by email on 2026-11-17. Items 1 to 8 are agreed with Team 9 and only
need recording in the shared ADOPTION.md; item 9 is still open.

1. **P5-CLOCK-NOT-READY** skips. No hosted request can hold a namespace not ready, because a
   refused setup leaves no session at all. Agreed: local evidence.
2. **P5-DELETE-RETAIN-TESTER** is built as Team 9 runs it. It hashes every earlier finalized report
   in the tester's own store, deletes a target workbook and hashes them again. It skips only when the
   store has no earlier finalized report, for example on a fresh deployment's first run.
3. **P5-FAULT-REJECT-DISABLED** skips on a deployment with faults enabled, which every other fault
   case requires. Agreed: local evidence (P4-LOCAL-FAULT-DISABLED).
4. **Busy cases** (P5-SCHEDULE-BUSY-AUDIT, -BUSY-REMEDIATION, P5-DELETE-ACTIVE-AUDIT,
   -ACTIVE-REMEDIATION) skip when the work cannot be shown to be active. A DELETE that returns 204
   on its own is inconclusive, so it skips too. When the busy path is exercised, they expect 409
   ACTIVE_OPERATION and check that the state is preserved. Team 9's tester does the same.
5. **Tester self-checks** (6 hosted P5-TESTER cases) are built as Team 9 builds them. Each judges
   a provisional report from the same report builder. CODE-COPY reads the system's session report
   during the run. STORED-BYTES checks a serialization round trip in the suite, and an acceptance
   check outside the suite compares the run response with the report stored afterwards.
6. **Access cases check the status and the ProjectError code**, matching Team 9: 401 UNAUTHORIZED,
   403 FORBIDDEN and 404 NOT_FOUND (§12).
7. **The "outstanding rename mismatch"** is P4-APPLY-RENAME and the `rename_references` fixture.
   Agreed: proceed with the cross-team runs, and investigate and fix it if it appears.
8. **Extra sessions:** a Phase 5 run creates many namespaces (79 against the stand-in). Team 9
   accepts cleanup batches of up to 100 IDs, provided the creating test-admin submits them (the
   tester always does).
9. **Missing identities:** the 5 access cases needing `reviewer-ungranted` or `test-admin-2` skip,
   naming the missing identity, at Team 9's request. Team 12 still needs to decide whether its own
   system provides these two identities.
