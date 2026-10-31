"""Reject DTDs, entities and external XML resources before OOXML inspection.

Used by partial 1.1.1 Non-text Content, 1.3.1 Info and Relationships and
2.4.2 Page Titled checks. OOXML external relationships are separate metadata;
they are never fetched and retain the existing manual-review policy.
"""

from xml.etree.ElementTree import Element  # Type used by existing checker annotations.

from defusedxml import ElementTree


def fromstring(text):
    return ElementTree.fromstring(text, forbid_dtd=True, forbid_entities=True, forbid_external=True)


def iterparse(source, events=None):
    return ElementTree.iterparse(
        source,
        events=events,
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    )
