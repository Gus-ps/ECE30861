# Phase 5 performance evidence (AC-18)

Local measurement of the integrated service on `Jon-Gus_branch` (PERF-2), for team
discussion. **Local, indicative only:** this is not hosted AC-18 acceptance and doesn't
predict the production instance. Nothing in the service, checker, worker limits or API
was changed to get these numbers. Raw per-run JSON is in `.perf/` (gitignored).

## Environment

| Item | This run | Production (for comparison) |
| --- | --- | --- |
| Commit | `0b0426b` plus the `upload_seconds` field added to `scripts/perf_service.py` in the commit that adds this document | release SHA from `ADOPTION.md` (unfilled) |
| Checker | this branch's copy, **without** the `f94330f` optimizations | same, until integrated |
| OS | Windows 11 Home 10.0.26200 (native, not WSL) | Linux, `python:3.13-slim` image |
| Python | 3.14.7 | 3.13 |
| CPU / RAM | Intel Core Ultra 9 185H, 22 logical CPUs / 31.6 GB | ECS task `Cpu: 1024`, `Memory: 2048` (`infrastructure/aws.yaml`); EC2 demo type not recorded here |
| Database | SQLite 3.50.4, a fresh file per profile | PostgreSQL on RDS |
| Server | `python -m uvicorn app:app`, one process, local loopback | ECS Express / Caddy on EC2 |
| Worker memory | **no limit**: the 384 MiB `RLIMIT_AS` in `service_worker.py` is POSIX only and isn't applied on Windows | 384 MiB `RLIMIT_AS` |
| Workbooks | Haruki's `scripts/perf_workbooks.py` (`origin/haruki/accessibility-checker`), run from an uncommitted copy in `.perf/`, default 250,000 cells | the tester's `performance_250000_cells` fixture |

Generated workbooks (all exactly 250,000 nonempty cells, within every upload limit):

| Profile | File | Bytes | Sheets | SHA-256 |
| --- | --- | --- | --- | --- |
| a | `perf_a_numeric_single_sheet_250000.xlsx` | 1,134,038 | 1 | `dc31f085ce7bc3c9f895b65b630d3bedb1b0f28040538ddc888cf9f83326c589` |
| b | `perf_b_numeric_50_sheets_250000.xlsx` | 1,126,263 | 50 | `0f00fc4f859ac1dd25ed074dac72f687429127ac3f3d929e015601cfad4247f2` |
| c | `perf_c_mixed_realistic_10_sheets_250000.xlsx` | 1,685,339 | 10 | `b334fadd48129ff0659e305a2199e6058f3f59f0bb691853cd039ed7e1b127d1` |
| d | `perf_d_styled_table_single_sheet_250000.xlsx` | 1,628,816 | 1 | `b4749646506c67ef5a1f3e658f00b5c295d6425ce8d808ab3c83f4e9136e05ad` |

## Method

`python scripts/perf_service.py --base-url http://127.0.0.1:8124 --token <local> <workbook>`,
one profile at a time, each against a freshly started server with a new database and
nothing else running on the machine (2026-11-19, 18:32:26 to 19:02:29 UTC, 30 min 3 s).
Per profile: one untimed warm-up run (discarded, not recorded), then 5 timed runs.

- **Upload:** duration of the `POST /api/v1/workbooks` request (transfer, validation,
  storage), until the 202.
- **End-to-end:** monotonic time from the 202 to the first poll that isn't `PROCESSING`
  (polled every 0.25 s), including the transfer of that final audit response.
- **Execution:** a separate, fresh `service_worker.py audit <file>` process on the same
  host, timed by the script (60 s cap, like the service).
- **Queue (approximate):** end-to-end minus execution. It also absorbs polling delay,
  result storage and the final response transfer, and the two worker runs differ
  slightly, so it can be negative for small results.
- **Fingerprint:** SHA-256 of the sorted (rule ID, worksheet, target, category, finding ID)
  of every finding. Sizes are the bytes of the audit GET (Operation 5, which carries the
  findings) and of the report GET.

## Results (every timed run)

#### perf_a_numeric_single_sheet_250000.xlsx

| Run | Outcome | Upload s | End-to-end s | Execution s | Queue s (approx) | Findings | Fingerprint | Audit bytes | Report bytes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | SUCCESS | 0.98 | 25.87 | 25.87 | -0.01 | 1 | `2e2fccddb500` | 941 | 2,164 |
| 2 | SUCCESS | 1.04 | 26.33 | 25.79 | 0.53 | 1 | `2e2fccddb500` | 941 | 2,164 |
| 3 | SUCCESS | 0.95 | 26.00 | 25.90 | 0.10 | 1 | `2e2fccddb500` | 941 | 2,164 |
| 4 | SUCCESS | 0.97 | 26.14 | 25.58 | 0.56 | 1 | `2e2fccddb500` | 941 | 2,164 |
| 5 | SUCCESS | 1.01 | 25.49 | 25.80 | -0.31 | 1 | `2e2fccddb500` | 941 | 2,164 |

#### perf_b_numeric_50_sheets_250000.xlsx

| Run | Outcome | Upload s | End-to-end s | Execution s | Queue s (approx) | Findings | Fingerprint | Audit bytes | Report bytes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | SUCCESS | 0.95 | 26.34 | 26.24 | 0.10 | 50 | `55d45f63025d` | 27,379 | 68,169 |
| 2 | SUCCESS | 0.96 | 26.00 | 25.74 | 0.26 | 50 | `55d45f63025d` | 27,379 | 68,169 |
| 3 | SUCCESS | 0.94 | 26.20 | 25.59 | 0.61 | 50 | `55d45f63025d` | 27,379 | 68,169 |
| 4 | SUCCESS | 0.95 | 25.41 | 25.72 | -0.31 | 50 | `55d45f63025d` | 27,379 | 68,169 |
| 5 | SUCCESS | 0.93 | 25.87 | 26.53 | -0.66 | 50 | `55d45f63025d` | 27,379 | 68,169 |

#### perf_c_mixed_realistic_10_sheets_250000.xlsx

| Run | Outcome | Upload s | End-to-end s | Execution s | Queue s (approx) | Findings | Fingerprint | Audit bytes | Report bytes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | PROCESSING_FAILED / `PROCESSING_TIMEOUT` | 1.04 | 60.21 | - | - | - | - | 504 | 836 |
| 2 | PROCESSING_FAILED / `PROCESSING_TIMEOUT` | 1.04 | 60.35 | - | - | - | - | 504 | 836 |
| 3 | PROCESSING_FAILED / `PROCESSING_TIMEOUT` | 1.09 | 60.19 | - | - | - | - | 504 | 836 |
| 4 | PROCESSING_FAILED / `PROCESSING_TIMEOUT` | 1.01 | 60.13 | - | - | - | - | 504 | 836 |
| 5 | PROCESSING_FAILED / `PROCESSING_TIMEOUT` | 1.03 | 60.11 | - | - | - | - | 504 | 836 |

#### perf_d_styled_table_single_sheet_250000.xlsx

| Run | Outcome | Upload s | End-to-end s | Execution s | Queue s (approx) | Findings | Fingerprint | Audit bytes | Report bytes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | SUCCESS | 1.07 | 36.50 | 27.65 | 8.85 | 250,000 | `6cfbbb3ec695` | 151,028,224 | - |
| 2 | SUCCESS | 1.03 | 35.63 | 27.95 | 7.68 | 250,000 | `6cfbbb3ec695` | 151,028,224 | - |
| 3 | SUCCESS | 1.08 | 36.14 | 27.97 | 8.17 | 250,000 | `6cfbbb3ec695` | 151,028,224 | - |
| 4 | SUCCESS | 1.10 | 36.04 | 28.10 | 7.95 | 250,000 | `6cfbbb3ec695` | 151,028,224 | - |
| 5 | SUCCESS | 1.06 | 35.84 | 27.62 | 8.22 | 250,000 | `6cfbbb3ec695` | 151,028,224 | - |

Report bytes `-` for profile d: the report GET returned **500** on every run (6 of 6,
including the warm-up). The script didn't record the error code; the server logged no
traceback, and the only 500 that route raises after a completed audit is the size guard
`RESULT_TOO_LARGE` (`phase4_service.py` line 442, limit 64 MiB). Profile c's report GETs
returned 200 (836 bytes, the failed audit's report).

## Verdicts per AC-18 criterion

Rules from `.claude/skills/service-performance` section 4 (pass with headroom at most 75%
of the budget, marginal at most 100%, otherwise fail).

| Criterion (spec §12/§17) | a | b | c | d |
| --- | --- | --- | --- | --- |
| Engine run ≤ 60 s or controlled failure | Pass with headroom (max 25.90 s) | Pass with headroom (max 26.53 s) | **Controlled failure 5/5**: `PROCESSING_FAILED` / `PROCESSING_TIMEOUT` at the 60 s worker kill | Pass with headroom (max 28.10 s), **only because no memory limit applies here** |
| Controlled failure (no partial output reported as success) | n/a | n/a | Yes: failed status with error code, no findings, a report of the failure | Audit succeeded; report refused by the size guard (controlled), but the audit GET itself returned 151,028,224 bytes (see sizes) |
| Identical findings across successful runs | Yes, 1 fingerprint, 1 finding | Yes, 1 fingerprint, 50 findings | No successful run to compare | Yes, 1 fingerprint, 250,000 findings |
| Queue reported separately | Yes, approximate (−0.31 to 0.56 s) | Yes, approximate (−0.66 to 0.61 s) | Not measurable (the execution side runs timed out too) | Yes, approximate (7.68 to 8.85 s, mostly result storage and the 151 MB response, not waiting) |
| Polling deadline 80 s from acceptance | Pass with headroom (max 26.33 s) | Pass with headroom (max 26.34 s) | Pass (max 60.35 s, ends in the controlled failure) | Pass with headroom (max 36.50 s) |

Overall, locally: a and b meet AC-18 with headroom. c always fails in a controlled way,
so a user at the boundary with an ordinary mixed workbook gets no audit (a product
concern, not a pass). d completes here, but would hit the 384 MiB limit in production
(AE-022), and its audit response breaks the 64 MiB limit.

The spread rule flagged a and b's queue column as noisy: it is sub-second and dominated
by the 0.25 s polling interval, so it says nothing about queueing. Execution and
end-to-end spreads were all under 4% of the median.

## Response sizes against the 64 MiB limit (67,108,864 bytes)

| Profile | Audit GET (Op 5) bytes | Report GET bytes | Within limit |
| --- | --- | --- | --- |
| a | 941 | 2,164 | Yes |
| b | 27,379 | 68,169 | Yes |
| c | 504 (failed audit) | 836 (failed audit) | Yes, only because the audit failed; AE-022 projects a successful c report at about 65.7 MiB |
| d | **151,028,224 (about 144 MiB)** | refused: 500 (`RESULT_TOO_LARGE`, inferred) | **No**: the audit GET has no size guard and returned 2.25 times the limit |

## Comparison with AE-022 (checker-only and worker-path results)

AE-022 ran on other hardware (i7-1360P, WSL2, Python 3.14.4) and measured the checker or
the worker alone, not the service. Its worker path "A" is the checker this branch has.

| Profile | AE-022 worker path A, 384 MiB / 60 s | This run (service, no memory limit) | Agreement |
| --- | --- | --- | --- |
| a | 5/5 ok, about 22.8–23.5 s | 5/5 ok, execution 25.58–25.90 s | Same outcome; about 10% slower here (different CPU and OS; not attributed further) |
| b | 5/5 ok (checker-only 22.5–24.8 s) | 5/5 ok, 25.59–26.53 s | Same outcome; slightly slower, same caveat |
| c | 5/5 timeout | 5/5 `PROCESSING_TIMEOUT` | Same. AE-022's optimized checker (`f94330f`, "B") finished c in about 29–30 s |
| d | 5/5 `MemoryError` in the worker's final `json.dumps` | 5/5 ok in 27.62–28.10 s | Differs because Windows applies no `RLIMIT_AS`; AE-022's unlimited run also completed (about 762 MiB RSS) |

AE-022 measured d's findings and limitations at 155,277,911 bytes; this run's whole audit
response is 151,028,224 bytes. The difference is probably serialization (the service's
encoder versus `json.dumps` defaults) but is unexplained. The generated files' hashes
weren't compared with AE-022, which doesn't list them.

## Not measured

- Linux, Python 3.13, PostgreSQL, the production instance type and the 384 MiB limit
  (PERF-3). Profile d's success here doesn't carry over to production.
- Worker peak memory (not available on Windows without a new tool).
- The tester's own `performance_250000_cells` fixture and the hosted `P5-PERFORMANCE-*`
  runs; these synthetic profiles aren't human-reviewed boundary fixtures.
- Exact queue time: the service doesn't record when a worker claims a job.

## For team discussion

Not decisions, and nothing here is implemented. Each item needs Haruki, the pod or Jon
to decide.

1. **Integrate the checker optimizations (`f94330f` and the stage 1 work).** Profile c
   fails on every run here and passed in about 30 s in AE-022 with them. Trade-off:
   integration work and re-verifying fingerprints on this branch; at about 30 s against
   60 s the margin on a slower host isn't large.
2. **Production instance type.** The ECS task has 1 vCPU and 2 GB. These numbers come
   from a fast laptop CPU; a and b at about 26 s could approach 60 s on a slower vCPU.
   A run on the real instance (PERF-3) decides this.
3. **Worker memory (384 MiB).** d needs about 762 MiB without a limit (AE-022) and fails
   in production with `MemoryError`. Raising the limit lets d finish but raises the risk
   to a shared host and doesn't fix response size; reducing output (aggregated
   COLOR_CONTRAST findings or limitations) fixes both but changes shared output and needs
   pod approval.
4. **The 64 MiB response limit for profiles c and d.** The report route enforces it
   (500 `RESULT_TOO_LARGE`) and so does history, but the audit GET (Operation 5) returned
   about 144 MiB for d with no guard. Options: guard Operation 5 the same way (a contract
   question: what the client gets instead), paginate findings, or remove the repeated
   arrays in the report (AE-022). All change shared behavior.
5. **Record a job claim time,** so queue time can be reported exactly instead of derived.
   AC-18 asks for queue time separately, and the current approximation also absorbs
   storage and transfer (about 8 s for d).
6. **Result storage and transfer cost.** d spends about 8 s after the worker finishes
   storing and serving about 150 MB. On PostgreSQL over a network this may grow, and it
   counts against the 80 s polling deadline.
