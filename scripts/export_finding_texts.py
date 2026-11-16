"""Export ruleset 2.0.0 prose for AC-05 human review (partial WCAG coverage).

1.1.1 Non-text Content; 1.3.1 Info and Relationships; 1.4.1 Use of Color;
1.4.3 Contrast (Minimum); 2.4.2 Page Titled (related 2.4.6 Headings and Labels);
2.4.4 Link Purpose (In Context). This export does not perform human review.
"""

import argparse
import json
import re
from pathlib import Path

from accessibility_checker.runner import check_workbook

ROOT = Path(__file__).resolve().parents[1]


def fixture_paths():
    return sorted(
        {ROOT / "tests/fixtures/six_rule_seeded.xlsx",
         *ROOT.glob("tests/fixtures/deployment/*.xlsx")},
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )


def message_template(text):
    """Only numeric contrast values vary in active finding messages."""
    return re.sub(
        r"Static text contrast [0-9]+\.[0-9]{2}:1 is below [0-9]+\.[0-9]:1\.",
        "Static text contrast {ratio:.2f}:1 is below {threshold:.1f}:1.",
        text,
    )


def export(paths=None):
    groups = {}
    limitations = {}
    for path in fixture_paths() if paths is None else sorted(map(Path, paths)):
        findings = check_workbook(path)
        source = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name
        for finding in findings:
            key = (
                finding["ruleId"], finding["classification"],
                message_template(finding["message"]), finding["recommendation"],
            )
            record = groups.setdefault(
                key, {"ruleId": key[0], "classification": key[1],
                      "messageTemplate": key[2], "recommendation": key[3],
                      "examples": set(), "fixtures": set()},
            )
            record["examples"].add(finding["message"])
            record["fixtures"].add(source)
        for text in findings.limitations:
            limitations.setdefault(text, set()).add(source)
    records = []
    for key in sorted(groups):
        record = groups[key]
        records.append({**record, "examples": sorted(record["examples"]),
                        "fixtures": sorted(record["fixtures"])})
    return {
        "rulesetVersion": "2.0.0",
        "scope": "Observed fixture output only; unexercised branches require source inventory.",
        "findings": records,
        "limitations": [{"text": text, "fixtures": sorted(limitations[text])}
                        for text in sorted(limitations)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbooks", nargs="*", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = json.dumps(export(args.workbooks or None), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
