"""Sparse OOXML input for future partial WCAG 1.3.1 Info and Relationships,
2.4.4 Link Purpose (In Context), 1.4.1 Use of Color and 1.4.3 Contrast (Minimum).

This module evaluates no accessibility rule. It preserves original values and
formula metadata, resolves text without phonetics and never saves a workbook.
"""

import posixpath
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from os import PathLike
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

from accessibility_checker import safe_xml
from accessibility_checker.coordinates import (
    MAX_ROW,
    CoordinateError,
    cell_position,
    cell_reference,
)
from accessibility_checker.excel_metadata import sheet_attributes
from accessibility_checker.phase3_policy import UNICODE_WHITE_SPACE

MAIN_NAMESPACES = {
    "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "http://purl.oclc.org/ooxml/spreadsheetml/main",
}


class WorkbookReadError(ValueError):
    """Required workbook metadata or cell content cannot be interpreted."""


@dataclass(frozen=True)
class SheetInfo:
    name: str
    sheet_id: str
    kind: str
    state: str
    part: str | None
    relationship_id: str
    relationship_target: str
    external: bool


@dataclass(frozen=True)
class Formula:
    text: str | None
    attributes: dict[str, str]


@dataclass(frozen=True)
class CellData:
    reference: str
    row: int
    column: int
    data_type: str
    value: str | Decimal | bool | None
    raw_value: str | None
    formula: Formula | None
    style_id: str | None
    rich_text: bool = False

    @property
    def has_formula(self) -> bool:
        return self.formula is not None

    @property
    def has_cached_value(self) -> bool:
        """Whether a formula has a stored v element, including an empty one."""
        return self.has_formula and self.raw_value is not None

    @property
    def cached_value(self):
        return self.value if self.has_formula else None

    @property
    def intake_nonempty(self) -> bool:
        return (
            self.has_formula
            or self.raw_value not in (None, "")
            or (self.data_type == "inlineStr" and self.value not in (None, ""))
        )

    @property
    def populated(self) -> bool:
        if self.has_formula:
            return True
        if isinstance(self.value, str):
            return bool(self.value.strip(UNICODE_WHITE_SPACE))
        return self.value is not None


def _namespace(element, local):
    for namespace in MAIN_NAMESPACES:
        if element.tag == f"{{{namespace}}}{local}":
            return namespace
    raise WorkbookReadError(f"Unsupported {local} namespace: {element.tag!r}")


def _body_text(element, namespace):
    # Text.content in openpyxl groups plain text before rich runs, whereas this
    # contract requires document order. Never descend into rPh/phoneticPr/extLst.
    fragments = []
    for child in element:
        if child.tag == f"{{{namespace}}}t":
            fragments.append(child.text or "")
        elif child.tag == f"{{{namespace}}}r":
            for text in child:
                if text.tag == f"{{{namespace}}}t":
                    fragments.append(text.text or "")
                elif text.tag != f"{{{namespace}}}rPr":
                    raise WorkbookReadError(
                        f"Unsupported rich-text run child: {text.tag}"
                    )
        elif child.tag not in {
            f"{{{namespace}}}rPh",
            f"{{{namespace}}}phoneticPr",
        }:
            raise WorkbookReadError(f"Unsupported string representation: {child.tag}")
    return "".join(fragments)


def _part(base, target):
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise WorkbookReadError(f"Not an internal package target: {target!r}")
    path = unquote(parsed.path)
    if "\\" in path or "\x00" in path:
        raise WorkbookReadError("Unsafe package target")
    resolved = posixpath.normpath(
        path.lstrip("/")
        if path.startswith("/")
        else posixpath.join(posixpath.dirname(base), path)
    )
    if not path or resolved in (".", "..") or resolved.startswith("../"):
        raise WorkbookReadError("Package target escapes its archive")
    return resolved


def _relationships(archive, part):
    directory, name = posixpath.split(part)
    path = f"{directory + '/' if directory else ''}_rels/{name}.rels"
    root = safe_xml.fromstring(archive.read(path))
    relations = {}
    for item in root:
        identifier = item.attrib["Id"]
        if identifier in relations:
            raise WorkbookReadError(f"Duplicate relationship ID: {identifier}")
        relations[identifier] = item
    return relations


class WorkbookReader:
    """Context-managed sparse reader; chartsheets are inventoried, not grids."""

    def __init__(self, path: str | PathLike[str]):
        self.path = path
        self._archive = None

    def __enter__(self):
        self._archive = ZipFile(self.path, "r")
        try:
            self._read_inventory()
        except BaseException:
            self._archive.close()
            self._archive = None
            raise
        return self

    def __exit__(self, *args):
        self._archive.close()
        self._archive = None

    def _read_inventory(self):
        root_rels = _relationships(self._archive, "")
        office = [
            r
            for r in root_rels.values()
            if r.attrib["Type"].endswith("/officeDocument")
        ]
        if len(office) != 1 or office[0].get("TargetMode") == "External":
            raise WorkbookReadError(
                "A unique internal workbook relationship is required"
            )
        self.workbook_part = _part("", office[0].attrib["Target"])
        root = safe_xml.fromstring(self._archive.read(self.workbook_part))
        namespace = _namespace(root, "workbook")
        relations = _relationships(self._archive, self.workbook_part)
        sheets = []
        for sheet in root.findall(f"{{{namespace}}}sheets/{{{namespace}}}sheet"):
            attributes = sheet_attributes(sheet)
            identifiers = [v for k, v in attributes.items() if k.endswith("}id")]
            if len(identifiers) != 1:
                raise WorkbookReadError("Missing or ambiguous sheet relationship ID")
            identifier = identifiers[0]
            relationship = relations[identifier]
            kind = relationship.attrib["Type"].rsplit("/", 1)[-1]
            if kind not in ("worksheet", "chartsheet"):
                raise WorkbookReadError(f"Unsupported sheet kind: {kind}")
            external = relationship.get("TargetMode") == "External"
            target = relationship.attrib["Target"]
            sheets.append(
                SheetInfo(
                    attributes["name"],
                    attributes["sheetId"],
                    kind,
                    attributes.get("state", "visible"),
                    None if external else _part(self.workbook_part, target),
                    identifier,
                    target,
                    external,
                )
            )
        self.sheets = tuple(sheets)
        strings = [
            r for r in relations.values() if r.attrib["Type"].endswith("/sharedStrings")
        ]
        if len(strings) > 1:
            raise WorkbookReadError("Ambiguous shared strings relationship")
        self._strings_relationship = strings[0] if strings else None
        self._strings = None

    def _shared_strings(self):
        if self._strings is None:
            rel = self._strings_relationship
            if rel is None:
                raise WorkbookReadError(
                    "Shared string cell has no shared strings relationship"
                )
            if rel.get("TargetMode") == "External":
                raise WorkbookReadError("External shared strings are not fetched")
            part = _part(self.workbook_part, rel.attrib["Target"])
            strings = []
            # Parse incrementally; retain resolved strings, not the XML tree.
            with self._archive.open(part) as stream:
                stack = []
                namespace = None
                for event, element in safe_xml.iterparse(stream, ("start", "end")):
                    if event == "start":
                        if not stack:
                            namespace = _namespace(element, "sst")
                        stack.append(element)
                    else:
                        if len(stack) == 2 and element.tag == f"{{{namespace}}}si":
                            strings.append((_body_text(element, namespace), element.find(f"{{{namespace}}}r") is not None))
                            stack[0].remove(element)
                            element.clear()
                        stack.pop()
            self._strings = strings
        return self._strings

    def _cell(self, element, namespace, row, previous_column):
        reference = element.get("r")
        if reference is None:
            column = previous_column + 1
            reference = cell_reference(row, column)
        else:
            actual_row, column = cell_position(reference)
            if actual_row != row:
                raise CoordinateError(f"Cell {reference!r} disagrees with row {row}")
            reference = cell_reference(row, column)
        values = element.findall(f"{{{namespace}}}v")
        formulas = element.findall(f"{{{namespace}}}f")
        inline = element.findall(f"{{{namespace}}}is")
        if len(values) > 1 or len(formulas) > 1 or len(inline) > 1:
            raise WorkbookReadError(f"Ambiguous cell content: {reference}")
        rich_text = False
        raw = (values[0].text or "") if values else None
        kind = element.get("t", "n")
        if kind == "s" and formulas and raw in (None, ""):
            value = None  # No saved index/cache: never calculate or invent one.
        elif kind == "s":
            if raw is None or re.fullmatch(r"[0-9]+", raw) is None:
                raise WorkbookReadError(f"Invalid shared string index: {reference}")
            strings = self._shared_strings()
            digits = raw.lstrip("0") or "0"
            if len(digits) > len(str(len(strings))):
                raise WorkbookReadError(
                    f"Shared string index out of bounds: {reference}"
                )
            index = int(digits)
            if index >= len(strings):
                raise WorkbookReadError(
                    f"Shared string index out of bounds: {reference}"
                )
            value, rich_text = strings[index]
        elif kind == "inlineStr":
            value = _body_text(inline[0], namespace) if inline else None
            rich_text = bool(inline and inline[0].find(f"{{{namespace}}}r") is not None)
        elif kind == "b":
            if raw not in (None, "", "0", "1", "false", "true"):
                raise WorkbookReadError(f"Invalid boolean: {reference}")
            value = None if raw in (None, "") else raw in ("1", "true")
        elif kind == "n":
            try:
                value = None if raw in (None, "") else Decimal(raw)
                if value is not None and not value.is_finite():
                    raise InvalidOperation
            except InvalidOperation as error:
                raise WorkbookReadError(
                    f"Invalid numeric value: {reference}"
                ) from error
        elif kind in ("str", "e", "d"):
            value = raw
        else:
            raise WorkbookReadError(f"Unsupported cell type {kind!r}: {reference}")
        formula = (
            Formula(formulas[0].text, dict(formulas[0].attrib)) if formulas else None
        )
        return CellData(
            reference, row, column, kind, value, raw, formula, element.get("s"), rich_text
        )

    def read_cells(self, sheet: SheetInfo) -> tuple[CellData, ...]:
        """Read only stored cells, returned in numeric row/column order.

        External sheets and chartsheets are explicit non-grid cases, not empty
        successful worksheet inspections. Formula caches are never calculated.
        """
        if self._archive is None:
            raise WorkbookReadError("WorkbookReader must be used inside a with block")
        if sheet.external or sheet.kind != "worksheet":
            raise WorkbookReadError(
                "External sheets/chartsheets cannot supply worksheet cells"
            )
        cells = {}
        rows = set()
        previous_row = 0
        current_row = None
        previous_column = 0
        cell_depth = None
        stack = []
        namespace = None
        sheet_data_seen = False
        with self._archive.open(sheet.part) as stream:
            for event, element in safe_xml.iterparse(stream, ("start", "end")):
                if event == "start":
                    if not stack:
                        namespace = _namespace(element, "worksheet")
                    if element.tag == f"{{{namespace}}}sheetData":
                        if len(stack) != 1 or sheet_data_seen:
                            raise WorkbookReadError("Duplicate or misplaced sheetData")
                        sheet_data_seen = True
                    if element.tag == f"{{{namespace}}}row":
                        if (
                            len(stack) != 2
                            or stack[-1].tag != f"{{{namespace}}}sheetData"
                        ):
                            raise CoordinateError("Row outside worksheet sheetData")
                        raw_row = element.get("r")
                        if (
                            raw_row is not None
                            and re.fullmatch(r"[0-9]+", raw_row) is None
                        ):
                            raise CoordinateError(f"Invalid row: {raw_row!r}")
                        digits = (
                            (raw_row.lstrip("0") or "0")
                            if raw_row is not None
                            else None
                        )
                        if digits is not None and len(digits) > 7:
                            raise CoordinateError("Row outside Excel bounds")
                        current_row = (
                            previous_row + 1 if digits is None else int(digits)
                        )
                        if not 1 <= current_row <= MAX_ROW or current_row in rows:
                            raise CoordinateError(
                                f"Invalid or duplicate row: {current_row}"
                            )
                        rows.add(current_row)
                        previous_row = current_row
                        previous_column = 0
                    if element.tag == f"{{{namespace}}}c":
                        if (
                            len(stack) != 3
                            or stack[-1].tag != f"{{{namespace}}}row"
                            or current_row is None
                        ):
                            raise CoordinateError("Cell without a stored row")
                        cell_depth = len(stack) + 1
                    stack.append(element)
                    continue
                if cell_depth == len(stack):
                    cell = self._cell(element, namespace, current_row, previous_column)
                    key = (cell.row, cell.column)
                    if key in cells:
                        raise CoordinateError(
                            f"Duplicate cell address: {cell.reference}"
                        )
                    cells[key] = cell
                    previous_column = cell.column
                    cell_depth = None
                if element.tag == f"{{{namespace}}}row":
                    current_row = None
                stack.pop()
                if cell_depth is None:
                    if stack:
                        stack[-1].remove(element)
                    element.clear()
        return tuple(cells[key] for key in sorted(cells))
