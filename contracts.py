"""HTTP data types for the operations and schemas supplied in PROMPT.md."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[str, StringConstraints(strict=True, pattern=r'^[A-Za-z0-9_-]{1,64}$')]
Timestamp = Annotated[str, StringConstraints(strict=True, pattern=r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$')]
SHA256 = Annotated[str, StringConstraints(strict=True, pattern=r'^[0-9a-f]{64}$')]
AuditStatus = Literal['PROCESSING', 'AUDIT_COMPLETE', 'REVIEW_REQUIRED', 'REMEDIATION_AVAILABLE', 'PROCESSING_FAILED']
VersionStatus = Literal['PROCESSING', 'AUDIT_COMPLETE', 'REVIEW_REQUIRED', 'REMEDIATION_AVAILABLE', 'REMEDIATING', 'REMEDIATED', 'PROCESSING_FAILED']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Error(Contract):
    code: str
    message: str
    requestId: Identifier
    details: dict = Field(default_factory=dict)


class Health(Contract):
    status: Literal['AVAILABLE']
    apiVersion: str
    rulesetVersion: str


class UploadResponse(Contract):
    workbookId: Identifier
    versionId: Identifier
    auditId: Identifier
    status: Literal['PROCESSING']


class WorkbookVersion(Contract):
    workbookId: Identifier
    versionId: Identifier
    fileName: str = Field(min_length=1, max_length=255)
    sha256: SHA256
    createdAt: Timestamp
    status: VersionStatus
    latestAuditId: Identifier | None = None
    sourceVersionId: Identifier | None = None


class Finding(Contract):
    findingId: Identifier
    ruleId: str = Field(min_length=1)
    category: Literal['NON_TEXT_CONTENT', 'TABLE_STRUCTURE', 'MERGED_CELLS', 'WORKSHEET_NAME', 'LINK_TEXT', 'COLOR_OR_CONTRAST']
    worksheet: str
    target: str
    classification: Literal['AUTOMATICALLY_REMEDIABLE', 'REQUIRES_USER_INPUT', 'MANUAL_REVIEW']
    message: str = Field(min_length=1, max_length=500)
    recommendation: str = Field(min_length=1, max_length=500)


class Audit(Contract):
    auditId: Identifier
    workbookId: Identifier
    versionId: Identifier
    rulesetVersion: str = Field(pattern=r'^\d+\.\d+\.\d+$')
    status: AuditStatus
    startedAt: Timestamp
    completedAt: Timestamp | None = None
    findings: list[Finding]
    limitations: list[str]
    error: Error | None = None


