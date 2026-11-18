"""Builds Team 12's draft executable Phase 5 manifest (tester/fixtures/manifest_phase5.json)
from the shared Phase 5 test plan (ref/Phase5_Agent_Context_Pack/phase5-test-plan.json).

Keeps every hosted_http case ID (357: 215 inherited from Phase 4, 142 new), its plan order,
components, acceptance criteria, operations and prerequisites. Inherited cases keep the check
mapping of scripts/build_phase4_manifest.py, imported rather than copied. New cases map to their
check once built; until then to phase5_pending, which skips naming its family (spec 3.0.0 §18:
an unbuilt check or fixture is an explicit skip and an outstanding task).

    uv run python scripts/build_phase5_manifest.py          # write the manifest
    uv run python scripts/build_phase5_manifest.py --check  # verify the committed file
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_phase4_manifest as phase4  # noqa: E402

PLAN = ROOT / "ref" / "Phase5_Agent_Context_Pack" / "phase5-test-plan.json"
OUT = ROOT / "tester" / "fixtures" / "manifest_phase5.json"
VERSION = "3.0.0-team12-draft"
##  Short names for the Phase 5 criteria (spec 3.0.0 §17); AC-01 to AC-11 keep the Phase 4 names.
NEW_CRITERIA = {"AC-12": "Periodic audits", "AC-13": "Deadline reminders", "AC-14": "Controlled failures",
                "AC-15": "Authorization across new operations", "AC-16": "Transport, credentials and deletion",
                "AC-17": "Accessible user interface", "AC-18": "Performance and repeatability"}


def family(test_id):
    ##  P5-SCHEDULE-MIN -> SCHEDULE; P5-ACCESS-DELETE-OWNER -> ACCESS
    return re.match(r"P5-([A-Z]+)", test_id).group(1)


BUILT = {"CLOCK": "phase5_clock", "SCHEDULE": "phase5_schedule", "REMINDER": "phase5_reminder",
         "DELETE": "phase5_delete", "FAULT": "phase5_fault", "ACCESS": "phase5_access",
         "PERFORMANCE": "phase5_performance"}


def p5(case):
    ##  (check, parameters, prerequisites) for a new Phase 5 case: a built family's check, with the
    ##  case named by the rest of its ID (P5-SCHEDULE-REJECT-ZERO -> REJECT-ZERO) plus the plan's
    ##  own inputs (e.g. an access case's expected_status), else pending.
    group = family(case["test_id"])
    if group in BUILT:
        return (BUILT[group], {"case": case["test_id"].removeprefix(f"P5-{group}-"), **case["inputs"]},
                case["prerequisites"])
    return "phase5_pending", {"family": group}, case["prerequisites"]


def acceptance(plan, baseline):
    names = {}
    for key, value in plan["acceptance"].items():
        name = baseline["acceptance"].get(key) or NEW_CRITERIA[key]
        requirements = value.get("requirements", []) if isinstance(value, dict) else []
        names[key] = f"{name} ({', '.join(requirements)})" if requirements else name
    return names


def build():
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    baseline = json.loads(phase4.PLAN.read_text(encoding="utf-8"))
    inherited = {case["test_id"] for case in baseline["tests"]}
    phase3 = {c["test_id"]: c for c in json.loads(phase4.PHASE3.read_text(encoding="utf-8"))["tests"]}
    tests = []
    for case in plan["tests"]:
        if case["tier"] != "hosted_http":
            continue
        test_id = case["test_id"]
        if test_id in inherited:
            check, parameters, prerequisites = (phase4.p4(test_id, case["fixtures"]) if test_id.startswith("P4-")
                                                else phase4.p3(test_id, case, phase3))
        else:
            check, parameters, prerequisites = p5(case)
        tests.append({"test_id": test_id, "check": check, "description": case["qualifying_assertion"],
                      "components": case["components"], "acceptance": case["acceptance"],
                      "operations": case["operations"], "prerequisites": prerequisites, "parameters": parameters})
    return {"manifest_version": VERSION, "ruleset_version": plan["ruleset_version"],
            "specification_version": plan["specification_version"],
            "note": "Team 12 draft generated from the shared Phase 5 test plan (pack 3.0.0). Inherited cases keep "
                    "the Phase 4 draft's checks; new cases map to phase5_pending until built. Local and manual "
                    "cases are evidence tasks outside this manifest.",
            "components": plan["components"], "acceptance": acceptance(plan, baseline), "tests": tests}


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
