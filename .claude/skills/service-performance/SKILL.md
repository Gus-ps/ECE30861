---
name: service-performance
description: Measure a web service's performance and judge whether it is acceptable against stated budgets. Load before any PHASE5_TASKS.md PERF item, before timing the workbook service or its checker, and before writing performance evidence or a verdict (AC-18, spec §12/§17).
---

# Measuring and judging service performance

The job is evidence a team can decide on, not a faster service. Measure what exists,
report it honestly, and leave fixes to a team decision.

## 1. Know the budget before measuring

Write down the bound each number will be judged against, with its source. For this
service (Phase 5 spec 3.0.0 §12 and §17; AE-022 in Haruki's
`.docs/assumptions_and_extensions.md`):

| What | Budget |
| --- | --- |
| Audit engine run (one workbook) | 60 s, or a controlled failure |
| Accepted-job queue wait | 15 s real time |
| Audit polling deadline from acceptance | 80 s real time |
| Validation / remediation worker | 30 s / 180 s |
| JSON response / binary transport | 64 MiB / 32 MiB |
| Upload limits (the boundary) | 25,000,000 bytes, 50 worksheets, 250,000 nonempty cells |
| Worker memory (deployment value, not spec) | 384 MiB `RLIMIT_AS` in `service_worker.py` |
| Whole Phase 5 tester suite | 2,400 s |

AC-18: five documented runs of boundary work, each within 60 s or a controlled failure,
identical findings across successful runs, and queue time reported separately from
execution time.

## 2. Measure correctly

- **Clock:** use `time.monotonic()` (or `perf_counter`) for durations. Never subtract
  wall-clock or API timestamps that may use the simulated test clock
  (`phase5_clock.effective_now`).
- **Separate the stages:** queue wait (accepted to a worker starting), execution (the
  worker's run), and client overhead (upload, polling interval, download). If the
  service doesn't expose a stage, derive it and label it **approximate**, with the
  formula. Don't add timing fields to the API to get it; that's a contract change.
- **Isolate runs:** one workbook at a time, nothing else running (no test suite, no
  profiler), a fresh database, and a fresh worker process per run. A profiler
  (`cProfile`) changes timings, so profile in separate runs from the timed ones.
- **Repeat:** at least 5 timed runs per input. Do one untimed warm-up first and say
  so. Report every run, plus min, median and max. With 5 runs a "p95" is just the max,
  so call it the max.
- **Correctness alongside speed:** fingerprint each successful run's findings
  (SHA-256 of the sorted rule ID, worksheet, target, category and finding ID) and
  compare them across runs. A fast run with different findings is a failure.
- **Size and memory:** record each response's byte size (findings JSON, report) and
  the worker's peak memory where the OS allows it. Compare sizes with the 64 MiB limit.
- **Failures are data:** record the outcome of every run: success, `PROCESSING_FAILED`
  with its error code, timeout, or an uncontrolled crash (a 500 with no record, a hung
  job, a partial output). Never drop a failed run or rerun until it passes.

## 3. Record the environment

Every result table states: commit SHA, OS, Python version, CPU model and core count,
RAM, database (SQLite or PostgreSQL), how the workbook was generated (script, profile
and SHA-256), and anything that differs from production. On this Windows machine,
`RLIMIT_AS` isn't applied (the `resource` module is POSIX only), so memory-limit
failures can't reproduce there. Local timings don't predict the production instance
type, so mark them **local, indicative only**.

## 4. Judge the result

For each budget, classify the **slowest** successful run (not the mean):

| Verdict | Rule |
| --- | --- |
| Pass with headroom | max ≤ 75% of budget (≤ 45 s for the 60 s engine bound) |
| Marginal | 75% < max ≤ 100% of budget. Passes today, but environment noise or a slower host can break it. Flag it for the team |
| Fail | any run over budget, an uncontrolled failure, or findings that differ between successful runs |
| Controlled failure | a deliberate, recorded `PROCESSING_FAILED` within the bound, with no output. AC-18 accepts this, but a boundary workbook that *always* fails means users at the limit get no audit. Report it as a product concern, not a pass |

Also judge consistency: a spread (max − min) above 20% of the median means the
environment is noisy and the runs should be repeated before drawing conclusions.

## 5. Report, don't fix

- Write results to the evidence document named by the task, with one table per
  workbook profile, the environment block and a verdict per budget.
- Compare with earlier measurements (e.g. AE-022's checker-only numbers) and explain
  differences you can attribute; mark the rest unexplained.
- Put every possible fix (changing the checker, worker memory, limits, instance type,
  response size) under "For team discussion" with its trade-off. Don't change the
  checker, worker limits, timeouts or upload limits in a measurement task. Those are
  pod or team decisions.
- Keep raw outputs (per-run JSON) under the gitignored `.perf/` and commit only the
  scripts and the summary document.
