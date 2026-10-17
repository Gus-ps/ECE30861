"""Temporary IDs for partial WCAG 2.1 checks.

1.1.1 Non-text Content, 1.3.1 Info and Relationships, and 2.4.2 Page Titled.
"""

import hashlib
import json


def make_finding_id(rule_id: str, worksheet: str, target: str) -> str:
    """Return a repeatable 64-character ID for the current local prototype."""
    # TODO: Replace with the agreed workbook/ruleset-aware identity policy.
    # Identical rule/sheet/target values in different workbooks currently collide.
    identity = json.dumps([rule_id, worksheet, target], ensure_ascii=False)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
