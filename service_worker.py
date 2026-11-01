"""Bounded child-process bridge to Jonathan's read-only checker and remediation module."""
import json
import sys
from pathlib import Path
from zipfile import ZipFile

from accessibility_checker import safe_xml
from accessibility_checker.cell_reader import WorkbookReader
from accessibility_checker.runner import RULE_ORDER, check_workbook
from remediation import RemediationError, remediate, validate_decisions, _template


def audit(path):
    findings = check_workbook(path)
    items = []
    with ZipFile(path) as archive:
        for finding in findings:
            value = None
            supported = finding['classification'] == 'REQUIRES_USER_INPUT'
            rule = finding['ruleId']
            if supported and rule == 'WORKSHEET_NAME':
                value = {'name': finding['worksheet']}
            elif supported and rule == 'ALT_TEXT':
                part, identifier = finding['target'].split('#id=')
                root = safe_xml.fromstring(archive.read(part))
                props = next(n for n in root.iter() if n.tag.rsplit('}', 1)[-1] == 'cNvPr' and n.get('id') == identifier)
                value = {'title': props.get('title'), 'description': props.get('descr')}
            elif supported and rule == 'TABLE_HEADER':
                value = _template(archive, finding)
            elif supported and rule == 'LINK_TEXT':
                part, reference = finding['target'].split('#cell=')
                with WorkbookReader(path) as reader:
                    sheet = next(s for s in reader.sheets if s.part == part)
                    cell = next((c for c in reader.read_cells(sheet) if c.reference == reference), None)
                    value = {'text': str(cell.value) if cell and cell.value is not None else ''}
            actions = ['APPLY', 'DECLINE', 'MANUAL_REVIEW'] if supported and value is not None else ['DECLINE', 'MANUAL_REVIEW']
            items.append({'findingId': finding['findingId'], 'allowedActions': actions,
                          'currentValue': value, 'reason': finding['recommendation']})
    return {'findings': list(findings), 'limitations': list(findings.limitations),
            'items': items, 'checksPerformed': list(RULE_ORDER)}


def main():
    # Keep a hostile/large package from exhausting the API host. Failure is
    # observed by the parent and persisted without publishing partial output.
    if sys.platform != 'win32':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024**2, 384 * 1024**2))
    mode, source = sys.argv[1:3]
    try:
        if mode == 'audit':
            result = audit(source)
        else:
            args = json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))
            if mode == 'validate':
                result = validate_decisions(source, args['decisions'], findings=args['findings'])
            else:
                result = remediate(source, sys.argv[4], args['decisions'], findings=args['findings'])
        print(json.dumps({'result': result}, ensure_ascii=False))
    except RemediationError as error:
        print(json.dumps({'error': {'code': error.code, 'message': str(error)}}))


if __name__ == '__main__':
    main()
