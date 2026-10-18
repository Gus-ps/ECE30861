# Team 9 → Team 12: Shared HTTP Test Suite Guide

**Excel Accessibility Hub · Phase 3 · October 16, 2026**  
**Suite manifest:** 1.4.0 · **Ruleset:** 1.0.0 · **Team 9 contract profile:** 1.0.0  
**Prepared against repository revision:** `66d588c`

This guide explains the inputs Team 9's shared HTTP suite sends, the responses it expects, and how Team 12 can run it against an approved system. The suite contains **53 planned cases** and exercises the system through HTTP. Team 12 can use the hosted tester without installing Team 9's code.

**Readiness:** The tester is implemented. This checkout's real Team 9 system endpoints are still pending integration; public service URLs, credentials, and both directions of cross-team testing are pending. Team 12's shared workbooks have not been delivered. Current fixture expectations use clearly labeled synthetic stand-ins.

## 1. Contract references and authority

The [instructor Cross-team Testing Interface](https://docs.google.com/document/d/1GhEVTw3a2tNJY2arfDyWgWS94kVYfgC7/edit?rtpof=true), including its **OpenAPI 3.1.1 starter, version 0.4.2**, defines setup, run, report, outcomes, error sources, and coverage. Its text export was retrieved and checked for this guide on October 16, 2026. Relevant sections are “Required calls,” “Execution rules,” “Coverage fields,” and “Phase 3 cross-team check.”

The following repository documents supply the project-specific details:

| Reference | Use |
|---|---|
| [Phase 3 contract profile](../contracts/phase3.md) | Project API, workbook rules, serialization, session transport, timing, and items awaiting pod confirmation |
| [Tester implementation](../implementation/dixon_phase3.md) | Actual shared-suite behavior, commands, and limitations |
| [Fixture guide](../../tests/fixtures/README.md) | Workbook inventory and instructions for adopting Team 12 fixtures |
| [Suite manifest](../../tests/fixtures/manifest.json) | Authoritative ordered cases, prerequisites, assertions, and component/AC mappings |
| [Expected results](../../tests/fixtures/expectations.json) | Independent workbook hashes, statuses, findings, and rejection expectations |
| [Tester OpenAPI](../contracts/tester.openapi.json) | Expanded request/response schemas for the three delivered tester endpoints |
| [System schema catalog](../contracts/system.openapi.json) | Project DTO schemas; paths are currently empty, so this is not a complete delivered system API description |

**Authority distinction:** The instructor defines the common testing interface. The workbook API, audit policy, `X-Test-Session`, exact field constraints, defensive limits, timing, and coverage catalogs below describe **Team 9's current implementation profile**. Details identified as pending must be confirmed with Team 12 before treating them as a shared pod contract. If a discrepancy is found, record it and coordinate a contract-version change.

## 2. What each team provides before a cross-team run

Team 12 supplies its actual system base URL, system deployment tag/SHA if known, and four test identities through a private channel: **userA**, **userB**, **reviewer**, and **test-admin**. User A owns uploaded resources; user B must be unable to read them. The reviewer must have an explicit grant to user A's resources and authorization for the test session. Reviewer role alone is insufficient.

Team 9 supplies its actual tester base URL and a tester operator bearer token privately. Team 9's tester operator configures the approved target URL and target credentials before setup. The grader/operator request body remains only `{"target_url":"..."}`; credentials and fixtures are server configuration.

Base URLs end before the endpoint path, for example `https://team12.example.edu/system` or `https://team9.example.edu/tester`. These are placeholders, not deployed services. Use public HTTPS with a valid certificate. Do not append `/test`, a query, fragment, or embedded credentials. The target URL must match the configured allowlist **exactly**, including any base path and trailing-slash choice. The tester preserves base path prefixes and does not follow redirects.

Team 12's system must expose the four project operations in section 4 plus system `POST /test/setup` and `GET /test/report`. No system `/test/run` is required. The real system and any audit worker must be running before a cross-team run.

## 3. Setup → run once → retrieve report

All testing endpoints use JSON and `Authorization: Bearer TOKEN`. GET requests have no body. The operator uses the **tester token**; the tester uses **target credentials** when contacting Team 12.

| Caller → service | Request | Expected response |
|---|---|---|
| Operator → tester | `POST /test/setup` with `{"target_url":"https://team12.example.edu/system"}` | `201 {"session_id":"<new-uuid>"}` after target preparation succeeds; no suite cases execute yet |
| Tester → system | `POST /test/setup` with `{"session_id":"<same-uuid>","setup":{}}` | `201 {"session_id":"<same-uuid>"}` when ready; retain the supplied ID |
| Operator → tester | `POST /test/run` with `{"session_id":"<uuid>"}` | `200` complete suite report, including failures/system errors; tester abort returns `500` with available results stored |
| Tester → system | `GET /test/report?session_id=<uuid>` | `200` session code-coverage response, shown below |
| Operator → tester | `GET /test/report?session_id=<uuid>` | `200` stored suite report; `409` before the suite ends |

Only one run is allowed per prepared tester session. Concurrent, repeated, and post-abort runs return `409`. Create a fresh session to repeat the suite. Invalid requests do not consume a session. Failed setup produces no runnable session; a valid system setup error is forwarded with its status, message, and source preserved. [Instructor: “Required calls” and “Execution rules.”]

Project calls carry `X-Test-Session: <uuid>` plus the appropriate user bearer token, except public health and deliberate negative-authentication cases. The header is also sent on health. Team 9 expects unknown sessions to return project `400`, unauthorized session access `403`, duplicate system setup `409`, and unknown report sessions `404`.

System setup starts an empty, isolated namespace. Resources, jobs, and measurements belong to that session; ordinary data and other sessions must remain intact. Retain state through the suite and coverage retrieval. Setup may additionally contain `{"cleanup_session_ids":["<earlier-owned-session>"]}` to clean earlier namespaces. Refuse cleanup of another owner's namespace or one with active jobs. Failed preparations are queued for cleanup through a later new setup; cleanup of successfully retrieved sessions is disabled by default. These transport/cleanup conventions require pod confirmation.

## 4. Project inputs and expected outputs

All paths below are relative to the **system** base URL. Business JSON uses **camelCase**; instructor testing JSON uses **snake_case**. Responses use `application/json`. Upload requests use `multipart/form-data` with the binary field named **file**.

| Operation | Input and success | Expected rejection/error cases |
|---|---|---|
| `GET /api/v1/health` | Public; `200` HealthResponse | `503` is the project unavailability contract; the shared suite does not force this fault |
| `POST /api/v1/workbooks` | User bearer token, session header, multipart `file`; valid `.xlsx` → `202` UploadResponse | `400` missing file; `401` absent/invalid token; `413` excess bytes; `415` unsupported extension/type; `422` invalid workbook; initialization/storage failure → `500` |
| `GET /api/v1/workbooks/{workbookId}/versions/{versionId}` | Owner or explicitly granted reviewer; `200` VersionResponse | `401` unauthenticated; `403` foreign owner; `404` unknown/mismatched resource IDs |
| `GET /api/v1/workbooks/{workbookId}/versions/{versionId}/audits/{auditId}` | Owner or explicitly granted reviewer; `200` AuditResponse, including while `PROCESSING` | `401`, `403`, or `404` as above; controlled processing failure is represented in the audit body |

**Input boundaries tested:** 25,000,000 bytes, 50 worksheets, and 250,000 nonempty cells are allowed. One over returns `413` for bytes or `422` for worksheets/cells. Large inputs are generated during the run. Count cells across hidden and visible sheets: formulas, numeric zero, boolean false, nonempty values, and nonempty inline strings count; formatting-only/empty-value cells do not.

CSV, `.xls`, and missing extensions return `415`. A named `.xlsm` returns `422` with code **MACRO_ENABLED_WORKBOOK_UNSUPPORTED**. Corrupt files, macro-bearing `.xlsx`, encrypted ZIP entries, workbook/worksheet protection, ZIP traversal/duplicate paths, and XML DTD/entity declarations return `422`. Except for the `.xlsm` code, the suite checks the rejection status and error envelope without requiring a particular code string. Rejections expose no accepted workbook/version/audit IDs and must create no accepted resources.

The profile also specifies defensive ceilings of 10,000 ZIP entries, 200 MiB expanded package bytes, and 50 MiB per expanded XML part. The current suite does not individually test every additional defensive ceiling. Team 12 should confirm those policies separately.

### Response examples and field requirements

Health:

```json
{"status":"AVAILABLE","apiVersion":"1.0","rulesetVersion":"1.0.0"}
```

Accepted upload: return three distinct, fresh identifiers and `PROCESSING`, even if the worker finishes before the first poll.

```json
{"workbookId":"wb-001","versionId":"ver-001","auditId":"audit-001","status":"PROCESSING"}
```

Version metadata for the current synthetic clean fixture:

```json
{
  "workbookId":"wb-001",
  "versionId":"ver-001",
  "fileName":"clean.xlsx",
  "sha256":"e1de45e415b8552304a69050a86c5d605ab07eeaf96cef0c92dde6ba2d63e35e",
  "createdAt":"2026-10-16T15:00:00Z",
  "status":"AUDIT_COMPLETE",
  "latestAuditId":"audit-001",
  "sourceVersionId":null
}
```

Completed clean audit:

```json
{
  "auditId":"audit-001",
  "workbookId":"wb-001",
  "versionId":"ver-001",
  "rulesetVersion":"1.0.0",
  "status":"AUDIT_COMPLETE",
  "startedAt":"2026-10-16T15:00:01Z",
  "completedAt":"2026-10-16T15:00:03Z",
  "findings":[],
  "limitations":[],
  "error":null
}
```

IDs/timestamps above are illustrative. Hashes are the actual current fixture hashes, not values to hard-code for arbitrary uploads.

| Formatting rule | Expected format |
|---|---|
| Resource/request/session identifiers | Strings of 1–64 characters matching `[A-Za-z0-9_-]+`; tester sessions are UUIDs |
| Hashes | Exactly 64 lowercase hexadecimal characters; version hash matches the raw uploaded bytes |
| Dates | UTC RFC3339 strings ending in `Z`; completion cannot precede start |
| Versions | `rulesetVersion` is semantic version `1.0.0`; `apiVersion` is string `"1.0"` |
| Required nullable fields | Include keys such as `sourceVersionId`, `latestAuditId`, `completedAt`, and `error` even when null |
| Collections | `findings` and `limitations` are arrays; use `[]` when empty |
| Text | Nonblank messages; `fileName` 1–255 characters; finding message/recommendation 1–500 characters |
| Object fields | Use the declared schema fields only; Team 9 models reject undeclared fields |

During `PROCESSING`, `completedAt`/`error` are null and findings are empty. Successful completion has a completion timestamp and null error. `AUDIT_COMPLETE` has no findings; `REVIEW_REQUIRED` has findings. `PROCESSING_FAILED` has a completion timestamp, a ProjectError, and no partial findings. Source bytes remain unchanged.

The schema recognizes future version states `REMEDIATION_AVAILABLE`, `REMEDIATING`, and `REMEDIATED`, and future audit state `REMEDIATION_AVAILABLE`; the Phase 3 shared suite does not treat these as completed remediation features.

### Two distinct error formats

Project API errors use all four fields:

```json
{"code":"UNSUPPORTED_FILE_TYPE","message":"Only .xlsx workbooks are supported.","requestId":"req-001","details":{}}
```

Instructor testing endpoint errors use:

```json
{"message":"The suite has not ended.","source":"tester"}
```

Testing endpoint statuses are `400` invalid request, `401` absent/invalid credentials, `403` forbidden, `404` unknown session, `409` conflict/not ready, and `500` service failure/abort. `source` is exactly `tester`, `system`, `communication`, or `unknown`. [Instructor: “Execution rules — Errors.”]

## 5. Expected findings and shared workbook files

**ALT_TEXT:** Inspect pictures, charts, shapes, grouped children, and hidden-sheet objects. A non-decorative object missing either the alt-text title or description gets one finding: `ruleId: ALT_TEXT`, `category: NON_TEXT_CONTENT`, `classification: REQUIRES_USER_INPUT`. Both missing still produces one finding. Visible chart titles and object names do not substitute for alt-text fields. An explicitly native decorative object produces one `MANUAL_REVIEW` finding instead. Unsupported/ambiguous representations require a review finding and explicit limitation.

**WORKSHEET_NAME:** After Unicode whitespace trimming, case-insensitive ASCII `Sheet` followed by digits with numeric value greater than zero gets one `WORKSHEET_NAME` rule/category finding, classified `REQUIRES_USER_INPUT`. Examples: `Sheet1`, `sheet2`, `Sheet01`, and ` Sheet3 ` trigger; `Sheet0`, `Sheet`, and `Expenses` do not. Preserve original sheet spelling in findings. Inspect hidden sheets too.

Both rules use Unicode White_Space: U+0009–000D, 0020, 0085, 00A0, 1680, 2000–200A, 2028, 2029, 202F, 205F, and 3000. U+200B zero-width space is not included. These are pod audit-policy details for confirmation.

Each finding includes `findingId`, `ruleId`, `category`, `worksheet`, `target`, `classification`, `message`, and `recommendation`. For example, one current synthetic seeded finding is:

```json
{
  "findingId":"6d492d85d162b8909a27865296eb8b64762a556b2455048b1cadf4b0d330c195",
  "ruleId":"ALT_TEXT",
  "category":"NON_TEXT_CONTENT",
  "worksheet":"Sheet1",
  "target":"xl/drawings/drawing1.xml#id=2",
  "classification":"REQUIRES_USER_INPUT",
  "message":"Picture 1 is missing its alternative text description.",
  "recommendation":"Provide an alternative text description."
}
```

Cross-team message wording may differ; the suite compares semantic fields and validates prose presence/length. Repeated audits of the same bytes on one target must preserve messages and recommendations as well as semantic fields. Prose meaning still needs human review.

**Stable identity:** `findingId` is lowercase SHA256 of compact UTF-8 JSON for `[sourceSha256,rulesetVersion,ruleId,worksheetName,target]`. Use `ensure_ascii=False`, separators `(",", ":")`, no Unicode normalization, BOM, or trailing newline. Sort findings by `(ruleId, worksheet, target)` using Unicode code-point order. Include no random IDs or timestamps in the digest. Object targets use the actual ZIP part plus `#id=<stored-id>`; worksheet targets use the actual part plus `#sheetId=<id>`. Missing/duplicate object IDs use the indexed `#xml=` path defined in the contract and require disclosure in limitations.

### Files requested from Team 12

| File | Required role |
|---|---|
| `clean.xlsx` | Valid workbook with descriptive sheet names and pictures/charts/shapes having nonblank alt-text title and description; no decorative review markers; expect `202`, then `AUDIT_COMPLETE` and no findings |
| `seeded_issues.xlsx` | Valid workbook deliberately containing generic sheets, missing/empty/whitespace alt fields, and a native decorative marker; expect `202`, then `REVIEW_REQUIRED` and independently documented exact findings |
| `corrupt.xlsx` | Deliberately unreadable workbook; expect `422` with ProjectError and no accepted IDs |

Supply raw-file SHA256, ruleset version, object/sheet targets, classifications, and expected status for each file. Two pod members should independently review expectations and valid workbooks should open in Excel without repair warnings; those reviews are currently pending. Do not obtain expected findings by running the implementation under test.

Retain `tests/fixtures/synthetic/`. Place Team 12 files under `tests/fixtures/shared/`, and use a reviewed expectations file whose canonical `clean`, `seeded_issues`, and `corrupt` entries point to `shared/...` with `origin: "team12"`. Keep the other edge fixtures. Point `FIXTURE_MANIFEST_PATH` at the corresponding manifest, whose `expectations` path is relative to that manifest. Create a new session after changing fixtures; setup snapshots the plan and checks raw-file hashes.

The current **synthetic** seeded workbook expects six findings: three missing-alt findings at drawing IDs 2, 3, and 6; one decorative manual-review finding at ID 4; and generic-name findings for `Sheet1` and hidden `sheet2`. Team 12's file must have its own oracle; it need not have the same bytes or six findings.

## 6. Run the shared suite

### A. Use the hosted tester directly

After Team 9 provisions the URL and operator token, any HTTP client can execute the following sequence. Replace example URLs with registered addresses and load the token privately into `TEAM9_TESTER_TOKEN`.

```sh
export TESTER_URL='https://team9.example.edu/tester'

# 1. Prepare the approved target. Save the returned session_id.
curl -sS --max-time 60 -X POST "$TESTER_URL/test/setup" \
  -H "Authorization: Bearer $TEAM9_TESTER_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"target_url":"https://team12.example.edu/system"}'

# 2. Replace this with the actual returned ID. Send run only once.
export SESSION_ID='replace-with-returned-session-id'
curl -sS --max-time 630 -X POST "$TESTER_URL/test/run" \
  -H "Authorization: Bearer $TEAM9_TESTER_TOKEN" \
  -H 'Content-Type: application/json' \
  --data "{\"session_id\":\"$SESSION_ID\"}" \
  -o report.json

# 3. Retrieve the stored report, including after a lost run response.
curl -sS --max-time 15 \
  "$TESTER_URL/test/report?session_id=$SESSION_ID" \
  -H "Authorization: Bearer $TEAM9_TESTER_TOKEN" \
  -o stored-report.json
```

Inspect the HTTP status and body in your client. A `200` from run means the tester finished; individual tests may still fail. If report returns `409`, poll again about once per second with a deadline. A lost run response is recovered through report GET; **do not resend run**. An uncertain upload/setup POST is not automatically retried either. [Instructor: “Timing” and “Tester reports.”]

### B. Use the repository CLI to save evidence

Use Python 3.12 and uv 0.13.1; the [repository setup instructions](../../README.md#local-setup) cover installing those tools on macOS/Linux and Windows. Run commands from the repository root:

```sh
uv sync --locked --group dev

# TEAM9_TESTER_TOKEN must already contain the privately supplied operator token.
uv run python -m scripts.run_suite \
  --tester-url https://team9.example.edu/tester \
  --target-url https://team12.example.edu/system \
  --target-revision unknown \
  --output report.json \
  --record run-record.json
```

On PowerShell, put the CLI command on one line; the token variable is `$env:TEAM9_TESTER_TOKEN`. Use an actual supplied deployment tag/SHA instead of `unknown` when available. Do not infer it from Team 9's tester checkout. Keep the local manifest aligned with the hosted tester; use `--manifest /path/to/matching/manifest.json` for a coordinated alternate plan.

The CLI performs setup, sends run once, and polls the stored report if the run response is lost. `report.json` preserves the report bytes. `run-record.json` adds counts, retrieval-time UTC timestamp, supplied revision, per-AC evidence, and the 14-operation status catalog. It leaves failure classification as `unclassified` for human review into system/test/specification problems. Retain actual run timing separately when needed. Exit `0` means no fail/error outcomes; `1` indicates fail/error or an operational problem; a missing operator token exits `2`. Expected observation skips alone do not fail the command.

### C. If Team 12 hosts its own copy of Team 9's tester

Use the same repository setup, configure a private `.env`, then start only the tester:

```sh
uv run uvicorn tester.main:create_app --factory --host 127.0.0.1 --port 8001
```

| Setting | Required value |
|---|---|
| `TESTER_OPERATOR_TOKEN_HASHES_JSON` | JSON map of lowercase SHA256(operator token) → operator subject |
| `ALLOWED_TARGET_URLS` | JSON list containing the exact approved system base URL |
| `TARGET_AUTH_MAP_JSON` | Map of that exact URL → object with private raw tokens keyed `userA`, `userB`, `reviewer`, `test-admin` |
| `FIXTURE_MANIFEST_PATH` | Optional alternate reviewed manifest; defaults to bundled/repository fixtures |
| `TESTER_DB_PATH` | Persistent tester SQLite path; one tester worker per store |
| `APP_ENV` | `production` for public deployment; HTTPS is required |

No credentials are enabled by default. The system must provision the matching identities, reviewer grant, and session access; when using Team 9's system implementation these are `SYSTEM_TOKEN_HASHES_JSON`, `REVIEWER_GRANTS_JSON`, `TEST_SESSION_USERS_JSON`, and `ENABLE_TEST_INTERFACE=true`. Measurement is optional and must be reported honestly. Team 12 may use a different internal configuration while matching HTTP behavior.

Local tester docs are at `http://127.0.0.1:8001/docs`. Use `--tester-url http://127.0.0.1:8001` in the CLI for this local tester. Running Team 9's foundation system on port 8000 does not yet provide an integrated target on this checkout.

## 7. Timing, reports, and coverage

| Activity | Current Team 9 limit |
|---|---|
| System setup | 30 seconds |
| Tester setup, including target preparation | 45 seconds |
| Upload call, including validation | 35 seconds |
| Ordinary GET | 10 seconds |
| Poll one accepted audit | 75 seconds, normally at 1-second intervals |
| Entire suite, including coverage retrieval | 600 seconds |
| Operator/proxy run read timeout | At least 630 seconds |

The profile additionally sets validation at 30 seconds, audit execution at 60 seconds, and queue wait at 15 seconds. Register agreed actual limits. Only safe GET transport failures receive up to three retries within the same deadline. The tester currently caps a target response at 2 MiB; this is a disclosed implementation limit awaiting pod confirmation.

A tester report has exactly `session_id`, `target_url`, `results`, and `coverage`. Each of the **53 planned test IDs appears exactly once**, in manifest order, with nonblank `test_id`, `outcome`, and `message`. A complete formatting specimen is the [retained synthetic-target report](../evidence/dixon_local_selfcheck/report.json); it is an example of report structure, not Team 12 results.

| Outcome | Interpretation |
|---|---|
| `pass` | Response matches expectations, including expected rejections such as corrupt-file `422` |
| `fail` | An evaluable response differs in status, schema, findings, or other expected behavior |
| `error` | Evaluation is prevented; include `source` as `tester`, `system`, `communication`, or `unknown` |
| `skip` | Case did not execute, such as a missing prerequisite or no controlled failure to inspect |

`source` is included only for error outcomes in Team 9's report profile. Unexpected target internal failures use `system`; a request timeout without a response uses `communication`. Tester abort preserves completed results, marks the interrupted case as tester error, and leaves unexecuted cases as skips. A final report is stored before response and remains unchanged on retrieval. Instructor retention is until the tester instance stops; Team 9 additionally persists reports in SQLite. [Instructor: “Execution rules.”]

System code-coverage response:

```json
{
  "session_id":"replace-with-session-id",
  "coverage":{"code":{
    "covered":null,
    "total":null,
    "basis":"Audit and validation source lines; instrumentation unavailable"
  }}
}
```

The suite report includes `coverage.code`, `coverage.component`, and `coverage.system`, each with `covered`, `total`, and nonblank `basis`. Available counts are nonnegative integers with covered ≤ total. Unavailable measurements use **both counts null**, with an explanation; do not substitute zero. Target code coverage comes only from the system's session report. State whether its scope is audit/validation-only or wider. Reading the system report does not execute work or reset measurements. [Instructor: “Coverage fields” and system report.]

Team 9 computes component coverage over **C1 authentication/access, C2 upload/validation, C3 source/version metadata, C4 rule engine, C5 jobs/audit API, and C6 session/coverage interface**. System coverage uses eight Phase 3 AC portions: **AC-01 intake, AC-02 rejection, AC-03 source preservation, AC-04 two-rule detection, AC-05 findings, AC-14 controlled failures, AC-15 access, and AC-18 determinism**. These denominators require pod confirmation. Executed qualifying assertions count even when they fail; skips earn no coverage. A coverage percentage does not establish acceptance success or full scope completion.

Existing documented local fake-target evidence is **52 passes, 0 fails, 0 errors, and 1 skip**, with components 6/6 and scoped ACs 7/8. `P3-AUDIT-FAILURE-ENVELOPE` normally skips on a healthy target. The fake's 40/50 code coverage is a test constant. These figures establish no real Team 9/Team 12 deployment result.

## 8. Cross-team handoff and troubleshooting

Before the first run, both teams should confirm the exact field names/nullability, enums, identity algorithm, object targets, audit policy, `.xlsm` behavior, cell counting, session transport/cleanup, coverage catalogs, response-size/timing limits, and private access provisioning described above. Supply and review shared fixtures separately. Registration needs actual distinguishable system/tester base URLs, the common pod specification link, and access/run notes.

| Symptom | Next action |
|---|---|
| Setup `400` | Check exact allowlist/access-map URL, base path, scheme, request fields, and trailing slash |
| `401` / `403` | Check tester token versus target token, session access, ownership, and explicit reviewer grant |
| Setup fails or echoes a different ID | Inspect its `{message, source}`; the target must prepare and echo the supplied ID |
| Run `409` | Session is already running/used; retrieve its report, or create a new session for another suite |
| Report `409` | Suite is not finished; poll GET within a deadline |
| Run timeout or tester `500` | Retrieve stored report using the same session ID; do not repeat run |
| Fixture hash or manifest mismatch | Obtain the agreed fixture/manifest version; keep original bytes and create a fresh setup |
| Many prerequisite skips | Inspect earlier upload/audit failures; later cases may have no usable resource |
| Correct findings but failed determinism | Check sorting, hash inputs, raw sheet spelling, and within-target prose stability |

Run **Team 9 tester → Team 12 system** and **Team 12 tester → Team 9 system** when both real targets are ready. Keep each direction's date/time, actual URLs, session ID, target revision, planned/executed/pass/fail/error/skip counts, report, coverage scope, and problems to fix. Red tests are valid Phase 3 evidence; the instructor requires a working common interface and well-formed reports, not a fabricated all-pass result. [Instructor: “Phase 3 cross-team check.”]

## Appendix: Current shared-suite case inventory

The following rows are copied from manifest 1.4.0 in execution order. Consult that manifest for exact prerequisites and assertion/AC mappings. This inventory covers only the shared HTTP suite.

| Test ID | Expected behavior |
|---|---|
| `P3-HEALTH` | Public health returns HealthResponse with the expected ruleset. |
| `P3-AUTH-UPLOAD` | Upload without a bearer token is rejected with no accepted IDs. |
| `P3-AUTH-UPLOAD-INVALID` | Upload with an unknown bearer token is rejected. |
| `P3-INPUT-MISSING-FILE` | Multipart upload without the file field returns 400. |
| `P3-INPUT-CSV` | CSV upload returns 415. |
| `P3-INPUT-MISSING-EXTENSION` | Missing filename extension returns 415. |
| `P3-INPUT-XLS` | Legacy .xls upload returns 415. |
| `P3-INPUT-XLSM` | Named .xlsm upload returns 422 MACRO_ENABLED_WORKBOOK_UNSUPPORTED. |
| `P3-INPUT-CORRUPT` | Corrupt workbook returns 422 with no accepted identifiers. |
| `P3-INPUT-PROTECTED` | Workbook with password-protected structure returns 422. |
| `P3-INPUT-BYTES-OVER` | An upload of 25,000,001 bytes returns 413. |
| `P3-INPUT-BYTES-AT` | A valid workbook of exactly 25,000,000 bytes is accepted. |
| `P3-INPUT-SHEETS-OVER` | A valid workbook with 51 worksheets returns 422. |
| `P3-INPUT-SHEETS-AT` | A valid workbook with exactly 50 worksheets is accepted. |
| `P3-INPUT-CELLS-OVER` | A valid workbook with 250,001 nonempty cells returns 422. |
| `P3-INPUT-CELLS-AT` | A valid workbook with exactly 250,000 nonempty cells is accepted. |
| `P3-UPLOAD-CLEAN` | Clean fixture is accepted with three PROCESSING identifiers. |
| `P3-UPLOAD-SEEDED` | Seeded fixture is accepted with three PROCESSING identifiers. |
| `P3-VERSION-VALID` | Version metadata matches the upload and the tester's own SHA256. |
| `P3-VERSION-UNAUTHENTICATED` | Version read without a bearer token returns 401. |
| `P3-AUDIT-CLEAN` | Clean fixture audit completes with no findings. |
| `P3-AUDIT-SEEDED` | Seeded audit returns exactly the expected findings in contract order. |
| `P3-SOURCE-HASH` | Source SHA256 is unchanged after auditing. |
| `P3-VERSION-FOREIGN` | User B cannot read user A's version. |
| `P3-AUDIT-UNAUTHENTICATED` | Audit read without a bearer token returns 401. |
| `P3-AUDIT-FOREIGN` | User B cannot read user A's audit. |
| `P3-VERSION-REVIEWER` | Explicitly granted reviewer reads user A's version. |
| `P3-AUDIT-REVIEWER` | Explicitly granted reviewer reads user A's audit. |
| `P3-NOT-FOUND` | version-unknown returns 404. |
| `P3-VERSION-MISMATCH` | version-mismatch returns 404. |
| `P3-AUDIT-MISMATCH` | audit-mismatch returns 404. |
| `P3-AUDIT-UNKNOWN` | audit-unknown returns 404. |
| `P3-DETERMINISM` | Audit 2 matches the first of five uploads. |
| `P3-DETERMINISM-3` | Audit 3 matches the first of five uploads. |
| `P3-DETERMINISM-4` | Audit 4 matches the first of five uploads. |
| `P3-DETERMINISM-5` | Audit 5 matches the first of five uploads. |
| `P3-SESSION-UNKNOWN` | A project call naming an unknown X-Test-Session returns 400. |
| `P3-SESSION-DUPLICATE` | Repeating system setup with an existing session_id returns 409. |
| `P3-UPLOAD-UNICODE` | unicode accepted. |
| `P3-AUDIT-UNICODE` | unicode exact findings and limitations. |
| `P3-UPLOAD-REPEATED-IDS` | repeated_ids accepted. |
| `P3-AUDIT-REPEATED-IDS` | repeated_ids exact findings and limitations. |
| `P3-UPLOAD-MULTIPLE-DRAWINGS` | multiple_drawings accepted. |
| `P3-AUDIT-MULTIPLE-DRAWINGS` | multiple_drawings exact findings and limitations. |
| `P3-INPUT-ZIP-TRAVERSAL` | zip_traversal rejects with no accepted IDs. |
| `P3-INPUT-ZIP-DUPLICATE` | zip_duplicate rejects with no accepted IDs. |
| `P3-INPUT-XML-DTD` | xml_dtd rejects with no accepted IDs. |
| `P3-INPUT-MACRO-PARTS` | macro_parts rejects with no accepted IDs. |
| `P3-INPUT-ENCRYPTED-ZIP` | encrypted_zip rejects with no accepted IDs. |
| `P3-INPUT-PROTECTED-SHEET` | protected_sheet separately rejected. |
| `P3-INPUT-PROTECTED-STRUCTURE` | protected_structure separately rejected. |
| `P3-AUDIT-FAILURE-ENVELOPE` | Validate any observed controlled target audit failure; skip if none occurred. |
| `P3-CODE-REPORT` | System report returns this session's code coverage (counts and basis, or paired nulls). |
