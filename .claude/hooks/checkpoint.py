"""StopFailure hook: record the working-tree state when a session dies on an API error.

The agent can't run its own checkpoint at that point, so this appends a snapshot to
PHASE5_HANDOFF.md for whoever resumes (rule 12 in PHASE5_TASKS.md).
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parents[2]
data = json.load(sys.stdin)
git = lambda *a: subprocess.run(['git', *a], cwd=root, capture_output=True, text=True).stdout.rstrip()
error = {k: v for k, v in data.items() if k not in ('session_id', 'transcript_path', 'cwd')}
with open(root / 'PHASE5_HANDOFF.md', 'a', encoding='utf-8') as f:
    f.write(f"\n### {datetime.now():%Y-%m-%d %H:%M} session ended on error\n"
            f"Session: {data.get('session_id')}\n"
            f"Error: {json.dumps(error)}\n"
            f"HEAD: {git('log', '-1', '--oneline')}\n"
            f"```\n{git('status', '--short')}\n{git('diff', '--stat')}\n```\n")
