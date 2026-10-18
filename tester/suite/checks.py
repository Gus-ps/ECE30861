"""Check functions, keyed by the manifest's `check` name.

Each takes (case, ctx) and returns a CaseResult. Call ctx.mark() once the
case's qualifying assertion is actually evaluated, pass or fail.
"""

from pydantic import ValidationError

from ..models import SystemReport, TestEndpointError
from .runner import CaseResult


def _schema_problem(error: ValidationError):
    first = error.errors()[0]
    where = ".".join(str(p) for p in first["loc"]) or "body"
    return f"{where}: {first['msg']}"


def _system_failure(name, response):
    return CaseResult.error("system", f"{name} returned an unexpected {response.status} internal failure.")


def system_report(case, ctx):
    ##  P3-CODE-REPORT: GET system /test/report returns this session's code coverage.
    response = ctx.target.system_report(ctx.session_id, ctx.deadline)
    if response.status >= 500:
        return _system_failure("System report", response)
    ctx.mark()
    if response.status != 200:
        return CaseResult.failed(f"Expected 200 from system report; received {response.status}.")
    try:
        report = SystemReport.model_validate(response.json())
    except ValidationError as error:
        return CaseResult.failed(f"System report body does not match SystemReport ({_schema_problem(error)}).")
    if report.session_id != ctx.session_id:
        return CaseResult.failed(f"System report echoed session {report.session_id}, not {ctx.session_id}.")
    measure = report.coverage["code"]
    ctx.record_code_coverage(measure.model_dump())
    if measure.covered is None:
        return CaseResult.passed(f"System report returned paired null code coverage ({measure.basis}).")
    return CaseResult.passed(f"System report returned code coverage {measure.covered}/{measure.total}.")


def system_setup_duplicate(case, ctx):
    ##  P3-SESSION-DUPLICATE: repeating system setup with this session's ID returns 409.
    response = ctx.target.system_setup(ctx.session_id, {}, ctx.deadline)
    if response.status >= 500:
        return _system_failure("Duplicate system setup", response)
    ctx.mark()
    if response.status != 409:
        return CaseResult.failed(f"Expected 409 for a duplicate system setup; received {response.status}.")
    try:
        TestEndpointError.model_validate(response.json())
    except ValidationError as error:
        return CaseResult.failed(f"409 body does not match TestEndpointError ({_schema_problem(error)}).")
    return CaseResult.passed("Duplicate system setup returned 409 with a valid {message, source} body.")


CHECKS = {
    "system_report": system_report,
    "system_setup_duplicate": system_setup_duplicate,
}
