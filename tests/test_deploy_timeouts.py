"""The deploy files must outlast the tester's own run ceiling for every shipped profile.

A run answers after at most the profile's suite budget plus the 30 s guard in
TesterService.run; a proxy or client that gives up sooner cuts off the report.
"""

import json
import re
from pathlib import Path

import pytest

from tester.config import FIXTURES

ROOT = Path(__file__).resolve().parent.parent
RUN_GUARD = 30          # TesterService.run waits suite_seconds + 30


def ceiling():
    budgets = [json.loads((FIXTURES / name).read_text(encoding="utf-8"))["timing"]["suite_seconds"]
               for name in ("pod_profile.json", "pod_profile_phase4.json")]
    return max(budgets) + RUN_GUARD


def test_the_run_guard_is_what_the_service_uses():
    service = (ROOT / "tester" / "service.py").read_text(encoding="utf-8")
    assert f"timing.suite_seconds + {RUN_GUARD})" in service


@pytest.mark.parametrize("path, pattern", [
    ("deploy/nginx/team12-tester.conf", r"proxy_read_timeout (\d+)s"),
    ("deploy/nginx/team12-tester.conf", r"proxy_send_timeout (\d+)s"),
    ("deploy/caddy/Caddyfile", r"read_timeout (\d+)s"),
    ("deploy/caddy/Caddyfile", r"write_timeout (\d+)s"),
    ("scripts/smoke_test.py", r'"--run-timeout", type=float, default=(\d+)'),
])
def test_deploy_timeouts_exceed_the_run_ceiling(path, pattern):
    found = [int(value) for value in re.findall(pattern, (ROOT / path).read_text(encoding="utf-8"))]
    assert found and min(found) > ceiling() == 1830, (path, found)
