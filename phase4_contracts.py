from typing import Any, Literal
from pydantic import Field
from contracts import Contract, Identifier, Audit, Finding, Error, WorkbookVersion


class ReauditRequest(Contract):
    reason: Literal['MANUAL_REAUDIT'] = 'MANUAL_REAUDIT'


class ReauditResponse(Contract):
    auditId: Identifier
    versionId: Identifier
    rulesetVersion: str
    status: Literal['PROCESSING']


class Decision(Contract):
    findingId: str = Field(pattern='^[0-9a-f]{64}$')
    action: Literal['APPLY', 'DECLINE', 'MANUAL_REVIEW']
    value: Any = None


class RemediationRequest(Contract):
    auditId: Identifier
    decisions: list[Decision] = Field(min_length=1, max_length=1000)


class RemediationAccepted(Contract):
    remediationId: Identifier
    sourceVersionId: Identifier
    status: Literal['REMEDIATING']


class RemediationResponse(Contract):
    remediationId: Identifier
    sourceVersionId: Identifier
    status: Literal['REMEDIATING', 'REMEDIATED', 'PROCESSING_FAILED']
    outputVersionId: Identifier | None
    outputId: Identifier | None
    auditId: Identifier | None
    error: Error | None


class ReviewItem(Contract):
    findingId: str
    allowedActions: list[Literal['APPLY', 'DECLINE', 'MANUAL_REVIEW']]
    currentValue: dict | None
    reason: str = Field(min_length=1, max_length=500)


class ReviewResponse(Contract):
    workbookId: Identifier
    versionId: Identifier
    auditId: Identifier
    items: list[ReviewItem]


class HistoryVersion(Contract):
    versionId: Identifier
    sourceVersionId: Identifier | None
    status: str
    createdAt: str


class HistoryAudit(Contract):
    auditId: Identifier
    versionId: Identifier
    rulesetVersion: str
    status: str


class HistoryResponse(Contract):
    workbookId: Identifier
    versions: list[HistoryVersion]
    audits: list[HistoryAudit]


class ReportDecision(Contract):
    sourceAuditId: Identifier
    findingId: str
    ruleId: str
    worksheet: str
    target: str
    action: Literal['APPLY', 'DECLINE', 'MANUAL_REVIEW']
    value: dict | None


class AuditReport(Contract):
    reportVersion: Literal['2.0.0']
    specificationVersion: Literal['2.1.0']
    workbookId: Identifier
    versionId: Identifier
    auditId: Identifier
    fileName: str
    sha256: str
    sourceVersionId: Identifier | None
    auditDate: str
    rulesetVersion: str
    status: str
    checksPerformed: list[str]
    findings: list[Finding]
    decisions: list[ReportDecision]
    approvedChanges: list[ReportDecision]
    unresolvedFindings: list[Finding]
    manualReviewItems: list[Finding]
    limitations: list[str]
    remediationId: Identifier | None
    outputVersionId: Identifier | None
    outputId: Identifier | None
    error: Error | None
