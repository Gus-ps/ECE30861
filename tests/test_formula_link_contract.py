"""Independent contract vectors; never import a production checker or response."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from tester.suite.identity import finding_id

PACK=Path(__file__).parents[1]/'tester/fixtures/phase4'


def test_formula_targets_and_independent_identity_vectors():
    entries=json.loads((PACK/'expectations.json').read_text(encoding='utf-8'))['fixtures']
    vectors=json.loads((PACK/'formula_link_identity_vectors.json').read_text(encoding='utf-8'))
    links=[v for v in vectors if v['fixture']=='link_vectors']
    assert [v['target'] for v in links]==[
        f'xl/worksheets/sheet1.xml#xml=/worksheet[1]/sheetData[1]/row[{row}]/c[1]'
        for row in (11,12,13)]
    assert [v['findingId'] for v in links]==[
        '1d423a59f9227fd8304cf7982b7138af1557a9b4c569c00ffd9a8fe2d14d93b0',
        'ade7d1e48d06087c1c734b488ed76e82e207a5dcd68e5f556e68e11eff9aa776',
        '6f4892fa45cc49b9e44294bb7e281e360c06a064711dfb2731f9f42ae3df6995']
    for vector in vectors:
        entry=entries[vector['fixture']]
        sha=hashlib.sha256((PACK/entry['file']).read_bytes()).hexdigest()
        assert sha==entry['sha256']==vector['sourceSha256']
        fields=[sha,'2.0.0','LINK_TEXT',vector['worksheet'],vector['target']]
        expected=hashlib.sha256(json.dumps(fields,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
        assert expected==vector['findingId']==finding_id(*fields)
        finding=next(f for f in entry['findings'] if f['ruleId']=='LINK_TEXT' and f['target']==vector['target'])
        assert finding['classification']=='MANUAL_REVIEW'
    entry=entries['link_vectors']
    assert entry['limitation_facts']
    with ZipFile(PACK/entry['file']) as archive:
        root=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        rows=root.find('{*}sheetData').findall('{*}row')
        for ordinal in (11,12,13):
            cell=rows[ordinal-1].findall('{*}c')[0]
            assert cell.get('r')==f'A{ordinal}'
            assert 'HYPERLINK' in cell.findtext('{*}f')


def test_manual_apply_attempts_reference_existing_manual_findings():
    from tester.suite.checks_phase4 import _invalid_bodies
    entry=json.loads((PACK/'expectations.json').read_text(encoding='utf-8'))['fixtures']['unsupported_edits']
    findings=[dict(f, findingId=hashlib.sha256(f['target'].encode()).hexdigest()) for f in entry['findings']]
    record={'entry':entry,'audit':{'auditId':'audit-vector','findings':findings}}
    variants=_invalid_bodies(None,record,'MANUAL-APPLY')
    manual_ids={f['findingId'] for f in findings if f['classification']=='MANUAL_REVIEW'}
    assert len(variants)==len(entry['apply_attempts'])
    for label, body, status, code in variants:
        assert body['decisions'][0]['findingId'] in manual_ids, label
        assert status==422 and code=='UNSUPPORTED_CORRECTION'
