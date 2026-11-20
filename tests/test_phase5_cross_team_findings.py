"""Independent small OOXML cases for the cross-team Phase 5 report findings."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from openpyxl import Workbook
from openpyxl.worksheet.table import Table

from accessibility_checker.runner import check_workbook
from remediation import RemediationError, remediate, validate_decisions

CF = '''<extLst><ext uri="{78C0D931-6437-407d-A8EE-F0AAD7539E65}"
 xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main">
 <x14:conditionalFormattings><x14:conditionalFormatting
 xmlns:xm="http://schemas.microsoft.com/office/excel/2006/main">
 <x14:cfRule type="expression" priority="1" id="{6F1C2D3E-0000-4000-8000-000000000001}">
 <xm:f>Sheet1!$B$2&gt;5</xm:f><x14:dxf><font><b/></font></x14:dxf>
 </x14:cfRule><xm:sqref>D1</xm:sqref></x14:conditionalFormatting>
 </x14:conditionalFormattings></ext></extLst>'''


class CrossTeamFindingTests(unittest.TestCase):
    def test_logical_disclosure_applies_only_to_unsafe_unstructured_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'book.xlsx'
            book=Workbook();book.active.title='Data'
            for row in ((1,2),(3,4)):book.active.append(row)
            book.save(path)
            findings=check_workbook(path)
            self.assertTrue(any('Logical table structure could not be established safely for A1:B2.' in text
                                for text in findings.limitations))
            self.assertTrue(any('first row lacks' in text for text in findings.limitations))
            book.active['A1']='Record';book.active['B1']='Value'
            book.active.add_table(Table(displayName='Records',ref='A1:B2'));book.save(path)
            self.assertFalse(any('Logical table structure' in text for text in check_workbook(path).limitations))

    def test_known_x14_reference_is_rewritten_and_unknown_extensions_stay_manual(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'source.xlsx';output=Path(directory)/'output.xlsx'
            book=Workbook();book.active.title='Sheet1';book.active['B2']=10
            report=book.create_sheet('Report');report['D1']='Flag'
            report['A1']='Sheet1!B2';report['A2']='=LEN("Sheet1")'
            book.save(path)
            with ZipFile(path) as archive:
                entries=[(info,archive.read(info)) for info in archive.infolist()]
            def write(extension):
                with ZipFile(path,'w') as archive:
                    for info,data in entries:
                        if info.filename=='xl/worksheets/sheet2.xml':
                            data=data.decode().replace('</worksheet>',extension+'</worksheet>').encode()
                        archive.writestr(info,data)
            write(CF)
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            findings=check_workbook(path)
            finding=next(f for f in findings if f['ruleId']=='WORKSHEET_NAME')
            self.assertEqual(finding['classification'],'REQUIRES_USER_INPUT')
            self.assertFalse(any(f['ruleId']=='COLOR_CONTRAST' for f in findings))
            decisions=[{'findingId':finding['findingId'],'action':'APPLY','value':{'name':'Data source'}}]
            remediate(path,output,decisions,findings=findings)
            with ZipFile(output) as archive:
                xml=ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
                formula=xml.find('.//{http://schemas.microsoft.com/office/excel/2006/main}f')
                self.assertEqual(formula.text,"'Data source'!$B$2>5")
                self.assertIn('Sheet1!B2',[e.text for e in xml.iter()])
                self.assertIn('LEN("Sheet1")',[e.text for e in xml.iter()])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
            for extension in (CF.replace('78C0D931','18C0D931'),
                              CF.replace('Sheet1!$B$2&gt;5','INDIRECT(&quot;Sheet1!B2&quot;)&gt;5')):
                write(extension)
                findings=check_workbook(path)
                finding=next(f for f in findings if f['ruleId']=='WORKSHEET_NAME')
                self.assertEqual(finding['classification'],'MANUAL_REVIEW')
                with self.assertRaises(RemediationError) as caught:
                    validate_decisions(path,[dict(decisions[0],findingId=finding['findingId'])],findings=findings)
                self.assertEqual(caught.exception.code,'UNSUPPORTED_CORRECTION')
