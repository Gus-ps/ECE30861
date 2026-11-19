"""Time audits end to end through the API (PERF-1, AC-18).

Usage: python scripts/perf_service.py --base-url URL --token TOKEN [--runs 5] WORKBOOK...

Execution time comes from a separate run of service_worker.py on this host, because the
service doesn't record when a worker claims a job; queue time is end-to-end minus that
execution time and is approximate. See .claude/skills/service-performance for the rules.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
BUDGETS = {'execution_seconds': 60, 'queue_seconds': 15, 'end_to_end_seconds': 80}  # spec §12/§17
RESPONSE_LIMIT = 64 * 1024**2
POLL_INTERVAL = 0.25
ACCEPTED = ('SUCCESS', 'PROCESSING_FAILED')


def call(base, token, method, path, body=None, headers=None):
    request = Request(base.rstrip('/') + path, data=body, method=method,
                      headers={'Authorization': f'Bearer {token}', **(headers or {})})
    try:
        with urlopen(request, timeout=120) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def error_code(body):
    try:
        return json.loads(body).get('code')
    except (ValueError, AttributeError):
        return None


def fingerprint(findings):
    keys = sorted([f['ruleId'], f['worksheet'], f['target'], f['category'], f['findingId']] for f in findings)
    return hashlib.sha256(json.dumps(keys).encode()).hexdigest()


def execution_seconds(path):
    start = time.monotonic()
    try:
        done = subprocess.run([sys.executable, str(ROOT / 'service_worker.py'), 'audit', str(path)],
                              capture_output=True, timeout=BUDGETS['execution_seconds'])
    except subprocess.TimeoutExpired:
        return None
    return time.monotonic() - start if done.returncode == 0 else None


def run_once(base, token, path):
    run = dict(workbook=path.name, outcome=None, error_code=None, upload_seconds=None, end_to_end_seconds=None,
               execution_seconds=None, queue_seconds=None, findings_count=None, fingerprint=None,
               findings_bytes=None, report_bytes=None)
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            'Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n'
            ).encode() + path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    sent = time.monotonic()
    status, body = call(base, token, 'POST', '/api/v1/workbooks', body,
                        {'Content-Type': f'multipart/form-data; boundary={boundary}'})
    start = time.monotonic()
    run['upload_seconds'] = start - sent  # request transfer, validation and storage
    if status != 202:
        return dict(run, outcome=f'UPLOAD_{status}', error_code=error_code(body))
    accepted = json.loads(body)
    audit_path = '/api/v1/workbooks/{workbookId}/versions/{versionId}/audits/{auditId}'.format(**accepted)
    while True:
        status, body = call(base, token, 'GET', audit_path)
        elapsed = time.monotonic() - start
        if status != 200:
            return dict(run, outcome=f'AUDIT_{status}', error_code=error_code(body))
        audit = json.loads(body)
        if audit['status'] != 'PROCESSING':
            break
        if elapsed > BUDGETS['end_to_end_seconds']:
            return dict(run, outcome='TIMEOUT', end_to_end_seconds=elapsed)
        time.sleep(POLL_INTERVAL)
    report_status, report = call(base, token, 'GET', audit_path + '/report')
    failed = audit['status'] == 'PROCESSING_FAILED'
    run.update(outcome='PROCESSING_FAILED' if failed else 'SUCCESS',
               error_code=(audit.get('error') or {}).get('code'), end_to_end_seconds=elapsed,
               findings_bytes=len(body), report_bytes=len(report) if report_status == 200 else None)
    if not failed:
        run.update(findings_count=len(audit['findings']), fingerprint=fingerprint(audit['findings']))
    run['execution_seconds'] = execution_seconds(path)
    if run['execution_seconds'] is not None:
        run['queue_seconds'] = elapsed - run['execution_seconds']
    return run


def verdict(runs, metric, budget):
    """Skill §4: judge the slowest run; any uncontrolled run or differing findings fails."""
    values = [r[metric] for r in runs if r[metric] is not None]
    if (any(r['outcome'] not in ACCEPTED for r in runs)
            or any(r['outcome'] == 'SUCCESS' and r[metric] is None for r in runs)
            or len({r['fingerprint'] for r in runs if r['outcome'] == 'SUCCESS'}) > 1
            or (values and max(values) > budget)):
        return 'FAIL'
    failed = sum(r['outcome'] == 'PROCESSING_FAILED' for r in runs)
    if failed:
        result = f'CONTROLLED FAILURE ({failed}/{len(runs)} runs)'
    else:
        result = 'PASS WITH HEADROOM' if max(values) <= 0.75 * budget else 'MARGINAL'
    if len(values) > 1 and max(values) - min(values) > 0.2 * statistics.median(values):
        result += '; noisy, repeat'
    return result


def summary(runs):
    lines = [f"{'metric':<20}{'min':>9}{'median':>9}{'max':>9}  verdict"]
    for metric, budget in BUDGETS.items():
        values = [r[metric] for r in runs if r[metric] is not None]
        stats = [f'{v:9.2f}' for v in (min(values), statistics.median(values), max(values))] if values else ['        -'] * 3
        label = metric.replace('_seconds', '') + (' (approx)' if metric == 'queue_seconds' else '')
        lines.append(f"{label:<20}{''.join(stats)}  {verdict(runs, metric, budget)} (budget {budget} s)")
    sizes = [r[k] for r in runs for k in ('findings_bytes', 'report_bytes') if r[k] is not None]
    outcomes = sorted('/'.join(filter(None, (r['outcome'], r['error_code']))) for r in runs)
    lines += [f"outcomes: {', '.join(outcomes)}",
              f"findings counts: {sorted({r['findings_count'] for r in runs if r['findings_count'] is not None})}, "
              f"distinct fingerprints: {len({r['fingerprint'] for r in runs if r['fingerprint']})}",
              f'largest response: {max(sizes, default=0)} bytes (limit {RESPONSE_LIMIT})']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--token', required=True)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('workbooks', nargs='+', type=Path)
    args = parser.parse_args()
    out = ROOT / '.perf'
    out.mkdir(exist_ok=True)
    for path in args.workbooks:
        run_once(args.base_url, args.token, path)  # untimed warm-up, discarded
        runs = [run_once(args.base_url, args.token, path) for _ in range(args.runs)]
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        (out / f'{path.stem}-{stamp}.json').write_text(json.dumps(runs, indent=2), encoding='utf-8')
        print(f'\n{path.name} ({path.stat().st_size} bytes, {args.runs} runs after 1 warm-up)\n{summary(runs)}')


if __name__ == '__main__':
    main()
