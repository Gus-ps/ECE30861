"""Builds Team 12's draft executable Phase 4 manifest (tester/fixtures/manifest_phase4.json)
from the shared test plan (ref/Phase4_Agent_Context_Pack/phase4-test-plan.json).

Team 9's executable manifest 2.1.0 does not exist yet. This draft keeps every hosted_http
case ID, its plan order, components, acceptance criteria and operations, and maps each to a
Team 12 check with explicit parameters and real resource prerequisites. Phase 3-numbered
cases keep their manifest 1.4.0 check, parameters and prerequisites, with fixtures resolved
in the Phase 4 pack (the plan's adaptation note: six-rule expectations). When Team 9's
manifest arrives, reconcile check names against MAPPING instead of editing the output.

    uv run python scripts/build_phase4_manifest.py          # write the manifest
    uv run python scripts/build_phase4_manifest.py --check  # verify the committed file
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "ref" / "Phase4_Agent_Context_Pack" / "phase4-test-plan.json"
PHASE3 = ROOT / "tester" / "fixtures" / "manifest.json"
OUT = ROOT / "tester" / "fixtures" / "manifest_phase4.json"
VERSION = "2.1.1-team12-draft"            # pack revision 2.1.1's suite target (CORRECTIONS.md)
##  Fixtures still waiting on an outside contract map to blocked_fixture (skips). None since
##  2026-11-01: Team 9's pod contract 1.1 fixtures are in the pack (origin team9).
BLOCKED = set()
POD_CONTRACT = "its expected findings follow pod contract 1.1, which is not in the Team 12 repo"
ACCESS_FIXTURE = "mixed_decisions"


def p4(test_id, fixtures):
    ##  (check, parameters, prerequisites) for a P4-* case.
    simple = {
        "P4-FAULT-SETUP": ("fault_setup", {}, []),
        "P4-FAULT-RECOVERY": ("fault_recovery", {}, ["P3-AUDIT-FAILURE-ENVELOPE"]),
        "P4-FAULT-AUTH": ("fault_auth", {}, []),
        "P4-FAULT-INVALID": ("fault_invalid", {}, []),
        "P4-UPLOAD-ALL-SIX": ("edge_upload", {"fixture": "seeded_all_six"}, []),
        "P4-AUDIT-ALL-SIX": ("edge_audit", {"fixture": "seeded_all_six"}, ["P4-UPLOAD-ALL-SIX"]),
        "P4-CLEAN-ALL-SIX": ("upload_and_audit", {"fixture": "clean_all_six"}, []),
        "P4-MANUAL-ONLY-STATUS": ("upload_and_audit", {"fixture": "review_only", "no_apply": True}, []),
        "P4-RULE-HEADER-DISABLED": ("rule_vector", {"fixture": "header_disabled_table", "rule": "TABLE_HEADER"}, []),
        "P4-RULE-HEADER-DENSE-RANGE": ("rule_vector", {"fixture": "header_range", "rule": "TABLE_HEADER"}, []),
        "P4-REVIEW-CONTEXT": ("review_context", {"fixture": "mixed_decisions"}, []),
        "P4-REVIEW-REVIEWER": ("review_reviewer", {"fixture": "mixed_decisions"}, []),
        "P4-VERSION-NEW": ("version_new", {"fixture": "clean_all_six", "new_bytes": "seeded_all_six"}, []),
        "P4-VERSION-SAME-BYTES": ("version_same_bytes", {"fixture": "clean_all_six"}, []),
        "P4-REAUDIT": ("reaudit", {"fixture": "seeded_all_six"}, []),
        "P4-REAUDIT-INVALID": ("reaudit_invalid", {"fixture": "clean_all_six"}, []),
        "P4-REAUDIT-DETERMINISM": ("reaudit_determinism", {"fixture": "seeded_all_six", "runs": 5}, []),
        "P4-SOURCE-BEFORE": ("source_before", {"fixture": "preservation_rich"}, []),
        "P4-DECISIONS-MIXED": ("remediation", {"fixture": "mixed_decisions", "set": "mixed"}, ["P4-AUDIT-ALL-SIX"]),
        "P4-APPLY-ALT": ("remediation", {"fixture": "alt_supported", "set": "corrections"}, []),
        "P4-APPLY-RENAME": ("remediation", {"fixture": "rename_references", "set": "corrections"}, []),
        "P4-APPLY-LINK": ("remediation", {"fixture": "link_supported", "set": "corrections"}, []),
        "P4-APPLY-HEADER-RANGE": ("remediation", {"fixture": "header_range", "set": "corrections"}, []),
        "P4-APPLY-HEADER-TABLE": ("remediation", {"fixture": "header_disabled_table", "set": "corrections"}, []),
        "P4-APPLY-COMBINED": ("remediation", {"fixture": "mixed_decisions", "set": "combined"}, []),
        "P4-APPLY-STRING-LABEL": ("remediation", {"fixture": "link_supported", "set": "corrections",
                                                  "targets": ["xl/worksheets/sheet1.xml#cell=A3"]}, []),
        "P4-APPLY-NO-EDITS": ("remediation", {"fixture": "review_only", "set": "no_edits"}, []),
        "P4-BATCH-ATOMIC-REJECTION": ("batch_atomic", {"fixture": "mixed_decisions"}, []),
        "P4-IDEMPOTENCY-REPLAY": ("idempotency", {"fixture": "mixed_decisions", "mode": "REPLAY"}, []),
        "P4-IDEMPOTENCY-CONFLICT": ("idempotency", {"fixture": "mixed_decisions", "mode": "CONFLICT"}, []),
        "P4-IDEMPOTENCY-INVALID-FIRST": ("idempotency", {"fixture": "mixed_decisions", "mode": "INVALID-FIRST"}, []),
        "P4-DOWNLOAD-LARGE": ("download_large", {"fixture": "large_preservation", "set": "large"}, []),
        "P4-SESSION-COVERAGE": ("session_coverage", {}, []),
        "P4-SESSION-CLEANUP": ("session_cleanup", {"fixture": "clean_all_six"}, []),
        "P4-REPORT-FORMAT": ("report_format", {}, []),
    }
    followups = {"P4-OUTPUT-HASH": ("preservation_rich", "preserve", "output_hash"),
                 "P4-SOURCE-AFTER": ("preservation_rich", "preserve", "source_after"),
                 "P4-PRESERVATION": ("preservation_rich", "preserve", "preservation"),
                 "P4-OUTPUT-AUDIT": ("mixed_decisions", "mixed", "output_audit"),
                 "P4-REPORT-COMPLETE": ("mixed_decisions", "mixed", "report_complete"),
                 "P4-REPORT-STABLE": ("mixed_decisions", "mixed", "report_stable"),
                 "P4-HISTORY": ("mixed_decisions", "mixed", "history"),
                 "P4-REMEDIATED-STATUS": ("mixed_decisions", "mixed", "remediated_status")}
    if test_id in simple:
        return simple[test_id]
    if test_id in followups:
        fixture, decision_set, aspect = followups[test_id]
        return "remediation_followup", {"fixture": fixture, "set": decision_set, "aspect": aspect}, []
    if test_id.startswith("P4-RULE-"):
        return "rule_vector", {"fixture": fixtures[0], "vector": test_id}, []
    if test_id.startswith("P4-REJECT-"):
        condition = test_id.removeprefix("P4-REJECT-")
        fixture = "unsupported_edits" if condition == "MANUAL-APPLY" else "mixed_decisions"
        return "reject_decisions", {"fixture": fixture, "condition": condition}, []
    if test_id.startswith("P4-ACCESS-"):
        rest = test_id.removeprefix("P4-ACCESS-")
        for operation in ("NEW-VERSION", "REAUDIT", "DECISIONS", "REMEDIATION", "OUTPUT", "HISTORY", "SOURCE",
                          "REPORT", "REVIEW"):
            if rest.startswith(operation + "-"):
                return "access", {"fixture": ACCESS_FIXTURE, "operation": operation,
                                  "condition": rest.removeprefix(operation + "-")}, []
    raise KeyError(f"no check mapping for {test_id}")


def p3(test_id, plan_case, phase3):
    ##  Phase 3-numbered cases: manifest 1.4.0's check, or the plan's new edge fixtures.
    fixture = (plan_case.get("inputs") or {}).get("fixture")
    if test_id == "P3-AUDIT-FAILURE-ENVELOPE":
        return "fault_failure_envelope", {"fixture": "clean_all_six"}, ["P4-FAULT-SETUP"]
    if test_id == "P3-INPUT-SHEETS-CHARTSHEET":
        return "upload_worksheets_chartsheet", {}, []
    if fixture in BLOCKED:
        return "blocked_fixture", {"blocked": fixture, "reason": POD_CONTRACT}, []
    if test_id in phase3:
        case = phase3[test_id]
        return case["check"], case.get("parameters", {}), case.get("prerequisites", [])
    if test_id.startswith("P3-UPLOAD-"):
        return "edge_upload", {"fixture": fixture}, []
    if test_id.startswith("P3-AUDIT-"):
        return "edge_audit", {"fixture": fixture}, [test_id.replace("P3-AUDIT-", "P3-UPLOAD-")]
    raise KeyError(f"no check mapping for {test_id}")


def build():
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    phase3 = {c["test_id"]: c for c in json.loads(PHASE3.read_text(encoding="utf-8"))["tests"]}
    tests = []
    for case in plan["tests"]:
        if case["tier"] != "hosted_http":
            continue
        test_id = case["test_id"]
        check, parameters, prerequisites = (p4(test_id, case["fixtures"]) if test_id.startswith("P4-")
                                            else p3(test_id, case, phase3))
        tests.append({"test_id": test_id, "check": check, "description": case["qualifying_assertion"],
                      "components": case["components"], "acceptance": case["acceptance"],
                      "operations": case["operations"], "prerequisites": prerequisites, "parameters": parameters})
    return {"manifest_version": VERSION, "ruleset_version": plan["ruleset_version"],
            "specification_version": plan["specification_version"],
            "note": "Team 12 draft generated from the shared Phase 4 test plan; replace with Team 9's executable "
                    "manifest 2.1.0 once it exists. Local and manual cases are evidence tasks outside this manifest.",
            "components": plan["components"], "acceptance": plan["acceptance"], "tests": tests}


def main(argv):
    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        print("Committed manifest matches the plan." if current == text else "Committed manifest is stale.")
        return 0 if current == text else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(build()['tests'])} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
