"""Builds the Phase 4 fixture pack bundle for Team 9's two-member review (shared specification §15.2).

Writes dist/team12-phase4-pack-review.zip: every file in tester/fixtures/phase4/, a generated
REVIEW.md (scope, how to verify, per-entry summary, points needing a decision), a
review-form.csv with one row per item for two reviewers, and SHA256SUMS.txt over the rest.
The pack is checked first (file hashes, recomputed finding IDs); a stale pack refuses to build.
ZIP entries use a fixed timestamp, so the same pack always gives the same bytes.

    uv run python scripts/build_review_bundle.py
"""

import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tester.suite.identity import finding_id  # noqa: E402

PACK = ROOT / "tester" / "fixtures" / "phase4"
OUT = ROOT / "dist" / "team12-phase4-pack-review.zip"
TOP = "team12-phase4-pack"
STAMP = (2026, 11, 1, 0, 0, 0)
ALIASES = {"clean": "clean_all_six", "seeded_issues": "seeded_all_six"}

##  Points where Team 12 chose an interpretation the specification leaves open; each needs a
##  reviewer decision. Keep in step with the shared doc's "interpretations to confirm".
DECISIONS = [
    ("table_header_vectors", "Excel repairs tables 3 (Blank) and 4 (Duplicate) on open. They are states Excel cannot "
     "store, kept because §7.4 requires systems to flag them; both are MANUAL_REVIEW, so no output edits them."),
    ("contrast_vectors", "Pack 2.1.1 tint cells on the Theme sheet: A9 (1A334D), A11 (030303 on 757575, the observable "
     "half-boundary case) and A13 (010101, coverage only: no fill separates it from a wrong 000000)."),
    ("contrast_vectors", "A conditional format whose rule sets no colour is not itself a colour finding; only the "
     "suppression of cells inside a colour rule is."),
    ("header_range, seeded_all_six, mixed_decisions", "A new table gets the lowest unused table ID starting at 1 and the "
     "first free A11yTable<ID> name, with _1, _2 ... on a case-insensitive collision (header_range expects A11yTable2_1); "
     "it has no autoFilter, tableStyleInfo or sortState."),
    ("rename_references", "docProps/app.xml sheet titles may be updated after a rename but need not be."),
    ("in_cell_picture, image_formula, form_controls, vml_comments", "Team 12 also expects a limitation for the "
     "uninterpreted representation itself (§7.2); your entries list none. Limitations are compared by presence only."),
    ("form_controls", "Your file opens with an Excel repair (undeclared x14 prefix in sheet1.xml; also a14, incomplete "
     "anchors and no VML drawing). Bytes kept unchanged; see the reply email."),
]

ALLOWED = [
    "ZIP serialization: compression, timestamps, entry order and offsets may differ.",
    "Every entry no approved change touches must be byte-identical after decompression.",
    "A touched part is compared semantically: element and attribute names, values, text, comments, processing "
    "instructions and namespace declarations. Attribute order, whitespace-only text outside <t>, and xml:space on <t> "
    "may differ.",
    "After a rename, docProps/app.xml titles may be updated or left as they were.",
    "A header correction's new table may omit the name attribute (it must then equal displayName) and headerRowCount "
    "(or set it to 1); it must not add autoFilter, tableStyleInfo, sortState or a totals row.",
]


def load():
    data = json.loads((PACK / "expectations.json").read_text(encoding="utf-8"))
    problems = []
    for key, entry in data["fixtures"].items():
        digest = hashlib.sha256((PACK / entry["file"]).read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            problems.append(f"{key}: {entry['file']} has SHA256 {digest}, the entry records {entry['sha256']}")
    if problems:
        raise SystemExit("Pack is stale; rebuild it first:\n" + "\n".join(problems))
    return data


def count(items, noun):
    return f"{len(items)} {noun}{'' if len(items) == 1 else 's'}"


def summary_rows(data):
    rows = []
    for key, e in data["fixtures"].items():
        if key in ALIASES:
            continue
        if e["kind"] == "rejected":
            result = f"{e['http_status']} rejection"
        else:
            extras = [count(e["corrections"], "correction") if e.get("corrections") else "",
                      count(e["decision_sets"], "decision set") if e.get("decision_sets") else "",
                      count(e["vectors"], "vector case") if e.get("vectors") else ""]
            result = ", ".join([f"{e['expected_status']}, {count(e['findings'], 'finding')}"] + [x for x in extras if x])
        excel = (e.get("excel_open") or {}).get("result", "not opened")
        rows.append(f"| `{key}` | {e['origin']} | `{e['sha256'][:12]}…` | {result} | {excel} |")
    return rows


def review_md(data):
    lines = [
        "# Team 12 Phase 4 fixture pack: review by Team 9", "",
        f"Ruleset {data['ruleset_version']}, specification {data['specification_version']}, context pack 2.1.1. "
        f"{len(data['fixtures'])} entries ({len(ALIASES)} are aliases for the Phase 3-numbered cases). "
        "Spec §15.2 asks two members of the other team to review each fixture's hash, its expected results under "
        "all six rules (targets, classifications, status, limitations), the correction effects and the allowed "
        "preservation differences. Nothing here was derived by running an engine: expectations were written by hand "
        "from the package XML. The four `origin: team9` files are yours, bytes unchanged, with expectations Team 12 "
        "re-derived.", "",
        "## How to review", "",
        "1. Check `SHA256SUMS.txt` (for example `sha256sum -c SHA256SUMS.txt`). Each workbook's hash is also its "
        "`sha256` in `expectations.json`.",
        "2. For each entry, read its `notes` and section in `README.md` (intent, every expected finding with its "
        "findingId), then the workbook's XML. Recompute any findingId you like from the hash with the contract "
        "identity formula.",
        "3. Record each reviewer's decision in `review-form.csv`: `agree`, `disagree` or `question`, with a note for "
        "anything but `agree`. Rows marked `decision` below are interpretations Team 12 chose.",
        "4. Send the form back; Team 12 records the names, date and decisions in each entry's `review` field and fixes "
        "or re-asks anything disputed. Any byte change gives a new hash and new finding IDs.", "",
        "## Entries", "",
        "| Key | Origin | SHA256 | Expected | Excel open (2026-11-01) |", "| --- | --- | --- | --- | --- |",
        *summary_rows(data), "",
        "Aliases: `clean` and `seeded_issues` are the same files and expectations as `clean_all_six` and "
        "`seeded_all_six`, for the Phase 3-numbered plan cases (the plan's adaptation note).", "",
        "## Points needing a decision", "",
        *[f"- **{where}:** {what}" for where, what in DECISIONS], "",
        "## Allowed preservation differences (Team 12's comparator, spec §11)", "",
        *[f"- {item}" for item in ALLOWED], "",
        "Correction effects are listed per correction fixture in `expectations.json` (`corrections`: target, value, "
        "effect; `decision_sets` for the batch fixtures) and described in `README.md`.", "",
    ]
    return "\n".join(lines)


def review_form(data):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["entry", "item", "detail", "findingId", "reviewer_1_decision", "reviewer_1_note",
                     "reviewer_2_decision", "reviewer_2_note"])
    blank = ["", "", "", ""]
    for key, e in data["fixtures"].items():
        if key in ALIASES:
            writer.writerow([key, "alias", f"same file and expectations as {ALIASES[key]}", "", *blank])
            continue
        writer.writerow([key, "hash", e["sha256"], "", *blank])
        if e["kind"] == "rejected":
            writer.writerow([key, "rejection", f"HTTP {e['http_status']}, no accepted identifiers", "", *blank])
            continue
        writer.writerow([key, "status", e["expected_status"], "", *blank])
        for f in e["findings"]:
            fid = finding_id(e["sha256"], data["ruleset_version"], f["ruleId"], f["worksheet"], f["target"])
            writer.writerow([key, "finding", f"{f['ruleId']} {f['classification']} on {f['worksheet']!r} at "
                                             f"{f['target']}", fid, *blank])
        writer.writerow([key, "limitations", " | ".join(e["limitation_facts"]) or "none expected", "", *blank])
        for c in e.get("corrections") or []:
            writer.writerow([key, "correction", f"{c['target']} -> {json.dumps(c['value'], ensure_ascii=False)}: "
                                                f"{c.get('effect', '')}", "", *blank])
        for name in e.get("decision_sets") or {}:
            writer.writerow([key, "decision set", name, "", *blank])
    for where, what in DECISIONS:
        writer.writerow([where, "decision", what, "", *blank])
    return buffer.getvalue()


def build():
    data = load()
    ##  Flat, as in the pack: expectations.json names workbooks relative to its own folder.
    files = {f"{TOP}/{p.name}": p.read_bytes() for p in sorted(PACK.iterdir()) if p.is_file()}
    files[f"{TOP}/REVIEW.md"] = review_md(data).encode("utf-8")
    files[f"{TOP}/review-form.csv"] = review_form(data).encode("utf-8")
    sums = "".join(f"{hashlib.sha256(data_).hexdigest()}  {name.removeprefix(TOP + '/')}\n"
                   for name, data_ in sorted(files.items()))
    files[f"{TOP}/SHA256SUMS.txt"] = sums.encode("utf-8")
    pack = json.loads(files[f"{TOP}/expectations.json"])
    missing = [e["file"] for e in pack["fixtures"].values() if f"{TOP}/{e['file']}" not in files]
    assert not missing, missing
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data_ in sorted(files.items()):
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data_)
    return buffer.getvalue(), files


def main():
    data, files = build()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_bytes(data)
    print(f"wrote {OUT} ({len(data):,} bytes, {len(files)} files, SHA256 {hashlib.sha256(data).hexdigest()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
