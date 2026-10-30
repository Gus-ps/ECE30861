"""1.4.1 Use of Color / 1.4.3 Contrast (Minimum): static screening only."""
from accessibility_checker import safe_xml
from accessibility_checker.cell_reader import WorkbookReader, _relationships, _part
from accessibility_checker.color_styles import StyleResolver, UnsupportedRendering, contrast_ratio
from accessibility_checker.coordinates import canonical_range
from accessibility_checker.finding_ids import get_source_sha256, make_phase4_finding_id
from accessibility_checker.results import Findings, finalize_findings
from accessibility_checker.worksheet_features import worksheet_features, contains


def _review(result, source, sheet, target, reasons, limitation=False):
    result.append(dict(findingId=make_phase4_finding_id(source,'COLOR_CONTRAST',sheet.name,target),
        ruleId='COLOR_CONTRAST',category='COLOR_OR_CONTRAST',worksheet=sheet.name,
        target=target,classification='MANUAL_REVIEW',message=' '.join(reasons),
        recommendation='Review the displayed colors and provide equivalent text or structure; no colors were changed.'))
    if limitation:
        result.limitations.extend(f'{sheet.name}: {target}: {reason}' for reason in reasons)


def _conditional_ranges(reader, sheet):
    relations = _relationships(reader._archive, reader.workbook_part)
    styles = [r for r in relations.values() if r.attrib['Type'].endswith('/styles')]
    differential = []
    if styles:
        if len(styles) != 1:
            raise ValueError('Ambiguous styles relationships')
        root = safe_xml.fromstring(reader._archive.read(_part(reader.workbook_part,styles[0].attrib['Target'])))
        ns = root.tag.split('}')[0]+'}'
        differential = root.findall(ns+'dxfs/'+ns+'dxf')
    ranges = set()
    unresolved = False
    for feature in worksheet_features(reader,sheet,{'conditionalFormatting','extLst'}):
        ns = feature.tag.split('}')[0]+'}'
        candidates = [feature] if feature.tag == ns+'conditionalFormatting' else [
            e for e in feature.iter() if e.tag.rsplit('}',1)[-1]=='conditionalFormatting']
        if feature.tag == ns+'extLst' and not candidates:
            # Unknown visual extensions have no reliable sqref: disclose full grid.
            unresolved = True
            continue
        for candidate in candidates:
            visual = feature.tag == ns+'extLst'
            for rule in candidate:
                if rule.tag != ns+'cfRule':
                    visual = True
                    continue
                visual |= rule.get('type') in {'colorScale','dataBar','iconSet'}
                visual |= any(e.tag.rsplit('}',1)[-1] in {'colorScale','dataBar','iconSet','extLst'} for e in rule.iter())
                identifier = rule.get('dxfId')
                if identifier is not None:
                    if not identifier.isdigit() or int(identifier)>=len(differential):
                        visual = True
                    else:
                        dxf=differential[int(identifier)]
                        visual |= dxf.find(ns+'fill') is not None or dxf.find(ns+'font/'+ns+'color') is not None
            if visual:
                refs = candidate.get('sqref') or ' '.join(e.text or '' for e in candidate.iter() if e.tag.rsplit('}',1)[-1]=='sqref')
                if not refs:
                    unresolved = True
                for ref in refs.split():
                    ranges.add(canonical_range(ref))
    return ranges, unresolved


def check_color_contrast(path, *, source_sha256=None):
    """Never calculate formulas, evaluate conditions, fetch content or save input."""
    source = source_sha256 if source_sha256 is not None else get_source_sha256(path)
    result=Findings(); assumptions=set(); missing_cache=False
    with WorkbookReader(path) as reader:
        try:
            resolver=StyleResolver(reader)
            resolver_error=None
        except UnsupportedRendering as error:
            resolver=None;resolver_error=str(error)
        for sheet in reader.sheets:
            if sheet.kind!='worksheet':continue
            if sheet.external:
                _review(result,source,sheet,reader.workbook_part+'#xml=/', ['External worksheet colors are not fetched.'],True)
                continue
            conditional, unresolved=_conditional_ranges(reader,sheet)
            if unresolved:
                _review(result,source,sheet,sheet.part+"#xml=/", ["Visual extension has no resolvable declared range; worksheet static rendering was not assessed."],True)
            for rectangle in sorted(conditional):
                _review(result,source,sheet,sheet.part+'#conditional='+rectangle,
                        ['Conditional visual formatting was not evaluated; static color screening is suppressed in this range.'],True)
            for cell in reader.read_cells(sheet):
                if unresolved or not cell.populated or any(contains(r,cell.row,cell.column) for r in conditional):continue
                target=sheet.part+'#cell='+cell.reference
                try:
                    if resolver_error:raise UnsupportedRendering(resolver_error)
                    style=resolver.resolve(sheet,cell)
                except UnsupportedRendering as error:
                    _review(result,source,sheet,target,['Static rendering could not be resolved: '+str(error)],True)
                    continue
                assumptions.update(style.assumptions)
                nonneutral=any(len(set(color))>1 for color in (style.font_rgb,style.fill_rgb))
                reasons=[]
                usable = not cell.has_formula or cell.cached_value not in (None,'')
                if not usable:missing_cache=True
                if usable:
                    ratio=contrast_ratio(style.font_rgb,style.fill_rgb)
                    threshold=3.0 if style.size>=18 or (style.size>=14 and style.bold) else 4.5
                    if ratio<threshold:reasons.append(f'Static text contrast {ratio:.2f}:1 is below {threshold:.1f}:1.')
                if nonneutral:reasons.append('Nonneutral font or fill color may convey meaning without equivalent text or structure.')
                if reasons:_review(result,source,sheet,target,reasons)
    result.limitations.extend('COLOR_CONTRAST: '+reason for reason in sorted(assumptions))
    if missing_cache:result.limitations.append('COLOR_CONTRAST: Formula text without a usable saved cache was not calculated; only color meaning was screened.')
    return finalize_findings(result)
