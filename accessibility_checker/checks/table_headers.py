"""1.3.1 Info and Relationships: Phase 4 formal table headers, partial scope.

The historical provisional detector remains in legacy_table_headers.py.
"""

from collections import Counter

from accessibility_checker import safe_xml
from accessibility_checker.cell_reader import WorkbookReader, _namespace, _part, _relationships
from accessibility_checker.coordinates import cell_reference, range_sort_key, canonical_range
from accessibility_checker.finding_ids import get_source_sha256, make_phase4_finding_id
from accessibility_checker.phase3_policy import UNICODE_WHITE_SPACE
from accessibility_checker.results import Findings, finalize_findings
from accessibility_checker.worksheet_features import contains, merge_ranges, overlaps, worksheet_features


def _labels(cells, rectangle):
    top, left, bottom, right = range_sort_key(rectangle)
    header = [c for c in cells if c.row == top and left <= c.column <= right]
    if len(header) != right - left + 1:
        return None
    if any(c.has_formula or c.rich_text or c.data_type not in {'s', 'inlineStr', 'str'}
           or not isinstance(c.value, str) or not c.value.strip(UNICODE_WHITE_SPACE)
           or len(c.value) > 255 for c in header):
        return None
    values = [c.value for c in sorted(header, key=lambda c: c.column)]
    keys = [value.strip(UNICODE_WHITE_SPACE).casefold() for value in values]
    return values if len(set(keys)) == len(keys) else None


def _record(result, source, sheet, target, reasons, safe=False):
    result.append({
        'findingId': make_phase4_finding_id(source, 'TABLE_HEADER', sheet.name, target),
        'ruleId': 'TABLE_HEADER', 'category': 'TABLE_STRUCTURE',
        'worksheet': sheet.name, 'target': target,
        'classification': 'REQUIRES_USER_INPUT' if safe else 'MANUAL_REVIEW',
        'message': 'Confirm the existing first row as the header.' if safe else 'Table header structure requires manual review.',
        'recommendation': 'Review the reported rectangle and its existing labels; no table or cells were changed.',
    })
    result.limitations.extend(f'{sheet.name}: {target}: {reason}' for reason in sorted(set(reasons)))


def _tables(reader):
    inventory = []
    for sheet in reader.sheets:
        if sheet.kind != 'worksheet' or sheet.external:
            continue
        features = worksheet_features(reader, sheet, {'tableParts'})
        if not features:
            continue
        relations = _relationships(reader._archive, sheet.part)
        parts = set()
        for container in features:
            ns = container.tag.split('}')[0] + '}'
            for item in container.findall(ns + 'tablePart'):
                ids = [v for k, v in item.attrib.items() if k in {
                    '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id',
                    '{http://purl.oclc.org/ooxml/officeDocument/relationships}id'}]
                if len(ids) != 1:
                    raise ValueError('Missing/ambiguous table relationship ID')
                relation = relations[ids[0]]
                if relation.get('TargetMode') == 'External' or not relation.attrib['Type'].endswith('/table'):
                    inventory.append((sheet, None, None, None))
                    continue
                part = _part(sheet.part, relation.attrib['Target'])
                if part in parts:
                    continue
                parts.add(part)
                root = safe_xml.fromstring(reader._archive.read(part))
                _namespace(root, 'table')
                inventory.append((sheet, part, root, canonical_range(root.attrib['ref'])))
    return inventory


def _feature_reasons(reader, sheet, rectangle, *, formal=False):
    reasons = []
    if sum(s.part == sheet.part for s in reader.sheets) != 1:
        reasons.append('Worksheet part has multiple owning sheets.')
    if any(overlaps(rectangle, merge) for merge in merge_ranges(reader, sheet)):
        reasons.append('Merged cells overlap the candidate.')
    # Features whose range/editor interaction is not proven safe are disclosed.
    for item in worksheet_features(reader, sheet, {'autoFilter', 'extLst', 'controls', 'oleObjects',
        'drawing', 'legacyDrawing', 'picture', 'conditionalFormatting', 'dataValidations', 'hyperlinks'}):
        kind = item.tag.rsplit('}', 1)[-1]
        if kind == 'autoFilter':
            if overlaps(rectangle, canonical_range(item.attrib['ref'])):
                reasons.append('Existing auto-filter overlaps the candidate.')
        elif kind in {'conditionalFormatting', 'dataValidations', 'hyperlinks'}:
            ns = item.tag.split('}')[0] + '}'
            refs = [item.get('sqref', '')] if kind == 'conditionalFormatting' else [
                child.get('sqref' if kind == 'dataValidations' else 'ref', '') for child in item
                if child.tag in {ns + 'dataValidation', ns + 'hyperlink'}]
            if any(overlaps(rectangle, canonical_range(ref)) for refs_ in refs for ref in refs_.split()):
                reasons.append(f'Attached {kind} requires preservation review.')
        else:
            reasons.append(f'Unsupported worksheet feature {kind} may affect header confirmation.')
    known = {'sheetPr', 'dimension', 'sheetViews', 'sheetFormatPr', 'cols', 'sheetCalcPr', 'sheetProtection', 'protectedRanges', 'scenarios', 'autoFilter', 'sortState', 'dataConsolidate', 'customSheetViews', 'mergeCells', 'phoneticPr', 'conditionalFormatting', 'dataValidations', 'hyperlinks', 'printOptions', 'pageMargins', 'pageSetup', 'headerFooter', 'rowBreaks', 'colBreaks', 'drawing', 'legacyDrawing', 'legacyDrawingHF', 'picture', 'oleObjects', 'controls', 'tableParts', 'extLst'}
    for item in worksheet_features(reader, sheet, None):
        namespace = item.tag.split('}')[0] + '}'
        if item.tag not in {namespace + name for name in known} or item.tag.endswith('}scenarios') or item.tag.endswith('}dataConsolidate'):
            reasons.append('Unrecognized or reference-bearing worksheet metadata requires preservation review.')
    return reasons


def _formal_tables(path, *, source_sha256=None):
    """Inspect referenced formal tables only; unstructured screening follows later."""
    source = source_sha256 if source_sha256 is not None else get_source_sha256(path)
    result = Findings()
    with WorkbookReader(path) as reader:
        inventory = _tables(reader)
        # IDs are workbook-wide; repeated owners of the same part are ownership,
        # not a second physical ID declaration.
        ids = Counter({part: root.get('id') for _, part, root, _ in inventory if part}.values())
        cells_by_part = {}
        for sheet, part, root, rectangle in inventory:
            if part is None:
                _record(result, source, sheet, sheet.part + '#xml=/', ['External/unsupported table relationships are not inspected or fetched.'])
                continue
            ns = root.tag.split('}')[0] + '}'
            identifier = root.get('id')
            valid_id = bool(identifier and identifier.isascii() and identifier.isdigit() and int(identifier) > 0 and ids[identifier] == 1)
            target = part + ('#tableId=' + identifier if valid_id else '#xml=/table[1]')
            if sheet.part not in cells_by_part:
                cells_by_part[sheet.part] = reader.read_cells(sheet)
            cells = cells_by_part[sheet.part]
            labels = _labels(cells, rectangle)
            columns = root.find(ns + 'tableColumns')
            names = [] if columns is None else [c.get('name') for c in columns.findall(ns + 'tableColumn')]
            top, left, bottom, right = range_sort_key(rectangle)
            metadata_ok = (len(names) == right - left + 1 and None not in names and columns is not None
                           and columns.get('count') == str(len(names))
                           and len({c.get('id') for c in columns}) == len(names)
                           and all(c.get('id', '').isascii() and c.get('id', '').isdigit() and int(c.get('id')) > 0 for c in columns))
            reasons = []
            if not valid_id:
                reasons.append('Table ID is missing, invalid or duplicated across table parts.')
            if sum(p == part for _, p, _, _ in inventory) > 1:
                reasons.append('Table part has multiple owning sheets.')
            conflict = any(s.part == sheet.part and p != part and r and overlaps(rectangle, r)
                           for s, p, _, r in inventory)
            if conflict:
                reasons.append('Formal table rectangles overlap.')
            merges = any(overlaps(rectangle, r) for r in merge_ranges(reader, sheet))
            count = root.get('headerRowCount', '1')
            if count == '1' and labels is not None and labels == names and metadata_ok and not merges and not conflict and valid_id:
                continue
            if count not in {'0', '1'}:
                reasons.append('Unsupported headerRowCount; only 0 and 1 are understood.')
            if labels is None or labels != names or not metadata_ok:
                reasons.append('Plain first-row labels and distinct column metadata do not match.')
            if merges:
                reasons.append('Merged cells overlap the table.')
            if count == '0':
                reasons.extend(_feature_reasons(reader, sheet, rectangle, formal=True))
                if right <= left or bottom <= top:
                    reasons.append('Header confirmation needs two columns and a remaining body row.')
                if root.get('totalsRowCount', '0') != '0' or root.get('totalsRowShown', '0') not in {'0', 'false'}:
                    reasons.append('Totals-row metadata makes enabling the header ambiguous.')
                if set(root.attrib) - {'id', 'name', 'displayName', 'ref', 'headerRowCount', 'totalsRowCount', 'totalsRowShown', 'comment', 'tableType', 'insertRow', 'insertRowShift', 'published', 'headerRowDxfId', 'headerRowBorderDxfId', 'dataDxfId', 'dataBorderDxfId', 'totalsRowDxfId', 'totalsRowBorderDxfId'}:
                    reasons.append('Unrecognized table attributes require header-operation review.')
                allowed = {'autoFilter', 'sortState', 'tableColumns', 'tableStyleInfo'}
                if any(name.startswith(('_xmlsignatures/', 'xl/embeddings/')) for name in reader._archive.namelist()):
                    reasons.append('Signed or opaque embedded package content prevents safe header confirmation.')
                if any(s.external for s in reader.sheets):
                    reasons.append('External sheet references cannot be checked for header dependencies.')
                if any(child.tag not in {ns + name for name in allowed} for child in root) or root.get('connectionId'):
                    reasons.append('Table query binding or extension is unsupported for enabling headers.')
                if any(c.get('queryTableFieldId') or c.find(ns + 'extLst') is not None or any(child.tag not in {ns + 'calculatedColumnFormula', ns + 'totalsRowFormula'} for child in c) for c in root.findall(ns + 'tableColumns/' + ns + 'tableColumn')):
                    reasons.append('Column query binding or extension is unsupported.')
                # A header operation can change structured-reference semantics anywhere.
                for other in reader.sheets:
                    if other.kind == 'worksheet' and not other.external:
                        for cell in reader.read_cells(other):
                            if cell.formula and '[' in (cell.formula.text or ''):
                                reasons.append('Structured formula references may depend on table headers.')
                # Defined names/chart/opaque references require a conservative proof.
                for name in reader._archive.namelist():
                    if name.endswith('.xml') and (name.startswith(('xl/charts/', 'xl/externalLinks/', 'xl/pivot', 'xl/query')) or name == reader.workbook_part):
                        xml = safe_xml.fromstring(reader._archive.read(name))
                        if any('[' in (e.text or '') for e in xml.iter()):
                            reasons.append('Non-cell structured references may depend on table headers.')
            _record(result, source, sheet, target, reasons, safe=count == '0' and not reasons)
    return finalize_findings(result)


def check_table_headers(path, *, source_sha256=None):
    """Inspect formal headers and sparse four-neighbor unstructured candidates."""
    source = source_sha256 if source_sha256 is not None else get_source_sha256(path)
    result = _formal_tables(path, source_sha256=source)
    excluded_small_component = False
    with WorkbookReader(path) as reader:
        inventory = _tables(reader)
        for sheet in reader.sheets:
            if sheet.kind != 'worksheet':
                continue
            if sheet.external:
                _record(result, source, sheet, reader.workbook_part + '#xml=/',
                        ['External worksheet table content is not fetched.'])
                continue
            rectangles = [rectangle for owner, part, root, rectangle in inventory
                          if owner == sheet and rectangle is not None]
            cells = reader.read_cells(sheet)
            remaining = {(c.row, c.column) for c in cells if c.populated and not any(
                contains(rectangle, c.row, c.column) for rectangle in rectangles)}
            while remaining:
                first = remaining.pop()
                component = {first}
                pending = [first]
                while pending:
                    row, column = pending.pop()
                    for adjacent in ((row-1, column), (row+1, column), (row, column-1), (row, column+1)):
                        if adjacent in remaining:
                            remaining.remove(adjacent)
                            component.add(adjacent)
                            pending.append(adjacent)
                top = min(r for r, c in component)
                bottom = max(r for r, c in component)
                left = min(c for r, c in component)
                right = max(c for r, c in component)
                if top == bottom or left == right:
                    excluded_small_component = True
                    continue
                rectangle = cell_reference(top, left) + ':' + cell_reference(bottom, right)
                reasons = _feature_reasons(reader, sheet, rectangle)
                if len(component) != (bottom-top+1)*(right-left+1):
                    reasons.append('The connected component is not a dense rectangle.')
                if _labels(cells, rectangle) is None:
                    reasons.append('The first row lacks distinct nonblank plain-string labels of at most 255 characters.')
                if any(overlaps(rectangle, other) for other in rectangles):
                    reasons.append('The candidate bounding rectangle overlaps a formal table.')
                if any(name.startswith(('_xmlsignatures/', 'xl/embeddings/')) for name in reader._archive.namelist()):
                    reasons.append('Signed or opaque embedded package content prevents safe table creation.')
                _record(result, source, sheet, sheet.part + '#range=' + rectangle, reasons, safe=not reasons)
    if excluded_small_component:
        result.limitations.append('TABLE_HEADER: Single cells, one-row regions and one-column lists are not inferred tables under this profile.')
    return finalize_findings(result)
