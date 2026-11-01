"""Bounded cell/range coordinates for future partial WCAG 1.3.1 checks.

Shared infrastructure, not an accessibility rule or an HTTP validator.
"""

import re

from openpyxl.utils.cell import column_index_from_string, get_column_letter

MAX_ROW = 1048576
MAX_COLUMN = 16384


class CoordinateError(ValueError):
    """A stored/inferred coordinate is invalid, inconsistent or duplicated."""


def cell_position(reference: str) -> tuple[int, int]:
    """Return numeric (row, column), accepting case and zero-padded rows.

    Absolute and sheet-qualified addresses are not stored cell coordinates.
    """
    match = re.fullmatch(r"([A-Za-z]{1,3})([0-9]+)", reference)
    if match is None:
        raise CoordinateError(f"Invalid cell reference: {reference!r}")
    row_digits = match[2].lstrip("0") or "0"
    if len(row_digits) > 7:
        raise CoordinateError(f"Row outside Excel bounds: {reference!r}")
    row = int(row_digits)
    column = column_index_from_string(match[1].upper())
    cell_reference(row, column)
    return row, column


def cell_reference(row: int, column: int) -> str:
    if (
        type(row) is not int
        or type(column) is not int
        or not (1 <= row <= MAX_ROW and 1 <= column <= MAX_COLUMN)
    ):
        raise CoordinateError(f"Cell position outside Excel bounds: {row}, {column}")
    return f"{get_column_letter(column)}{row}"


def canonical_range(reference: str) -> str:
    """Return both endpoints, rejecting reversed or malformed rectangles."""
    bounds = reference.split(":")
    if len(bounds) == 1:
        bounds *= 2
    if len(bounds) != 2:
        raise CoordinateError(f"Invalid range: {reference!r}")
    first, last = (cell_position(bound) for bound in bounds)
    if first[0] > last[0] or first[1] > last[1]:
        raise CoordinateError(f"Reversed range: {reference!r}")
    return f"{cell_reference(*first)}:{cell_reference(*last)}"


def range_sort_key(reference: str) -> tuple[int, int, int, int]:
    first, last = canonical_range(reference).split(":")
    return (*cell_position(first), *cell_position(last))
