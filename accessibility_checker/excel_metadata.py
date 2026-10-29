"""Read parsed OOXML using openpyxl models with lossless legacy fallbacks.

Partial 2.4.2 Page Titled (related 2.4.6 Headings and Labels) and
1.3.1 Info and Relationships only. No workbook loading, XML parsing, or saving
occurs here. Raw package locations and lexical values remain authoritative.
"""

from openpyxl.packaging.core import DocumentProperties
from openpyxl.packaging.workbook import ChildSheet
from openpyxl.worksheet.table import Table


def _model(model_type, element):
    try:
        return model_type.from_tree(element)
    except (TypeError, ValueError, OverflowError):
        # Model validation is stricter than our existing checks, including for
        # minimal fixtures and unsupported Excel features. It is not evidence
        # that a workbook is invalid. Inspect the same original XML instead.
        return None


def sheet_attributes(element):
    """Interpret name/state with ChildSheet; retain raw IDs and unknown fields."""
    attributes = dict(element.attrib)
    model = _model(ChildSheet, element)
    if model is not None:
        for key in ("name", "state"):
            if key in attributes:
                attributes[key] = getattr(model, key)
    return attributes


def workbook_title(properties):
    """Use core properties without changing first-title or raw-text semantics."""
    titles = properties.findall("{http://purl.org/dc/elements/1.1/}title")
    model = _model(DocumentProperties, properties)
    # Serialisable.from_tree matches child local names; a foreign namespace
    # must not supply or replace the Dublin Core title used by our rule.
    local_titles = [
        child for child in properties if child.tag.rsplit("}", 1)[-1] == "title"
    ]
    if model is not None and len(titles) <= 1 and local_titles == titles:
        return model.title
    return titles[0].text if titles else None


def table_header(table):
    """Return (header count, range), preserving the original lexical rule.

    openpyxl handles omitted header counts as 1. The current rule specifically
    requires the literal attribute '0', so '00', '+0' and ' 0' stay excluded.
    A model's range normalization must not change an existing finding target.
    """
    model = _model(Table, table)
    raw_count = table.get("headerRowCount")
    if (
        model is not None
        and (raw_count is None or raw_count == str(model.headerRowCount))
        and table.get("ref") == model.ref
    ):
        return str(model.headerRowCount), model.ref
    return raw_count, table.get("ref")
