"""Temporary IDs for 1.1.1 Non-text Content and 2.4.2 Page Titled findings."""

import hashlib
import json


def make_finding_id(rule_id: str, worksheet: str, target: str) -> str:
    """Return a repeatable 64-character ID for the current local prototype."""
    # TODO: Replace with the agreed workbook/ruleset-aware identity policy.
    # Identical rule/sheet/target values in different workbooks currently collide.
    identity = json.dumps([rule_id, worksheet, target], ensure_ascii=False)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
