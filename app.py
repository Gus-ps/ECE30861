"""Workbook service entry point."""
import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
import sys

from service_errors import ApiError
from phase4_service import create_app, MAX_UPLOAD, RULESET_VERSION
from phase4_store import now as utc_now
ROOT = Path(__file__).parent

def load_workbook_validator():
    path = Path(os.getenv('VALIDATOR_PATH', str(ROOT / 'validity_check.py')))
    if not path.is_file():
        return None
    path = path.resolve()

    def validate(filepath):
        # Isolation closes the supplied checker's file handles before Windows
        # removes the temporary file. Keep printed messages separate from JSON.
        completed = subprocess.run(
            [sys.executable, '-c', '''import contextlib, io, json, runpy, sys
output = io.StringIO()
with contextlib.redirect_stdout(output):
    module = runpy.run_path(sys.argv[1])
    checker = module.get("check_validity", module.get("validate_file"))
    result = checker(sys.argv[2])
    errors = result if isinstance(result, list) else []
    if result is False or type(result) is int and result == 0:
        explain = module.get("validate_file")
        if explain is not None and explain is not checker:
            explanation = explain(sys.argv[2])
            if isinstance(explanation, list):
                errors = explanation
print(json.dumps({"result": result, "output": output.getvalue(), "errors": errors}))
''', str(path), filepath], capture_output=True, text=True, timeout=60)
        if completed.stderr:
            print(completed.stderr, end='', file=sys.stderr, flush=True)
        completed.check_returncode()
        payload = json.loads(completed.stdout)
        if payload['output']:
            print(payload['output'], end='', flush=True)
        result = payload['result']
        if isinstance(result, list) and all(isinstance(error, str) for error in result):
            result = not result
        if type(result) in (bool, int) and result in (False, 0):
            errors = payload['errors']
            if not errors and payload['output'].strip():
                errors = [payload['output'].strip()]
            raise ApiError(422, 'INVALID_WORKBOOK', 'Workbook is invalid.', {'valid': False, 'errors': errors})
        return result
    return validate


app = create_app()
