"""2.4.4 Link Purpose (In Context): finite hyperlink-label screening only."""

import re

from openpyxl.formula import Tokenizer
from openpyxl.formula.tokenizer import TokenizerError

from accessibility_checker import safe_xml
from accessibility_checker.cell_reader import WorkbookReader, _part, _relationships
from accessibility_checker.coordinates import canonical_range, range_sort_key, cell_reference
from accessibility_checker.finding_ids import get_source_sha256, make_phase4_finding_id
from accessibility_checker.phase3_policy import UNICODE_WHITE_SPACE
from accessibility_checker.results import Findings, finalize_findings
from accessibility_checker.worksheet_features import contains, indexed_paths, merge_ranges, overlaps, worksheet_features

WORDS = {'click here', 'here', 'link', 'more', 'read more', 'learn more', 'website', 'url'}
WS = '[' + re.escape(UNICODE_WHITE_SPACE) + ']+'
FUNCTION = re.compile(r'(?:_xlfn\.)?HYPERLINK\(', re.IGNORECASE | re.ASCII)


def normalized_label(value):
    return re.sub(WS, ' ', value.strip(UNICODE_WHITE_SPACE)).casefold()


def ambiguous_label(label, destination):
    value = normalized_label(label)
    if not value or value == normalized_label(destination):
        return True
    comparison = value[:-1] if value[-1:] in {'.', '!', '?'} else value
    return comparison in WORDS or value.startswith(('http://', 'https://', 'www.', 'mailto:'))


def literal_hyperlink(formula):
    """Return destination,label for the finite literal grammar, or None."""
    text = formula[1:] if formula.startswith('=') else formula
    match = re.fullmatch(r'\s*(?:_xlfn\.)?HYPERLINK\s*\((.*)\)\s*', text, re.IGNORECASE | re.ASCII | re.DOTALL)
    if not match:
        return None
    body = match[1]
    args = []
    position = 0
    while True:
        while position < len(body) and body[position] in UNICODE_WHITE_SPACE:
            position += 1
        if position >= len(body) or body[position] != '"':
            return None
        position += 1
        chars = []
        while position < len(body):
            char = body[position]
            position += 1
            if char == '"':
                if position < len(body) and body[position] == '"':
                    chars.append('"')
                    position += 1
                else:
                    break
            else:
                chars.append(char)
        else:
            return None
        args.append(''.join(chars))
        while position < len(body) and body[position] in UNICODE_WHITE_SPACE:
            position += 1
        if position == len(body):
            break
        if body[position] != ',' or len(args) >= 2:
            return None
        position += 1
    return (args[0], args[-1]) if 1 <= len(args) <= 2 else None


def _calls_hyperlink(text):
    text = text or ''
    try:
        return any(t.type == 'FUNC' and t.subtype == 'OPEN' and FUNCTION.fullmatch(t.value)
                   for t in Tokenizer(text if text.startswith('=') else '=' + text).items)
    except (TokenizerError, IndexError):
        # Strip text literals before conservative recognition of malformed calls.
        outside = re.sub(r'"(?:[^"]|"")*"', '""', text)
        return re.search(r'(?:_xlfn\.)?HYPERLINK\s*\(', outside, re.IGNORECASE | re.ASCII) is not None


def _record(result, source, sheet, target, reasons, safe=False):
    result.append({
        'findingId': make_phase4_finding_id(source, 'LINK_TEXT', sheet.name, target),
        'ruleId': 'LINK_TEXT', 'category': 'LINK_TEXT', 'worksheet': sheet.name,
        'target': target, 'classification': 'REQUIRES_USER_INPUT' if safe else 'MANUAL_REVIEW',
        'message': 'Hyperlink label requires review for descriptive link purpose.',
        'recommendation': 'Provide descriptive link text while preserving the destination; no link was changed.',
    })
    result.limitations.extend(f'{sheet.name}: {target}: {reason}' for reason in sorted(set(reasons)))


def check_link_text(path, *, source_sha256=None):
    source = source_sha256 if source_sha256 is not None else get_source_sha256(path)
    result = Findings()
    with WorkbookReader(path) as reader:
        for sheet in reader.sheets:
            if sheet.external:
                if sheet.kind == 'worksheet':
                    _record(result, source, sheet, reader.workbook_part + '#xml=/', ['External worksheet hyperlink content is not fetched.'])
                continue
            if sheet.kind != 'worksheet':
                _drawing_disclosures(reader, sheet, result)
                continue
            cells = reader.read_cells(sheet)
            by_address = {cell.reference: cell for cell in cells}
            formula_cells = {cell.reference: cell for cell in cells if cell.has_formula and _calls_hyperlink(cell.formula.text)}
            merges = merge_ranges(reader, sheet)
            declarations = []
            relationships = None
            # Direct-child occurrence indices count all same-local-name children.
            for feature, feature_path in worksheet_features(reader, sheet, None, with_paths=True):
                if feature.tag.rsplit('}', 1)[-1] != 'hyperlinks':
                    continue
                ns = feature.tag.split('}')[0] + '}'
                locations = indexed_paths(feature)
                for item in feature.findall(ns + 'hyperlink'):
                    rectangle = canonical_range(item.attrib['ref'])
                    target = sheet.part + '#xml=' + feature_path + locations[item][len('/hyperlinks[1]'):]
                    destination = item.get('location', '')
                    ids = [v for k, v in item.attrib.items() if k in {
                        '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id',
                        '{http://purl.oclc.org/ooxml/officeDocument/relationships}id'}]
                    if ids:
                        if len(ids) != 1:
                            raise ValueError('Ambiguous hyperlink relationship ID')
                        if relationships is None:
                            relationships = _relationships(reader._archive, sheet.part)
                        relation = relationships[ids[0]]
                        if not relation.attrib['Type'].endswith('/hyperlink'):
                            declarations.append((item, rectangle, target, '', ['Unsupported hyperlink relationship type.']))
                            continue
                        destination = relation.attrib['Target'] + ('#' + destination if destination else '')
                    declarations.append((item, rectangle, target, destination, []))
            for item, rectangle, fallback, destination, reasons_ in declarations:
                reasons = list(reasons_)
                top, left, bottom, right = range_sort_key(rectangle)
                address = cell_reference(top, left)
                cell = by_address.get(address)
                if (top, left) != (bottom, right):
                    reasons.append('Multi-cell hyperlink representation is unsupported.')
                if sum(overlaps(rectangle, other) for _, other, _, _, _ in declarations) > 1 or any(
                    contains(rectangle, c.row, c.column) for c in formula_cells.values()):
                    reasons.append('Competing hyperlink declarations affect this representation.')
                if sum(s.part == sheet.part for s in reader.sheets) > 1:
                    reasons.append('Worksheet part has multiple owning sheets.')
                if any(overlaps(rectangle, merge) for merge in merges):
                    reasons.append('Hyperlink intersects merged cells.')
                if cell and (cell.has_formula or cell.rich_text or cell.data_type not in {'s', 'str', 'inlineStr'}):
                    reasons.append('The label is not a simple editable text cell.')
                label = '' if cell is None or cell.value is None else str(cell.value)
                if reasons or ambiguous_label(label, destination):
                    target = fallback if reasons else sheet.part + '#cell=' + address
                    _record(result, source, sheet, target, reasons, safe=not reasons)
            for address, cell in formula_cells.items():
                parsed = literal_hyperlink(cell.formula.text or '')
                unsupported = cell.formula.attributes.get('t', 'normal') != 'normal' or any(contains(r, cell.row, cell.column) for _, r, _, _, _ in declarations)
                if not unsupported and parsed is not None and not ambiguous_label(parsed[1], parsed[0]):
                    continue
                target = sheet.part + '#cell=' + address
                reasons = ['Formula hyperlink text is not edited; its formula was not calculated.']
                if parsed is None or unsupported:
                    # Stored row/cell positions are needed, including omitted r.
                    target = _formula_location(reader, sheet, address)
                    reasons.append('Only one or two literal string HYPERLINK arguments are supported for screening.')
                _record(result, source, sheet, target, reasons)
            _drawing_disclosures(reader, sheet, result)
    return finalize_findings(result)


def _formula_location(reader, sheet, address):
    # Stream without retaining the grid; inferred addresses match the common reader.
    from accessibility_checker.coordinates import cell_position
    row = 0
    column = 0
    stack = []
    namespace = None
    with reader._archive.open(sheet.part) as stream:
        for event, element in safe_xml.iterparse(stream, ('start', 'end')):
            if event == 'start':
                local = element.tag.rsplit('}', 1)[-1]
                if not stack:
                    namespace = element.tag.split('}')[0] + '}'
                    location = '/' + local + '[1]'
                else:
                    parent, path, counts = stack[-1]
                    counts[local] = counts.get(local, 0) + 1
                    location = path + '/' + local + '[' + str(counts[local]) + ']'
                if element.tag == namespace + 'row' and len(stack) == 2:
                    row = int(element.get('r', str(row + 1)))
                    column = 0
                if element.tag == namespace + 'c' and len(stack) == 3:
                    column = cell_position(element.get('r'))[1] if element.get('r') else column + 1
                    if cell_reference(row, column) == address:
                        return sheet.part + '#xml=' + location
                stack.append((element, location, {}))
            else:
                stack.pop()
                if stack:
                    stack[-1][0].remove(element)
                element.clear()
    raise ValueError('Formula hyperlink cell location is missing')


def _drawing_disclosures(reader, sheet, result):
    features = worksheet_features(reader, sheet, {'drawing'})
    if not features:
        return
    relations = _relationships(reader._archive, sheet.part)
    for feature in features:
        ids = [v for k, v in feature.attrib.items() if k.endswith('}id')]
        if len(ids) != 1:
            raise ValueError('Missing/ambiguous drawing relationship')
        relation = relations[ids[0]]
        if relation.get('TargetMode') == 'External':
            result.limitations.append(f'{sheet.name}: {sheet.part}#xml=/: External drawing hyperlink content was not fetched.')
            continue
        part = _part(sheet.part, relation.attrib['Target'])
        root = safe_xml.fromstring(reader._archive.read(part))
        for element, location in indexed_paths(root).items():
            if element.tag in {f'{{{ns}}}{name}' for ns in (
                'http://schemas.openxmlformats.org/drawingml/2006/main',
                'http://purl.oclc.org/ooxml/drawingml/main') for name in ('hlinkClick', 'hlinkHover')}:
                result.limitations.append(f'{sheet.name}: {part}#xml={location}: Drawing hyperlink requires manual review; label and purpose were not screened.')
