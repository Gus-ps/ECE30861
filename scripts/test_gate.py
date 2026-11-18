"""Phase 5 test gate: fail only on test failures that are not in the recorded baseline.

Usage:
  python scripts/test_gate.py           # run suites, compare with baseline (exit 1 on new failures)
  python scripts/test_gate.py --update  # rewrite the baseline (human use only)

The Gustavo suite carries inherited failures (AGENTS.md, SYS-006). The gate compares the
exact FAIL/ERROR test IDs, including subTest labels, against scripts/test_baseline.json.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / 'scripts' / 'test_baseline.json'
SUITES = [
    ['-m', 'unittest', 'discover', '-s', 'tests', '-v'],
    ['-m', 'unittest', 'test_remediation', '-v'],
]
EVENT = re.compile(r'^(FAIL|ERROR): (.+)$')


def run():
    events, ran = set(), 0
    for args in SUITES:
        out = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True,
                             encoding='utf-8', errors='replace')
        text = out.stdout + out.stderr
        events |= {f'{m[1]} {m[2]}' for m in map(EVENT.match, text.splitlines()) if m}
        ran += sum(int(n) for n in re.findall(r'^Ran (\d+) tests?', text, re.M))
    return events, ran


def main():
    events, ran = run()
    if ran == 0:
        print('GATE FAILED: no tests ran.')
        return 1
    if '--update' in sys.argv:
        BASELINE.write_text(json.dumps(sorted(events), indent=1) + '\n', encoding='utf-8')
        print(f'Baseline updated: {len(events)} known failure/error events, {ran} tests.')
        return 0
    known = set(json.loads(BASELINE.read_text(encoding='utf-8')))
    new, fixed = sorted(events - known), sorted(known - events)
    print(f'Ran {ran} tests. Known failures: {len(events & known)}. New: {len(new)}. Fixed: {len(fixed)}.')
    for line in new:
        print('  NEW  ', line)
    for line in fixed:
        print('  FIXED', line)
    if new:
        print('GATE FAILED: new failures above.')
        return 1
    print('GATE PASSED.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
