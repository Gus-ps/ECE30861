# ECE30861
Repository for EC30861 class

## Team 12 tester

Cross-team tester for the Excel accessibility hub. It exposes the instructor
testing interface (`POST /test/setup`, `POST /test/run`, `GET /test/report`)
and runs Team 9's 53-case Phase 3 manifest against an approved target system.

| Path | Purpose |
| --- | --- |
| `tester/main.py` | App factory and routes |
| `tester/service.py` | Setup / run / report lifecycle |
| `tester/store.py` | SQLite sessions, frozen plans, progress, immutable reports |
| `tester/target.py` | Bounded HTTP client for the target system |
| `tester/suite/` | Plan loading, ordered runner, check functions |
| `tester/fixtures/manifest.json` | Copy of Team 9 suite manifest 1.4.0 |
| `tester/fixtures/pod_profile.json` | Pod-pending defaults (Team 9 values, not pod-approved) |
| `tester/wcag/` | WCAG 2.1 workbook checker, kept for Phase 4 remediation checks |
| `ref/` | Instructor spec and Team 9 contract documents |

Setup (Python 3.12 via [uv](https://docs.astral.sh/uv/)):

```sh
uv sync --group dev
cp .env.example .env      # then fill in real values
uv run uvicorn tester.main:create_app --factory --port 8001
uv run pytest
```

Only the session-interface checks (`P3-SESSION-DUPLICATE`, `P3-CODE-REPORT`)
are implemented so far; every other case reports `skip` with
"not implemented in this tester build" until its check is added.
