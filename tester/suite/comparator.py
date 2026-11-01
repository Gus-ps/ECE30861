"""Independent workbook comparator for Phase 4 outputs (shared specification §11, §8.3-8.6).

compare(source, output, changes, declared_sha256) returns every unexplained difference
between a source package and a remediated output, as human-readable strings; an empty
list means the output preserves the source except for exactly the approved changes.

- Package level: entry path sets, SHA256 of every decompressed entry, the output's
  declared hash against its downloaded bytes, and bounded, DTD-free reading.
- Part level: an entry no approved change touches must be byte-identical. An entry a
  change touches is compared semantically (elements, attributes, text, comments,
  processing instructions and namespace declarations) with the tester's own
  application of the change to the source part.

The expected edits are modelled here, never taken from the system's editor or
comparator. ZIP serialization (compression, timestamps, order, offsets) may differ.
"""

import copy
import hashlib
import io
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from xml.parsers import expat

MAX_ENTRIES, MAX_PACKAGE_BYTES, MAX_PART_BYTES = 10_000, 200 * 2 ** 20, 50 * 2 ** 20
TABLE_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"
CONTENT_TYPES = "{http://schemas.openxmlformats.org/package/2006/content-types}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
FAMILIES = {
    ##  spreadsheet main namespace -> officeDocument relationships namespace
    "http://schemas.openxmlformats.org/spreadsheetml/2006/main":
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "http://purl.oclc.org/ooxml/spreadsheetml/main": "http://purl.oclc.org/ooxml/officeDocument/relationships",
}
FORMULA_ELEMENTS = {"f", "formula", "formula1", "formula2", "calculatedColumnFormula", "totalsRowFormula"}
REFERENCE_PARTS = ("xl/worksheets/", "xl/chartsheets/", "xl/charts/", "xl/tables/")


class ChangeError(ValueError):
    ##  An approved change that cannot be located unambiguously in the source package.
    pass


##  ---- Approved changes (one per APPLY decision; targets as in spec §7.1) ----

@dataclass(frozen=True)
class AltText:
    drawing: str
    object_id: str
    title: str
    description: str


@dataclass(frozen=True)
class Rename:
    sheet_id: str
    name: str


@dataclass(frozen=True)
class LinkLabel:
    worksheet: str
    cell: str
    text: str


@dataclass(frozen=True)
class HeaderRow:
    ##  An unstructured candidate: a new table over exactly this range.
    worksheet: str
    range: str


@dataclass(frozen=True)
class EnableHeader:
    ##  An existing formal table whose header row is switched on.
    table: str


def change_from_decision(target, value):
    ##  The approved change for an APPLY decision on a finding target.
    part, _, locator = target.partition("#")
    kind, _, key = locator.partition("=")
    if kind == "id" and "title" in value:
        return AltText(part, key, value["title"], value["description"])
    if kind == "sheetId" and "name" in value:
        return Rename(key, value["name"])
    if kind == "cell" and "text" in value:
        return LinkLabel(part, key, value["text"])
    if kind == "range" and "headerRow" in value:
        return HeaderRow(part, key)
    if kind == "tableId" and "headerRow" in value:
        return EnableHeader(part)
    raise ChangeError(f"no supported correction for target {target}")


##  ---- Reading packages ----

def _unsafe(name):
    return name.startswith("/") or "\\" in name or ".." in name.split("/")


def read_package(data, label):
    ##  ({entry name: decompressed bytes}, problems); entries are None if the package is unusable.
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None, [f"the {label} is not a readable ZIP package"]
    infos = archive.infolist()
    names = [info.filename for info in infos]
    problems = []
    if len(infos) > MAX_ENTRIES:
        return None, [f"the {label} has {len(infos)} entries (limit {MAX_ENTRIES})"]
    if len(set(names)) != len(names):
        problems.append(f"the {label} repeats an entry name")
    problems += [f"the {label} entry {name!r} has an unsafe name" for name in names if _unsafe(name)]
    if any(info.flag_bits & 1 for info in infos):
        problems.append(f"the {label} has encrypted entries")
    if problems:
        return None, problems
    entries, total = {}, 0
    for info in infos:
        if info.is_dir():
            continue
        chunks, size = [], 0
        try:
            with archive.open(info) as stream:
                while chunk := stream.read(1 << 16):
                    size += len(chunk)
                    total += len(chunk)
                    if size > MAX_PART_BYTES or total > MAX_PACKAGE_BYTES:
                        return None, [f"the {label} expands beyond the comparator's size limits at {info.filename}"]
                    chunks.append(chunk)
        except (zipfile.BadZipFile, OSError, NotImplementedError) as error:
            return None, [f"the {label} entry {info.filename} cannot be read ({type(error).__name__})"]
        entries[info.filename] = b"".join(chunks)
    return entries, []


def _is_xml(name):
    return name.endswith((".xml", ".rels", ".vml")) or name == "[Content_Types].xml"


class _DoctypeFound(Exception):
    pass


def _refuse_doctype(*_args):
    raise _DoctypeFound


def _parse(data, where):
    ##  Package XML never needs a DTD. A plain expat pass refuses one in any encoding (which also
    ##  rules out entity expansion) before the tree is built.
    checker = expat.ParserCreate()
    checker.StartDoctypeDeclHandler = _refuse_doctype
    try:
        checker.Parse(data, True)
    except _DoctypeFound:
        raise ChangeError(f"{where} declares a DTD") from None
    except expat.ExpatError as error:
        raise ChangeError(f"{where} is not well-formed XML ({expat.ErrorString(error.code)})") from None
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    return ET.fromstring(data, parser=parser)


def _namespaces(data):
    return {pair for _, pair in ET.iterparse(io.BytesIO(data), events=("start-ns",))}


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _ns(tag):
    return tag[1:].split("}", 1)[0] if isinstance(tag, str) and tag.startswith("{") else ""


##  ---- Canonical XML ----
##  Expanded names, sorted attributes, comments and PIs kept, whitespace-only text dropped
##  except inside <t> text elements; xml:space on <t> is ignored (it only governs whitespace).

def _canon(element):
    if element.tag is ET.Comment:
        return ("#comment", element.text or "", (), "", ())
    if element.tag is ET.ProcessingInstruction:
        return ("#pi", element.text or "", (), "", ())
    keep = _local(element.tag) == "t"
    attrs = tuple(sorted((k, v) for k, v in element.attrib.items() if not (keep and k == XML_SPACE)))
    text = element.text or ""
    if not keep and not text.strip():
        text = ""
    children = []
    for child in element:
        tail = child.tail or ""
        children.append(_canon(child) + ((tail if tail.strip() else ""),))
    return (element.tag, "", attrs, text, tuple(children))


def _difference(expected, actual, path="", position=1):
    ##  A short description of the first place two canonical trees differ, located by an
    ##  indexed path (1-based among same-named siblings).
    tag = expected[0]
    here = f"{path}/{_local(tag) if not tag.startswith('#') else tag}" + (f"[{position}]" if path else "")
    if expected[0] != actual[0]:
        return f"{path or '/'}: expected <{_local(expected[0])}>, found <{_local(actual[0])}>"
    if expected[1] != actual[1]:
        return f"{here}: comment or instruction text differs"
    if expected[2] != actual[2]:
        e, a = dict(expected[2]), dict(actual[2])
        for key in sorted(set(e) | set(a)):
            if e.get(key) != a.get(key):
                return f"{here}: attribute {_local(key)} is {a.get(key)!r}, expected {e.get(key)!r}"
    if expected[3] != actual[3]:
        return f"{here}: text is {actual[3]!r}, expected {expected[3]!r}"
    for index, (e, a) in enumerate(zip(expected[4], actual[4])):
        if e != a:
            if e[:5] == a[:5]:
                return f"{here}: text after child {index + 1} differs"
            position = 1 + sum(1 for earlier in expected[4][:index] if earlier[0] == e[0])
            return _difference(e[:5], a[:5], here, position)
    if len(expected[4]) != len(actual[4]):
        return f"{here}: has {len(actual[4])} child nodes, expected {len(expected[4])}"
    return f"{here}: differs"


##  ---- Formula sheet references (independent tokenizer) ----

OPERATORS = set(" \t\r\n!'\"(),;:=+-*/^&<>%{}[]#@")


def quote_sheet(name):
    return "'" + name.replace("'", "''") + "'"


def rewrite_sheet_references(formula, old, new):
    ##  Replace references to sheet `old` (case-insensitive) with the quoted new name. String
    ##  literals, external ([n]Sheet!) references, similar names and plain text are untouched.
    out, i, n, target = [], 0, len(formula), old.casefold()
    while i < n:
        ch = formula[i]
        if ch == '"':
            j = i + 1
            while j < n and not (formula[j] == '"' and formula[j + 1:j + 2] != '"'):
                j += 2 if formula[j] == '"' else 1
            out.append(formula[i:j + 1])
            i = j + 1
        elif ch == "'":
            j, name = i + 1, []
            while j < n:
                if formula[j] == "'":
                    if formula[j + 1:j + 2] == "'":
                        name.append("'")
                        j += 2
                        continue
                    break
                name.append(formula[j])
                j += 1
            token, i = formula[i:j + 1], j + 1
            sheet = "".join(name)
            refers = formula[i:i + 1] == "!" and not sheet.startswith("[") and sheet.casefold() == target
            out.append(quote_sheet(new) if refers else token)
        elif ch not in OPERATORS:
            j = i
            while j < n and formula[j] not in OPERATORS:
                j += 1
            word, before = formula[i:j], formula[i - 1:i]
            refers = formula[j:j + 1] == "!" and before not in ("]", "#") and word.casefold() == target
            out.append(quote_sheet(new) if refers else word)
            i = j
        else:
            out.append(ch)
            i += 1
    return "".join(out)


##  ---- Planning: what each approved change does to which part ----

def _rels_path(part):
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


def _relationships(entries, part):
    ##  {Id: (type, resolved target, target mode)} for a part's relationships.
    path = _rels_path(part)
    if path not in entries:
        return {}
    out = {}
    for rel in _parse(entries[path], path).iter(f"{PKG_REL}Relationship"):
        target, mode = rel.get("Target", ""), rel.get("TargetMode", "Internal")
        if mode != "External":
            target = target[1:] if target.startswith("/") else posixpath.normpath(
                posixpath.join(posixpath.dirname(part), target))
        out[rel.get("Id")] = (rel.get("Type", ""), target, mode)
    return out


def _column_number(letters):
    number = 0
    for letter in letters:
        number = number * 26 + ord(letter.upper()) - 64
    return number


def _cell_ref(column, row):
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row}"


class Plan:
    def __init__(self, entries, changes):
        self.entries = entries
        root_rels = _relationships(entries, "")
        self.workbook = next((t for kind, t, _ in root_rels.values() if kind.endswith("/officeDocument")), None)
        if self.workbook not in entries:
            raise ChangeError("the source package has no workbook part")
        workbook = _parse(entries[self.workbook], self.workbook)
        self.main = _ns(workbook.tag)
        if self.main not in FAMILIES:
            raise ChangeError(f"the source workbook namespace {self.main} is not SpreadsheetML")
        self.rel_ns = FAMILIES[self.main]
        self.workbook_rels = _relationships(entries, self.workbook)
        self.sheets = {s.get("sheetId"): (s.get("name"), self.workbook_rels.get(s.get(f"{{{self.rel_ns}}}id"), ("", ""))[1])
                       for s in workbook.iter(f"{{{self.main}}}sheet")}
        self.transforms = {}            # part -> [function(root) -> [variant roots]]
        self.new_parts = {}             # part added by an approved change -> checker(bytes) -> problems
        self.table_parts = {}           # worksheet part -> rIds an approved change appends to tableParts
        self.rels_additions = {}        # rels path -> {Id: (type, target, mode)}
        self.content_type_additions = {}
        self.new_tables = {}            # new table part -> (table id, name, ref, header labels)
        self.descriptions = {}          # part -> [what the approved changes do there]
        self._allocated_tables, self._allocated_ids, self._allocated_names = set(), set(), set()
        for change in changes:
            getattr(self, f"_plan_{type(change).__name__}")(change)

    def _add(self, part, transform, description):
        if part not in self.entries:
            raise ChangeError(f"{part} named by an approved change is not in the source package")
        self.transforms.setdefault(part, []).append(transform)
        self.descriptions.setdefault(part, []).append(description)

    def _source(self, part):
        return _parse(self.entries[part], part)

    ##  -- alt text (§8.3) --
    def _plan_AltText(self, change):
        root = self._source(change.drawing) if change.drawing in self.entries else None
        matches = [p for p in root.iter() if _local(p.tag) == "cNvPr" and p.get("id") == change.object_id] \
            if root is not None else []
        if len(matches) != 1:
            raise ChangeError(f"{change.drawing}#id={change.object_id} does not identify exactly one object")

        def apply(root):
            props = next(p for p in root.iter() if _local(p.tag) == "cNvPr" and p.get("id") == change.object_id)
            props.set("title", change.title)
            props.set("descr", change.description)
            return [root]
        self._add(change.drawing, apply, f"alt text of object {change.object_id}")

    ##  -- worksheet rename (§8.4) --
    def _plan_Rename(self, change):
        if change.sheet_id not in self.sheets:
            raise ChangeError(f"no sheet has sheetId {change.sheet_id}")
        old = self.sheets[change.sheet_id][0]
        if change.name == old:
            raise ChangeError(f"sheet {old!r} is renamed to its own name")

        def workbook(root):
            for sheet in root.iter(f"{{{self.main}}}sheet"):
                if sheet.get("sheetId") == change.sheet_id:
                    sheet.set("name", change.name)
            for defined in root.iter(f"{{{self.main}}}definedName"):
                defined.text = rewrite_sheet_references(defined.text or "", old, change.name)
            return [root]

        def references(root):
            for element in root.iter():
                if _local(element.tag) in FORMULA_ELEMENTS and element.text:
                    element.text = rewrite_sheet_references(element.text, old, change.name)
                if _local(element.tag) == "hyperlink" and element.get("location"):
                    element.set("location", rewrite_sheet_references(element.get("location"), old, change.name))
            return [root]

        def app_titles(root):
            ##  docProps/app.xml lists sheet names; updating it is allowed but not required.
            renamed = copy.deepcopy(root)
            for item in renamed.iter():
                if _local(item.tag) == "lpstr" and item.text == old:
                    item.text = change.name
            return [root, renamed]

        what = f"rename of {old!r} to {change.name!r}"
        self._add(self.workbook, workbook, what)
        for part in self.entries:
            if part.startswith(REFERENCE_PARTS) and part.endswith(".xml"):
                self._add(part, references, f"sheet references rewritten for the {what}")
        if "docProps/app.xml" in self.entries:
            self._add("docProps/app.xml", app_titles, f"titles updated for the {what}")

    ##  -- hyperlink label (§8.5) --
    def _plan_LinkLabel(self, change):
        root = self._source(change.worksheet) if change.worksheet in self.entries else None
        if root is None or len([c for c in root.iter(f"{{{self.main}}}c") if c.get("r") == change.cell]) != 1:
            raise ChangeError(f"{change.worksheet}#cell={change.cell} does not identify exactly one cell")

        def apply(root):
            cell = next(c for c in root.iter(f"{{{self.main}}}c") if c.get("r") == change.cell)
            for child in [c for c in cell if _local(c.tag) in ("v", "is", "f")]:
                cell.remove(child)
            cell.set("t", "inlineStr")
            ET.SubElement(ET.SubElement(cell, f"{{{self.main}}}is"), f"{{{self.main}}}t").text = change.text
            variants = [root]
            for link in root.iter(f"{{{self.main}}}hyperlink"):
                if link.get("ref") == change.cell:
                    if link.get("display") is not None:
                        link.set("display", change.text)
                    else:
                        with_display = copy.deepcopy(root)
                        next(h for h in with_display.iter(f"{{{self.main}}}hyperlink")
                             if h.get("ref") == change.cell).set("display", change.text)
                        variants.append(with_display)
            return variants
        self._add(change.worksheet, apply, f"label of the link at {change.cell}")

    ##  -- existing table header (§8.6) --
    def _plan_EnableHeader(self, change):
        if change.table not in self.entries:
            raise ChangeError(f"{change.table} is not in the source package")

        def apply(root):
            implicit = copy.deepcopy(root)
            root.set("headerRowCount", "1")
            implicit.attrib.pop("headerRowCount", None)
            return [root, implicit]
        self._add(change.table, apply, "headerRowCount switched on")

    ##  -- new table over an unstructured candidate (§8.6) --
    def _plan_HeaderRow(self, change):
        sheet = change.worksheet
        if sheet not in self.entries:
            raise ChangeError(f"{sheet} is not in the source package")
        match = re.fullmatch(r"([A-Z]+)([0-9]+):([A-Z]+)([0-9]+)", change.range)
        if not match:
            raise ChangeError(f"{change.range} is not an A1:D9 range")
        first_col, first_row, last_col = _column_number(match[1]), int(match[2]), _column_number(match[3])
        labels = [self._cell_text(sheet, _cell_ref(col, first_row)) for col in range(first_col, last_col + 1)]
        if any(not label for label in labels):
            raise ChangeError(f"the first row of {sheet}#range={change.range} has a blank or non-string label")

        tables = [p for p in self.entries if re.fullmatch(r"xl/tables/table[0-9]+\.xml", p)]
        number = next(n for n in range(1, 10 ** 6)
                      if f"xl/tables/table{n}.xml" not in self.entries and n not in self._allocated_tables)
        self._allocated_tables.add(number)
        used_ids = {int(t.get("id")) for t in (self._source(p) for p in tables) if (t.get("id") or "").isdigit()}
        table_id = next(n for n in range(1, 10 ** 6) if n not in used_ids | self._allocated_ids)
        self._allocated_ids.add(table_id)
        taken = {name.casefold() for p in tables for t in [self._source(p)]
                 for name in (t.get("name"), t.get("displayName")) if name}
        taken |= {(d.get("name") or "").casefold() for d in self._source(self.workbook).iter(f"{{{self.main}}}definedName")}
        taken |= self._allocated_names
        base, suffix, name = f"A11yTable{table_id}", 0, f"A11yTable{table_id}"
        while name.casefold() in taken:
            suffix += 1
            name = f"{base}_{suffix}"
        self._allocated_names.add(name.casefold())

        table_part, rels = f"xl/tables/table{number}.xml", _rels_path(sheet)
        existing = {**_relationships(self.entries, sheet), **self.rels_additions.get(rels, {})}
        rid = next(f"rId{n}" for n in range(1, 10 ** 6) if f"rId{n}" not in existing)
        self.rels_additions.setdefault(rels, {})[rid] = (f"{self.rel_ns}/table", table_part, "Internal")
        self.content_type_additions[f"/{table_part}"] = TABLE_CONTENT_TYPE
        self.table_parts.setdefault(sheet, []).append(rid)
        self.descriptions.setdefault(sheet, []).append(f"tablePart {rid} for the new table over {change.range}")

        def check(data):
            return self._check_table(table_part, data, table_id, name, change.range, labels)
        self.new_parts[table_part] = check
        self.new_tables[table_part] = (table_id, name, change.range, labels)
        if rels not in self.entries:
            self.new_parts[rels] = lambda data: self._check_rels(rels, b"", data)

    def _cell_text(self, sheet, ref):
        cell = next((c for c in self._source(sheet).iter(f"{{{self.main}}}c") if c.get("r") == ref), None)
        if cell is None or any(_local(c.tag) == "f" for c in cell):
            return None
        kind = cell.get("t")
        if kind == "inlineStr":
            return "".join(t.text or "" for t in cell.iter(f"{{{self.main}}}t")).strip() or None
        if kind == "s":
            strings = next((t for k, t, _ in self.workbook_rels.values() if k.endswith("/sharedStrings")), None)
            items = list(self._source(strings).iter(f"{{{self.main}}}si")) if strings in self.entries else []
            index = int(cell.findtext(f"{{{self.main}}}v") or -1)
            if 0 <= index < len(items):
                return "".join(t.text or "" for t in items[index].iter(f"{{{self.main}}}t")).strip() or None
        return None

    ##  -- checks for structural additions --
    def _check_table(self, part, data, table_id, name, ref, labels):
        try:
            root = _parse(data, part)
        except ChangeError as error:
            return [str(error)]
        problems = []
        if root.tag != f"{{{self.main}}}table":
            return [f"{part}: root is <{_local(root.tag)}> in {_ns(root.tag)}, expected <table> in {self.main}"]
        expected = {"id": str(table_id), "displayName": name, "ref": ref}
        problems += [f"{part}: {key} is {root.get(key)!r}, expected {value!r}"
                     for key, value in expected.items() if root.get(key) != value]
        if root.get("name") not in (None, name):
            problems.append(f"{part}: name is {root.get('name')!r}, expected {name!r}")
        if root.get("headerRowCount") not in (None, "1"):
            problems.append(f"{part}: headerRowCount is {root.get('headerRowCount')}")
        if root.get("totalsRowCount") not in (None, "0"):
            problems.append(f"{part}: has a totals row")
        for unwanted in ("autoFilter", "tableStyleInfo", "sortState"):
            if root.find(f"{{{self.main}}}{unwanted}") is not None:
                problems.append(f"{part}: has <{unwanted}>, which the header operation does not add")
        columns = root.find(f"{{{self.main}}}tableColumns")
        names = [c.get("name") for c in columns] if columns is not None else []
        if names != labels:
            problems.append(f"{part}: table columns are {names}, expected the header labels {labels}")
        elif columns.get("count") not in (None, str(len(labels))):
            problems.append(f"{part}: tableColumns count is {columns.get('count')}")
        return problems

    def _check_rels(self, path, source, output):
        def relations(data):
            if not data:
                return set()          # a relationships part the header change creates
            return {(r.get("Id"), r.get("Type"), _resolve(path, r.get("Target", ""), r.get("TargetMode")),
                     r.get("TargetMode", "Internal")) for r in _parse(data, path).iter(f"{PKG_REL}Relationship")}
        expected = relations(source) | {(rid, kind, target, mode)
                                        for rid, (kind, target, mode) in self.rels_additions.get(path, {}).items()}
        actual = relations(output)
        return _set_problems(path, "relationship", expected, actual)

    def _check_content_types(self, source, output):
        def declarations(data):
            root = _parse(data, "[Content_Types].xml")
            return {(_local(e.tag), e.get("Extension") or e.get("PartName"), e.get("ContentType")) for e in root}
        expected = declarations(source) | {("Override", part, kind) for part, kind in self.content_type_additions.items()}
        return _set_problems("[Content_Types].xml", "declaration", expected, declarations(output))


def _resolve(rels_path, target, mode):
    if mode == "External":
        return target
    owner = posixpath.dirname(posixpath.dirname(rels_path))
    return target[1:] if target.startswith("/") else posixpath.normpath(posixpath.join(owner, target))


def _set_problems(part, noun, expected, actual):
    problems = [f"{part}: missing {noun} {item}" for item in sorted(expected - actual, key=str)]
    return problems + [f"{part}: unexpected {noun} {item}" for item in sorted(actual - expected, key=str)]


##  ---- Comparison ----

def _strip_table_parts(root, main):
    for parent in root.iter():
        for child in [c for c in parent if c.tag == f"{{{main}}}tableParts"]:
            parent.remove(child)
    return root


def _compare_part(plan, name, source, output):
    if name in plan.rels_additions:
        return plan._check_rels(name, source, output)
    if name == "[Content_Types].xml" and plan.content_type_additions:
        return plan._check_content_types(source, output)
    transforms = plan.transforms.get(name, [])
    adds_tables = name in plan.table_parts
    if not (transforms or adds_tables) or not _is_xml(name):
        return [] if source == output else [f"{name} changed, but no approved change touches it"]
    src_root = _parse(source, f"source {name}")
    variants = [src_root]
    for transform in transforms:
        variants = [result for variant in variants for result in transform(copy.deepcopy(variant))]
    if adds_tables:
        variants = [_strip_table_parts(v, plan.main) for v in variants]
    expected, unchanged_allowed = [_canon(v) for v in variants], not adds_tables and _canon(src_root)
    if unchanged_allowed and set(expected) == {unchanged_allowed}:
        return [] if source == output else [f"{name} changed, but the approved changes leave it as it was"]
    what = "; ".join(plan.descriptions.get(name, []))
    if source == output:
        ##  Acceptable only when leaving the part as it was is one of the allowed variants.
        if unchanged_allowed and unchanged_allowed in expected:
            return []
        return [f"{name} is unchanged, but an approved change requires an edit there ({what})"]
    try:
        out_root = _parse(output, f"output {name}")
    except ChangeError as error:
        return [str(error)]
    problems = []
    if _namespaces(source) - _namespaces(output):
        lost = sorted(_namespaces(source) - _namespaces(output))
        problems.append(f"{name}: namespace declarations {lost} were dropped or renamed")
    if adds_tables:
        found = [t.get(f"{{{plan.rel_ns}}}id") for t in out_root.iter(f"{{{plan.main}}}tablePart")]
        before = [t.get(f"{{{plan.rel_ns}}}id") for t in src_root.iter(f"{{{plan.main}}}tablePart")]
        wanted = before + plan.table_parts[name]
        if found != wanted:
            problems.append(f"{name}: tableParts references are {found}, expected {wanted}")
        count = next((t.get("count") for t in out_root.iter(f"{{{plan.main}}}tableParts")), None)
        if count not in (None, str(len(wanted))):
            problems.append(f"{name}: tableParts count is {count}, expected {len(wanted)}")
        out_root = _strip_table_parts(out_root, plan.main)
    actual = _canon(out_root)
    if actual not in expected:
        problems.append(f"{name}: {_difference(expected[0], actual)} (approved here: {what})")
    return problems


def compare(source, output, changes=(), declared_sha256=None):
    problems = []
    if declared_sha256 is not None and hashlib.sha256(output).hexdigest() != declared_sha256:
        problems.append(f"the output's declared sha256 {declared_sha256} does not match its downloaded bytes "
                        f"({hashlib.sha256(output).hexdigest()})")
    source_entries, source_problems = read_package(source, "source")
    output_entries, output_problems = read_package(output, "output")
    problems += source_problems + output_problems
    if source_entries is None or output_entries is None:
        return problems
    try:
        plan = Plan(source_entries, changes)
    except ChangeError as error:
        return problems + [f"approved change not locatable in the source: {error}"]
    for name in sorted(set(source_entries) - set(output_entries)):
        problems.append(f"{name} is missing from the output")
    for name in sorted(set(output_entries) - set(source_entries)):
        if name not in plan.new_parts:
            problems.append(f"{name} was added, but no approved change adds it")
    for name, check in sorted(plan.new_parts.items()):
        if name in output_entries:
            problems += check(output_entries[name])
        else:
            problems.append(f"{name}, required by an approved header change, is missing from the output")
    for name in sorted(set(source_entries) & set(output_entries)):
        try:
            problems += _compare_part(plan, name, source_entries[name], output_entries[name])
        except ChangeError as error:
            problems.append(str(error))
    return problems
