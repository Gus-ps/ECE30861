"""The Phase 4 profile carries the bounds and catalogs of specification 2.1.0."""

import json
from pathlib import Path

import pytest

from tester.config import FIXTURES
from tester.models import PodProfile
from tester.suite.plan import load_plan

PHASE4 = FIXTURES / "pod_profile_phase4.json"
TEST_PLAN = Path(__file__).resolve().parent.parent / "ref" / "Phase4_Agent_Context_Pack" / "phase4-test-plan.json"


def phase4():
    return PodProfile.model_validate(json.loads(PHASE4.read_text(encoding="utf-8")))


def test_catalogs_match_the_phase4_test_plan():
    plan = json.loads(TEST_PLAN.read_text(encoding="utf-8"))
    coverage = phase4().coverage
    assert coverage.components == list(plan["components"])
    assert coverage.acceptance == list(plan["acceptance"])
    assert "C9" in coverage.component_basis and "not counted" in coverage.component_basis


def test_bounds_follow_section_10():
    profile = phase4()
    timing = profile.timing
    assert (timing.system_setup_seconds, timing.tester_setup_seconds) == (30, 45)
    assert (timing.upload_seconds, timing.get_seconds, timing.download_seconds) == (35, 10, 30)
    assert (timing.audit_poll_seconds, timing.remediation_poll_seconds) == (80, 210)
    assert (timing.poll_interval_seconds, timing.suite_seconds) == (1, 1800)
    assert 1 + timing.get_retries == 3, "at most three GET attempts in total"
    assert (profile.response_limits.json_bytes, profile.response_limits.binary_bytes) == (67_108_864, 33_554_432)


def test_phase3_profile_has_no_phase4_timings():
    timing = PodProfile.model_validate(json.loads((FIXTURES / "pod_profile.json").read_text(encoding="utf-8"))).timing
    assert timing.remediation_poll_seconds is None and timing.download_seconds is None


def test_phase4_profile_refuses_the_phase3_manifest():
    with pytest.raises(ValueError, match="components do not match"):
        load_plan(FIXTURES / "manifest.json", PHASE4)
