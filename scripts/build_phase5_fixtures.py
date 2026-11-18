"""Builds Team 12's Phase 5 fixture pack (shared specification 3.0.0, ruleset 2.0.0).

Phase 5 adds one fixture, performance_250000_cells (test plan P5-PERFORMANCE-RUN-1..5): exactly
250,000 nonempty cells, the shared limit, in one formal table on one descriptively named
worksheet, so a correct six-rule audit has no finding and no limitation. Every other fixture is
the adopted Phase 4 pack 2.1.1, unchanged and referenced in place.

Outputs:
    tester/fixtures/phase5/performance_250000_cells.xlsx
    tester/fixtures/expectations_phase5.json   (the Phase 4 entries under phase4/, plus the new one)

The pack root is tester/fixtures, so both folders stay inside it (the tester refuses fixture
paths outside the expectations file's folder). The expected result was written from the
definition below, not by running an engine.

    uv run python scripts/build_phase5_fixtures.py          # write the files
    uv run python scripts/build_phase5_fixtures.py --check  # verify committed bytes
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_phase4_fixtures import REL, package, table  # noqa: E402
from build_shared_fixtures import HEAD, MAIN, zipped  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tester" / "fixtures"
OUT = FIXTURES / "phase5"
EXPECTATIONS = FIXTURES / "expectations_phase5.json"
PHASE4 = FIXTURES / "phase4" / "expectations.json"

KEY = "performance_250000_cells"
SHEET = "Performance Data"
COLUMNS = ["Record", "Region", "Quarter", "Units", "Unit Price", "Revenue", "Cost", "Margin", "Returns", "Rating"]
ROWS = 25_000                  # header row + 24,999 data rows; 10 columns -> 250,000 nonempty cells
HEADER_STYLE = 1               # STYLES index 1: bold black on solid white; data uses index 0 (black on white)


def _column(index):
    return "ABCDEFGHIJ"[index]


def performance_sheet():
    ##  Hand-written worksheet XML (a 250,000-entry dict would be slow): inline-string header,
    ##  integer data, every cell inside table 1, no merges, links, objects or nonneutral colours.
    last = f"{_column(len(COLUMNS) - 1)}{ROWS}"
    rows = ['<row r="1">' + "".join(f'<c r="{_column(i)}1" s="{HEADER_STYLE}" t="inlineStr"><is><t>{name}</t></is></c>'
                                    for i, name in enumerate(COLUMNS)) + "</row>"]
    for row in range(2, ROWS + 1):
        values = (row - 1, row % 7 + 1, row % 4 + 1, row % 90 + 10, row % 40 + 5, (row % 90 + 10) * (row % 40 + 5),
                  row % 500 + 100, row % 300, row % 9, row % 5 + 1)
        rows.append(f'<row r="{row}">' + "".join(f'<c r="{_column(i)}{row}"><v>{v}</v></c>' for i, v in enumerate(values))
                    + "</row>")
    return (f'{HEAD}<worksheet xmlns="{MAIN}" xmlns:r="{REL}"><dimension ref="A1:{last}"/>'
            f'<cols><col min="1" max="{len(COLUMNS)}" width="14" customWidth="1"/></cols>'
            f'<sheetData>{"".join(rows)}</sheetData><tableParts count="1"><tablePart r:id="rId1"/></tableParts>'
            f'</worksheet>'), last


class _NoMedia:
    files = {}


def build_workbook():
    xml, last = performance_sheet()
    parts = package("Performance fixture: 250,000 nonempty cells",
                    [(SHEET, 1, 1, xml, [("rId1", f"{REL}/table", "../tables/table1.xml", False)])],
                    {1: table(1, "PerformanceRecords", f"A1:{last}", COLUMNS)}, {}, {}, _NoMedia())
    return zipped(parts)


def entry(data):
    return {
        "kind": "accepted", "file": f"phase5/{KEY}.xlsx", "sha256": hashlib.sha256(data).hexdigest(),
        "origin": "team12", "upload_name": f"{KEY}.xlsx", "http_status": 202, "expected_status": "AUDIT_COMPLETE",
        "findings": [], "limitation_facts": [],
        "notes": (f"One worksheet, {SHEET!r} (sheetId 1, sheet1.xml), holding formal table 1 (PerformanceRecords, "
                  f"A1:J{ROWS}, header row {', '.join(COLUMNS)}): exactly {len(COLUMNS) * ROWS:,} nonempty cells, "
                  f"the shared 250,000-cell limit. Header cells are bold black inline strings and data cells are "
                  f"integers, every style black on an explicit solid white fill; no merges, links, drawings, objects, "
                  f"comments, defined names or shared strings. Every populated cell is inside the table."),
        "review": {"reviewers": [], "date": None, "decisions": None},
        "excel_open": {"date": None, "reviewer": None, "excel_version": None, "platform": None, "result": None,
                       "repaired_parts": [], "expected": True, "note": "Not opened in Excel yet."},
    }


def build():
    ##  {path relative to tester/fixtures: bytes}
    workbook = build_workbook()
    phase4 = json.loads(PHASE4.read_text(encoding="utf-8"))
    fixtures = {key: {**value, "file": f"phase4/{value['file']}"} for key, value in phase4["fixtures"].items()}
    fixtures[KEY] = entry(workbook)
    pack = {
        "ruleset_version": phase4["ruleset_version"], "specification_version": "3.0.0",
        "manual_review": ("Not reviewed. Phase 5 pack: the adopted Phase 4 pack 2.1.1 entries unchanged (their "
                          "review state is in that pack's manual_review), plus performance_250000_cells, built by "
                          "scripts/build_phase5_fixtures.py and hand-authored on 2026-11-17 from its definition "
                          "before any engine was run. It has not been opened in Excel or reviewed by Team 9."),
        "fixtures": fixtures,
    }
    return {f"phase5/{KEY}.xlsx": workbook,
            EXPECTATIONS.name: (json.dumps(pack, indent=2, ensure_ascii=False) + "\n").encode("utf-8")}


def main(argv):
    files = build()
    if "--check" in argv:
        ##  A Windows checkout with core.autocrlf holds the JSON with CRLF; the workbook is binary.
        def same(name, data):
            path = FIXTURES / name
            if not path.exists():
                return False
            disk = path.read_bytes()
            return disk == data if name.endswith(".xlsx") else disk.replace(b"\r\n", b"\n") == data
        stale = [name for name, data in files.items() if not same(name, data)]
        if stale:
            print("Committed Phase 5 fixtures differ from the builder: " + ", ".join(stale))
            return 1
        print("Committed Phase 5 fixtures match the builder.")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (FIXTURES / name).write_bytes(data)
        print(f"wrote {FIXTURES / name} ({len(data):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
