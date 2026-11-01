"""Print a finished session's run record as JSON (evidence kept outside SuiteReport).

    uv run python scripts/run_record.py --db tester.db --session <session_id>

Opens the tester database read-only, so it is safe beside a running tester.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="tester.db", help="TESTER_DB_PATH of the tester (default tester.db)")
    parser.add_argument("--session", required=True, help="tester session ID")
    args = parser.parse_args()

    uri = Path(args.db).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        row = db.execute("SELECT state, record FROM sessions WHERE session_id = ?", (args.session,)).fetchone()
        if row is None:
            sys.exit(f"No session {args.session} in {args.db}.")
        state, record = row
        if record is None:
            sys.exit(f"Session {args.session} is {state}; it has no run record (only finished runs do).")
        retrievals = [r[0] for r in db.execute(
            "SELECT retrieved_at FROM report_retrievals WHERE session_id = ? ORDER BY rowid", (args.session,))]
    print(json.dumps({**json.loads(record), "report_retrievals": retrievals}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
