"""Wire models for the instructor testing interface (ref/tester.openapi.json)
and the tester's own configuration files."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
ErrorSource = Literal["tester", "system", "communication", "unknown"]
Outcome = Literal["pass", "fail", "error", "skip"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


##  ---- Tester endpoints ----

class TesterSetupRequest(Strict):
    target_url: NonBlank


class SetupResponse(Strict):
    session_id: Identifier


class RunRequest(Strict):
    session_id: Identifier


class TestEndpointError(Strict):
    message: NonBlank
    source: ErrorSource


class TestResult(Strict):
    test_id: NonBlank
    outcome: Outcome
    message: NonBlank
    source: ErrorSource | None = None

    @model_validator(mode="after")
    def source_only_on_error(self):
        if (self.outcome == "error") != (self.source is not None):
            raise ValueError("source is required for error outcomes and omitted otherwise")
        return self


class CoverageMeasure(Strict):
    covered: int | None = Field(ge=0)
    total: int | None = Field(ge=0)
    basis: NonBlank

    @model_validator(mode="after")
    def paired_counts(self):
        if (self.covered is None) != (self.total is None):
            raise ValueError("covered and total must both be null or both be integers")
        if self.covered is not None and self.covered > self.total:
            raise ValueError("covered must not exceed total")
        return self


class SuiteCoverage(Strict):
    code: CoverageMeasure
    component: CoverageMeasure
    system: CoverageMeasure


class SuiteReport(Strict):
    session_id: Identifier
    target_url: NonBlank
    results: list[TestResult]
    coverage: SuiteCoverage


##  ---- System test endpoints (consumed) ----

class SystemReport(Strict):
    session_id: Identifier
    coverage: dict[Literal["code"], CoverageMeasure]


##  ---- Suite manifest (tester/fixtures/manifest.json, Team 9 format) ----

class ManifestCase(BaseModel):
    model_config = ConfigDict(extra="ignore")

    test_id: NonBlank
    check: NonBlank
    description: str = ""
    components: list[str] = []
    acceptance: list[str] = []
    prerequisites: list[str] = []
    parameters: dict[str, object] = {}


class Manifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    manifest_version: str
    ruleset_version: str
    components: dict[str, str]
    acceptance: dict[str, str]
    tests: list[ManifestCase]

    @model_validator(mode="after")
    def consistent(self):
        ids = [case.test_id for case in self.tests]
        if len(ids) != len(set(ids)):
            raise ValueError("test_id values must be unique")
        for position, case in enumerate(self.tests):
            for prerequisite in case.prerequisites:
                if prerequisite not in ids[:position]:
                    raise ValueError(f"{case.test_id}: prerequisite {prerequisite} must run earlier")
            for component in case.components:
                if component not in self.components:
                    raise ValueError(f"{case.test_id}: unknown component {component}")
            for criterion in case.acceptance:
                if criterion not in self.acceptance:
                    raise ValueError(f"{case.test_id}: unknown acceptance criterion {criterion}")
        return self


##  ---- Pod profile (tester/fixtures/pod_profile.json) ----
##  Every value is a Team 9 default awaiting pod confirmation.

class SessionTransport(Strict):
    header: NonBlank
    send_on_health: bool
    unknown_session_status: int


class UnsupportedTypes(Strict):
    status: int
    cases: list[str]


class XlsmPolicy(Strict):
    status: int
    code: str


class Limits(Strict):
    max_file_bytes: int
    max_worksheets: int
    max_nonempty_cells: int


class AltTextPolicy(Strict):
    require_title: bool
    require_description: bool
    decorative_classification: str


class WorksheetNamePolicy(Strict):
    pattern: str
    suffix_must_exceed_zero: bool


class CoverageCatalogs(Strict):
    components: list[str]
    acceptance: list[str]


class Timing(Strict):
    system_setup_seconds: float = Field(gt=0)
    tester_setup_seconds: float = Field(gt=0)
    upload_seconds: float = Field(gt=0)
    get_seconds: float = Field(gt=0)
    audit_poll_seconds: float = Field(gt=0)
    poll_interval_seconds: float = Field(gt=0)
    suite_seconds: float = Field(gt=0)
    get_retries: int = Field(ge=0)


class CleanupPolicy(Strict):
    send_failed_setup_ids: bool


class PodProfile(Strict):
    profile_version: NonBlank
    pod_approved: bool
    note: str = ""
    session_transport: SessionTransport
    unsupported_types: UnsupportedTypes
    xlsm: XlsmPolicy
    assert_other_error_codes: bool
    limits: Limits
    protected_workbook_status: int
    alt_text: AltTextPolicy
    worksheet_name: WorksheetNamePolicy
    coverage: CoverageCatalogs
    timing: Timing
    max_response_bytes: int = Field(gt=0)
    cleanup: CleanupPolicy
