"""Phase 3 IDs and retained legacy IDs for partial WCAG 2.1 checks.

1.1.1 Non-text Content, 1.3.1 Info and Relationships, and 2.4.2 Page Titled.
"""

import hashlib
import json
from os import PathLike
from pathlib import Path


RULESET_VERSION = "1.0.0"


def get_source_sha256(path: str | PathLike[str]) -> str:
    """Hash the original workbook bytes, without rewriting or normalizing them."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_phase3_finding_id(
    source_sha256: str, rule_id: str, worksheet: str, target: str
) -> str:
    """Apply the exact compact JSON identity recipe from the guide, Section 5."""
    identity = json.dumps(
        [source_sha256, RULESET_VERSION, rule_id, worksheet, target],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def make_finding_id(rule_id: str, worksheet: str, target: str) -> str:
    """Retain the old ID policy for inactive Title/Table checkers only."""
    # TODO: Replace with the agreed workbook/ruleset-aware identity policy.
    # Identical rule/sheet/target values in different workbooks currently collide.
    identity = json.dumps([rule_id, worksheet, target], ensure_ascii=False)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
