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


##  ---- Project API (consumed; ref/phase3.md appendix and Phase 4 wire schemas) ----
##  Phase 4 keeps these shapes; it only tightens requestId to an Identifier, which
##  Phase 3 already required of request identifiers.

SemVer = Annotated[str, StringConstraints(
    pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")]


class HealthResponse(Strict):
    status: Literal["AVAILABLE"]
    apiVersion: Literal["1.0"]
    rulesetVersion: SemVer


class ProjectError(Strict):
    code: NonBlank
    message: NonBlank
    requestId: Identifier
    details: dict[str, object]


class UploadResponse(Strict):
    workbookId: Identifier
    versionId: Identifier
    auditId: Identifier
    status: Literal["PROCESSING"]


Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
UtcTime = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")]
FindingText = Annotated[str, StringConstraints(min_length=1, max_length=500, pattern=r"\S")]
AuditStatus = Literal["PROCESSING", "AUDIT_COMPLETE", "REVIEW_REQUIRED", "REMEDIATION_AVAILABLE", "PROCESSING_FAILED"]


VersionStatus = Literal["PROCESSING", "AUDIT_COMPLETE", "REVIEW_REQUIRED", "REMEDIATION_AVAILABLE", "REMEDIATING",
                        "REMEDIATED", "PROCESSING_FAILED"]


class VersionResponse(Strict):
    workbookId: Identifier
    versionId: Identifier
    fileName: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    sha256: Sha256
    createdAt: UtcTime
    status: VersionStatus
    latestAuditId: Identifier | None
    sourceVersionId: Identifier | None


class Finding(Strict):
    findingId: Sha256
    ruleId: NonBlank
    category: Literal["NON_TEXT_CONTENT", "TABLE_STRUCTURE", "MERGED_CELLS", "WORKSHEET_NAME", "LINK_TEXT",
                      "COLOR_OR_CONTRAST"]
    worksheet: str
    target: NonBlank
    classification: Literal["AUTOMATICALLY_REMEDIABLE", "REQUIRES_USER_INPUT", "MANUAL_REVIEW"]
    message: FindingText
    recommendation: FindingText


class AuditResponse(Strict):
    auditId: Identifier
    workbookId: Identifier
    versionId: Identifier
    rulesetVersion: SemVer
    status: AuditStatus
    startedAt: UtcTime
    completedAt: UtcTime | None
    findings: list[Finding]
    limitations: list[str]
    error: ProjectError | None


##  ---- Phase 4 additions (phase4-wire-schemas.json) ----

class ReauditResponse(Strict):
    auditId: Identifier
    versionId: Identifier
    rulesetVersion: SemVer
    status: Literal["PROCESSING"]


class HistoryVersion(Strict):
    versionId: Identifier
    sourceVersionId: Identifier | None
    status: VersionStatus
    createdAt: UtcTime


class HistoryAudit(Strict):
    auditId: Identifier
    versionId: Identifier
    rulesetVersion: SemVer
    status: AuditStatus


class HistoryResponse(Strict):
    workbookId: Identifier
    versions: list[HistoryVersion]
    audits: list[HistoryAudit]


class AuditReport(Strict):
    ##  Top-level shape only; decision and approved-change items are validated once the
    ##  remediation checks that produce them exist.
    reportVersion: Literal["2.0.0"]
    specificationVersion: Literal["2.1.0"]
    workbookId: Identifier
    versionId: Identifier
    auditId: Identifier
    fileName: Annotated[str, StringConstraints(min_length=1, max_length=255, pattern=r"\S")]
    sha256: Sha256
    sourceVersionId: Identifier | None
    auditDate: UtcTime
    rulesetVersion: SemVer
    status: Literal["AUDIT_COMPLETE", "REVIEW_REQUIRED", "REMEDIATION_AVAILABLE", "PROCESSING_FAILED"]
    checksPerformed: list[Literal["ALT_TEXT", "WORKSHEET_NAME", "TABLE_HEADER", "MERGED_CELLS", "LINK_TEXT",
                                  "COLOR_CONTRAST"]]
    findings: list[Finding]
    decisions: list[dict[str, object]]
    approvedChanges: list[dict[str, object]]
    unresolvedFindings: list[Finding]
    manualReviewItems: list[Finding]
    limitations: list[NonBlank]
    remediationId: Identifier | None
    outputVersionId: Identifier | None
    outputId: Identifier | None
    error: ProjectError | None


##  ---- Suite manifest (tester/fixtures/manifest.json, Team 9 format) ----

class ManifestCase(BaseModel):
    model_config = ConfigDict(extra="ignore")

    test_id: NonBlank
    check: NonBlank
    description: str = ""
    components: list[str] = []
    acceptance: list[str] = []
    operations: list[int | str] = []
    prerequisites: list[str] = []
    parameters: dict[str, object] = {}


class Manifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    manifest_version: str
    ruleset_version: str
    specification_version: str | None = None
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


##  ---- Fixture pack (an expectations.json beside its workbooks) ----
##  Only the fields the tester needs to load and verify bytes are required;
##  per-fixture expectations are kept whole for the check functions.

class FixtureEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: Literal["accepted", "rejected"]
    file: NonBlank
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    origin: NonBlank
    upload_name: NonBlank


class FixturePack(BaseModel):
    model_config = ConfigDict(extra="allow")

    ruleset_version: NonBlank
    fixtures: dict[str, FixtureEntry]


##  ---- Pod profile (tester/fixtures/pod_profile.json, pod_profile_phase4.json) ----
##  Phase 3 values are Team 9 defaults awaiting pod confirmation; Phase 4 values
##  come from the shared specification 2.1.0.

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
    ##  Basis text reported with each measure, stated by the phase's contract.
    component_basis: NonBlank
    system_basis: NonBlank


class Timing(Strict):
    system_setup_seconds: float = Field(gt=0)
    tester_setup_seconds: float = Field(gt=0)
    upload_seconds: float = Field(gt=0)
    get_seconds: float = Field(gt=0)
    audit_poll_seconds: float = Field(gt=0)
    poll_interval_seconds: float = Field(gt=0)
    suite_seconds: float = Field(gt=0)
    get_retries: int = Field(ge=0)
    ##  Phase 4 only; null in a profile whose phase has no remediation or downloads.
    remediation_poll_seconds: float | None = Field(default=None, gt=0)
    download_seconds: float | None = Field(default=None, gt=0)


class ResponseLimits(Strict):
    json_bytes: int = Field(gt=0)
    binary_bytes: int = Field(gt=0)


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
    response_limits: ResponseLimits
    cleanup: CleanupPolicy
