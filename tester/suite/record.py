"""Run record: evidence about a finished run, kept outside the instructor SuiteReport.

Stored with the report when the run ends and never returned by the testing
interface. Report retrieval times are kept separately as they happen; read the
whole record with scripts/run_record.py.
"""

import json
from collections import Counter

from .plan import manifest_of, profile_of

RECORD_VERSION = "1"
OUTCOMES = ("pass", "fail", "error", "skip")


def _design_record(run_profile, marked):
    run_profile = run_profile or {}
    if not run_profile.get("kind"):
        return {}
    entry = {"report_profile": {key: run_profile[key] for key in ("kind", "tester_team", "target_team")}}
    if run_profile["kind"] == "own":
        design, executed = run_profile["design"]["map"], set(marked or [])
        entry["design_map"] = {"team_id": design["teamId"], "design_version": design["designVersion"],
                               "mapping_url": design["mappingUrl"], "sha256": run_profile["design"]["sha256"]}
        entry["design_evidence"] = {r["requirementId"]: [t for t in r["testIds"] if t in executed]
                                    for r in design["requirements"]}
    return entry


def build_record(session_id, target_url, plan, report, progress, *, state, started_at, ended_at,
                 abort_reason=None):
    manifest = manifest_of(plan)
    profile = profile_of(plan)
    results = json.loads(report)["results"]
    outcome_of = {result["test_id"]: result["outcome"] for result in results}
    counts = Counter(outcome_of.values())

    ##  Operation -> outcome counts over the cases that exercise it, in manifest order.
    conformance = {}
    for case in manifest.tests:
        for operation in case.operations:
            tally = conformance.setdefault(str(operation), dict.fromkeys(OUTCOMES, 0))
            tally[outcome_of[case.test_id]] += 1

    evidence = (progress or {}).get("evidence") or {"components": {}, "acceptance": {}}
    fixtures = plan.get("fixtures")
    provenance = plan.get("provenance") or {}
    return {
        "record_version": RECORD_VERSION,
        "session_id": session_id,
        "target_url": target_url,
        "state": state,
        "abort_reason": abort_reason,
        "started_at": started_at,
        "ended_at": ended_at,
        "specification_version": manifest.specification_version,
        "manifest_version": manifest.manifest_version,
        "ruleset_version": manifest.ruleset_version,
        "profile_version": profile.profile_version,
        "pod_approved": profile.pod_approved,
        "fixture_pack": None if fixtures is None else {
            "expectations_sha256": fixtures["expectations_sha256"],
            "ruleset_version": fixtures["ruleset_version"],
            "fixtures": {key: entry["sha256"] for key, entry in fixtures["entries"].items()},
        },
        "tester_revision": provenance.get("tester_revision"),
        "target_revision": provenance.get("target_revision"),
        "counts": {**{outcome: counts.get(outcome, 0) for outcome in OUTCOMES}, "total": len(results)},
        "coverage": json.loads(report)["coverage"],
        "operation_conformance": conformance,
        "component_evidence": evidence["components"],
        "acceptance_evidence": evidence["acceptance"],
        ##  Phase 5 report profile and, for own-team runs, the frozen design map and which executed
        ##  tests earned each design requirement (spec 3.0.0 §14).
        **_design_record(plan.get("run_profile"), (progress or {}).get("marked")),
        ##  Separate system sessions created by the fault cases; queued for cleanup after this record.
        "fault_session_ids": list((progress or {}).get("fault_sessions", [])),
        ##  Every fail and error, for triage; owner and resolution are filled in by people.
        "unresolved_discrepancies": [
            {key: result[key] for key in ("test_id", "outcome", "source", "message") if key in result}
            for result in results if result["outcome"] in ("fail", "error")
        ],
    }
