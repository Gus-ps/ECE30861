"""2.4.4 partial hyperlink screening; REQ-03/04/05/06, AC-03/04/05/06."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from openpyxl import Workbook
from accessibility_checker.checks.link_text import ambiguous_label, literal_hyperlink, check_link_text

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
DOC = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'


class LinkTextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'links.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.title = 'Data'
        sheet['A1'] = 'click here'
        sheet['A1'].hyperlink = 'https://example.invalid/'
        sheet['A2'] = 'Annual accessibility report'
        sheet['A2'].hyperlink = 'https://example.invalid/'
        sheet['A3'] = 'https://example.invalid/' # Ordinary URL is not a hyperlink.
        book.save(self.path)
        book.close()

    def edit(self, part, action):
        with ZipFile(self.path) as archive:
            parts = {p: archive.read(p) for p in archive.namelist()}
        root = ET.fromstring(parts[part])
        action(root)
        parts[part] = ET.tostring(root)
        with ZipFile(self.path, 'w') as archive:
            for name, data in parts.items():
                archive.writestr(name, data)

    def test_predicate_exact_vocabulary_whitespace_and_punctuation(self):
        for label in ['click\u00a0\there!', ' HERE? ', 'READ MORE.', 'https://other.invalid', 'www.x', 'mailto:x', '']:
            self.assertTrue(ambiguous_label(label, 'destination'), label)
        for label in ['click here!!', 'click somewhere', '\u200b', 'Annual report', 'here\u001c']:
            self.assertFalse(ambiguous_label(label, 'destination'), label)
        self.assertTrue(ambiguous_label(' DEST ', 'dest'))

    def test_literals_escape_comma_and_unsupported_grammar(self):
        self.assertEqual(literal_hyperlink('=_xlfn.hYpErLiNk("a,b","a ""quoted"" report")'), ('a,b','a "quoted" report'))
        self.assertEqual(literal_hyperlink('HYPERLINK("url")'), ('url','url'))
        for text in ['HYPERLINK(A1,"here")', 'HYPERLINK("x";"here")', 'HYPERLINK("x",)', '==HYPERLINK("x")', 'HYPERLINK("x","here")+1']:
            self.assertIsNone(literal_hyperlink(text), text)

    def test_visible_text_over_display_and_independent_id(self):
        def display(root):
            links = root.find(NS+'hyperlinks')
            links[0].set('display', 'Annual accessibility report')
            links[1].set('display', 'click here')
        self.edit('xl/worksheets/sheet1.xml', display)
        before = self.path.read_bytes()
        result = check_link_text(self.path)
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual((item['target'],item['classification']), ('xl/worksheets/sheet1.xml#cell=A1','REQUIRES_USER_INPUT'))
        identity = [hashlib.sha256(before).hexdigest(),'2.0.0','LINK_TEXT','Data',item['target']]
        self.assertEqual(item['findingId'], hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(',',':')).encode()).hexdigest())
        self.assertEqual(result, check_link_text(self.path))
        self.assertEqual(before,self.path.read_bytes())

    def test_formula_descriptive_literal_computed_and_string_literal(self):
        def formulas(root):
            root.remove(root.find(NS+'hyperlinks'))
            data = root.find(NS+'sheetData')
            data.clear()
            for row, formula in enumerate(['HYPERLINK("x","here")','_xlfn.HYPERLINK("x","Annual report")',
                'HYPERLINK(A1,"here")','HYPERLINK("x";"here")','"HYPERLINK("',
                'IF(TRUE,HYPERLINK("x","here"),"none")'],1):
                cell = ET.SubElement(ET.SubElement(data, NS+'row',r=str(row)),NS+'c',r=f'A{row}')
                ET.SubElement(cell,NS+'f').text = formula
        self.edit('xl/worksheets/sheet1.xml',formulas)
        result = check_link_text(self.path)
        self.assertEqual(len(result),4)
        self.assertTrue(all(f['classification']=='MANUAL_REVIEW' for f in result))
        self.assertIn('xl/worksheets/sheet1.xml#cell=A1',[f['target'] for f in result])
        self.assertIn('xl/worksheets/sheet1.xml#xml=/worksheet[1]/sheetData[1]/row[3]/c[1]',[f['target'] for f in result])

    def test_duplicate_range_rich_and_merged_representations(self):
        def duplicate(root):
            links=root.find(NS+'hyperlinks')
            ET.SubElement(links,NS+'hyperlink',ref='A1:B2',location='Data!A1')
        self.edit('xl/worksheets/sheet1.xml',duplicate)
        result=check_link_text(self.path)
        self.assertEqual(len(result),3) # A2 also overlaps the range declaration.
        self.assertEqual(len({f['target'] for f in result}),3)
        self.assertTrue(all('#xml=' in f['target'] and f['classification']=='MANUAL_REVIEW' for f in result))

    def test_shared_strings_reused_and_rich_provenance(self):
        with ZipFile(self.path) as archive:
            parts={p:archive.read(p) for p in archive.namelist()}
        sheet=ET.fromstring(parts['xl/worksheets/sheet1.xml'])
        for cell in sheet.findall('.//'+NS+'c')[:2]:
            address=cell.get('r');cell.clear();cell.set('r',address);cell.set('t','s');ET.SubElement(cell,NS+'v').text='0'
        parts['xl/worksheets/sheet1.xml']=ET.tostring(sheet)
        rels=ET.fromstring(parts['xl/_rels/workbook.xml.rels'])
        ET.SubElement(rels,f'{{{PKG}}}Relationship',Id='strings',Type=DOC+'/sharedStrings',Target='sharedStrings.xml')
        parts['xl/_rels/workbook.xml.rels']=ET.tostring(rels)
        for rich in [False,True]:
            text='<r><t>here</t></r>' if rich else '<t>here</t>'
            parts['xl/sharedStrings.xml']=(f'<sst xmlns="{NS[1:-1]}"><si>{text}<rPh sb="0" eb="1"><t>ignored</t></rPh></si></sst>').encode()
            with ZipFile(self.path,'w') as archive:
                for name,data in parts.items():archive.writestr(name,data)
            before=self.path.read_bytes()
            result=check_link_text(self.path)
            self.assertEqual(len(result),2)
            self.assertEqual({f['classification'] for f in result},{'MANUAL_REVIEW' if rich else 'REQUIRES_USER_INPUT'})
            self.assertEqual(before,self.path.read_bytes())

    def test_hidden_merge_and_shared_worksheet_are_manual(self):
        self.edit('xl/workbook.xml',lambda r:r.find(NS+'sheets/'+NS+'sheet').set('state','veryHidden'))
        self.assertEqual(check_link_text(self.path)[0]['classification'],'REQUIRES_USER_INPUT')
        def merge(root):
            ET.SubElement(ET.SubElement(root,NS+'mergeCells'),NS+'mergeCell',ref='A1:B1')
        self.edit('xl/worksheets/sheet1.xml',merge)
        self.assertEqual(check_link_text(self.path)[0]['classification'],'MANUAL_REVIEW')
        def shared(root):
            sheets=root.find(NS+'sheets')
            ET.SubElement(sheets,NS+'sheet',name='Other',sheetId='2',attrib={f'{{{DOC}}}id':sheets[0].get(f'{{{DOC}}}id')})
        self.edit('xl/workbook.xml',shared)
        result=check_link_text(self.path)
        self.assertEqual(len(result),4) # Both labels on both owners are ambiguous to edit.
        self.assertTrue(any('multiple owning' in reason for reason in result.limitations))

    def test_drawing_hyperlinks_disclosed_without_fetching(self):
        doc=DOC;pkg=PKG
        with ZipFile(self.path) as archive:
            parts={p:archive.read(p) for p in archive.namelist()}
        sheet=ET.fromstring(parts['xl/worksheets/sheet1.xml'])
        ET.SubElement(sheet,NS+'drawing',{f'{{{doc}}}id':'drawing'})
        parts['xl/worksheets/sheet1.xml']=ET.tostring(sheet)
        rels=ET.fromstring(parts['xl/worksheets/_rels/sheet1.xml.rels'])
        ET.SubElement(rels,f'{{{pkg}}}Relationship',Id='drawing',Type=doc+'/drawing',Target='../drawings/drawing90.xml')
        parts['xl/worksheets/_rels/sheet1.xml.rels']=ET.tostring(rels)
        parts['xl/drawings/drawing90.xml']=b'<x:wsDr xmlns:x="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><x:pic><x:nvPicPr><x:cNvPr id="7"><a:hlinkClick/></x:cNvPr></x:nvPicPr></x:pic></x:wsDr>'
        with ZipFile(self.path,'w') as archive:
            for name,data in parts.items():archive.writestr(name,data)
        result=check_link_text(self.path)
        self.assertTrue(any('drawing90.xml#xml=/wsDr[1]/pic[1]/nvPicPr[1]/cNvPr[1]/hlinkClick[1]' in reason for reason in result.limitations))

    def test_foreign_namespace_is_not_a_supported_hyperlink(self):
        def foreign(root):
            ET.SubElement(root,'{urn:foreign}hyperlinks').append(ET.Element('{urn:foreign}hyperlink',ref='B9',location='x'))
        self.edit('xl/worksheets/sheet1.xml',foreign)
        result=check_link_text(self.path)
        self.assertEqual(len(result),2)
        self.assertEqual(result[1]['classification'],'MANUAL_REVIEW')
        self.assertEqual(result[1]['target'],'xl/worksheets/sheet1.xml#xml=/worksheet[1]/hyperlinks[2]')
