"""Builds the Phase 5 add-on review bundle for Team 9 (test plan P5-MANUAL-FIXTURE-REVIEW).

Phase 5 adds one fixture to the Phase 4 pack Team 9 already has (dist/team12-phase4-pack-review.zip,
unchanged): performance_250000_cells. This writes dist/team12-phase5-addon-review.zip with the
workbook, its expectations entry, a REVIEW.md, a review-form.csv for two reviewers, and
SHA256SUMS.txt. The workbook hash is checked first; ZIP entries use a fixed timestamp, so the same
inputs always give the same bytes.

    uv run python scripts/build_phase5_review_bundle.py
"""

import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tester" / "fixtures"
OUT = ROOT / "dist" / "team12-phase5-addon-review.zip"
TOP = "team12-phase5-addon"
STAMP = (2026, 11, 17, 0, 0, 0)
KEY = "performance_250000_cells"


def load():
    entry = json.loads((FIXTURES / "expectations_phase5.json").read_text(encoding="utf-8"))["fixtures"][KEY]
    data = (FIXTURES / entry["file"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise SystemExit(f"{entry['file']} does not match its recorded SHA256; rebuild the Phase 5 fixtures first.")
    return entry, data


def review_md(entry):
    return "\n".join([
        "# Team 12 Phase 5 fixture add-on: review by Team 9", "",
        "Phase 5 (specification 3.0.0, ruleset 2.0.0) adds one fixture to the Phase 4 pack you already have: "
        f"`{KEY}`, used by P5-PERFORMANCE-RUN-1 to -5 and P5-PERFORMANCE-COMPARE. The Phase 4 entries are unchanged "
        "(same bytes and expectations as `team12-phase4-pack-review.zip`).", "",
        "## What it is", "", entry["notes"], "",
        f"Expected: HTTP {entry['http_status']} on upload, status {entry['expected_status']}, no findings, no "
        "limitations. Written by hand from the definition in `scripts/build_phase5_fixtures.py`, not by running an "
        "engine. It has not been opened in Excel.", "",
        "## How to review", "",
        "1. Check `SHA256SUMS.txt`; the workbook's hash is also `sha256` in `expectations-entry.json`.",
        "2. Confirm the workbook holds exactly 250,000 nonempty cells (the shared limit: accepted, not rejected).",
        "3. Confirm that no rule should report anything: one formal table covers every populated cell with a header "
        "row, the worksheet name is descriptive, and there are no merges, links, objects or nonneutral colours.",
        "4. Record each reviewer's decision in `review-form.csv` (`agree`, `disagree` or `question`, with a note for "
        "anything but `agree`) and send it back.", "",
        "## Question for you", "",
        "- Should a 250,000-cell audit carry any limitation (for example a size or time note)? Team 12 expects none.",
        "",
    ])


def review_form(entry):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["entry", "item", "detail", "reviewer_1_decision", "reviewer_1_note", "reviewer_2_decision",
                     "reviewer_2_note"])
    for item, detail in (("hash", entry["sha256"]), ("cell count", "exactly 250,000 nonempty cells"),
                         ("upload", f"HTTP {entry['http_status']}"), ("status", entry["expected_status"]),
                         ("findings", "none expected"), ("limitations", "none expected")):
        writer.writerow([KEY, item, detail, "", "", "", ""])
    return buffer.getvalue()


def build():
    entry, data = load()
    files = {f"{TOP}/{KEY}.xlsx": data,
             f"{TOP}/expectations-entry.json": (json.dumps({KEY: entry}, indent=2) + "\n").encode("utf-8"),
             f"{TOP}/REVIEW.md": review_md(entry).encode("utf-8"),
             f"{TOP}/review-form.csv": review_form(entry).encode("utf-8")}
    sums = "".join(f"{hashlib.sha256(body).hexdigest()}  {name.removeprefix(TOP + '/')}\n"
                   for name, body in sorted(files.items()))
    files[f"{TOP}/SHA256SUMS.txt"] = sums.encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in sorted(files.items()):
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, body)
    return buffer.getvalue(), files


def main():
    data, files = build()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_bytes(data)
    print(f"wrote {OUT} ({len(data):,} bytes, {len(files)} files, SHA256 {hashlib.sha256(data).hexdigest()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
