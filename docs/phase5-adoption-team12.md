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
| Runnable manifest version and hash | `3.0.0-team12-draft`, `tester/fixtures/manifest_phase5.json` SHA256 `cb7b9b0119ed143719cb81e72118f21542015d81d2aeef4f77f9e630a7c83859`. Generated from the plan by `scripts/build_phase5_manifest.py`: 357 hosted cases, 351 with checks and 6 tester self-checks pending |
| Fixture and expectations hashes | `tester/fixtures/expectations_phase5.json` `d4fe307f317f8b4eca6a84c245520c9e47ba62b7eae5d7293d02a612c851a819` (Phase 4 pack 2.1.1 entries unchanged, plus `performance_250000_cells.xlsx` `cc5113ac0e868e12c11565b97603f93607cf16b5b472a26bec5bc902b2d73ea1`). Phase 4 pack `tester/fixtures/phase4/expectations.json` `2d51a46b93cbc05bc27aed8d04383b35042f1eb10a16167ec2c64a38e1a00cab` |
| Private access provisioning location | Pending. The tester needs per target userA, userB, reviewer and test-admin, plus `reviewer-ungranted` and `test-admin-2` for 5 access cases |
| Team design version and mapping URL/hash | Draft 1.0.0, `tester/fixtures/design_map_team12.json` SHA256 `73e88b6220e1d8533bd20f0c0b7cdf008b015979e9ad2234c00c4dddb9767c26`, mappingUrl `https://github.com/Gus-ps/ECE30861/blob/Logan-tester-phase5/tester/fixtures/design_map_team12.json`. Pending: Team 12 review, and a final URL on a stable branch or tag |
| Own-team trusted target identity configuration reviewed | Pending. Configured by `TESTER_TEAM_ID=team12` and `TARGET_TEAMS_JSON` (exact base URLs, `deploy/tester.env.example`) |
| Actual setup/run limits registered | Pending registration. Values: tester setup 45 s, run up to 2,430 s (2,400 s suite plus 30 s guard), system setup 30 s; deploy proxies allow 2,460 s |
| Own-system report with model coverage | Pending: no real run yet. Rehearsal against the stand-in only: 344 pass, 13 skip, model 38/38 |
| Reciprocal report without model coverage | Pending: needs a Phase 5 Team 9 system |
| Human fixture review records | Pending: Phase 4 pack review bundle sent to Team 9; `performance_250000_cells` not yet reviewed |
| Excel and real-world precision evidence | Pending. Phase 4 fixture opens are recorded in the pack; correction outputs and the performance workbook have not been opened |
| Accessibility and five-run performance evidence | Pending. P5-PERFORMANCE-RUN-1 to -5 and -COMPARE are built and record upload and end-to-end times; queue and engine times need the system's own evidence |
| Deletion and backup/restore evidence | Pending (system) |
| Queue scheduling and notification monitoring evidence | Pending (system) |

## Deviations and open shared decisions (owner: Team 12 tester, to raise with Team 9)

1. **P5-CLOCK-NOT-READY** skips. No hosted request can hold a namespace not ready, because a
   refused setup leaves no session at all. Proposal: treat it as local-tier.
2. **P5-DELETE-RETAIN-TESTER** skips. Finalized tester reports live only in the tester's own
   store, so a hosted case has nothing on the target to observe. Question: how is it meant to run?
3. **P5-FAULT-REJECT-DISABLED** skips on a deployment with faults enabled, which every other fault
   case requires. It passes only against a deployment with the switch off (P4-LOCAL-FAULT-DISABLED).
4. **Busy cases** (P5-SCHEDULE-BUSY-AUDIT, -BUSY-REMEDIATION, P5-DELETE-ACTIVE-AUDIT,
   -ACTIVE-REMEDIATION) skip when the target finishes its work before the clock call or DELETE
   arrives. A DELETE that returns 204 cannot be told apart from a target that ignored active work,
   so it skips too, rather than passing or failing.
5. **Tester self-checks** (6 hosted P5-TESTER cases) are not built. Question: how should a hosted
   case judge the run's own report before that report exists?
6. **Access cases compare HTTP status only, not error codes.** The spec names 401 UNAUTHORIZED for
   the new routes, while earlier contracts used other codes.
7. **The "outstanding rename mismatch"** that ADOPTION.md mentions: ask Team 9 which mismatch this
   is.
8. **Extra sessions:** a Phase 5 run creates many namespaces (79 against the stand-in). They are
   cleaned through `cleanup_session_ids`, at most 100 per setup.
