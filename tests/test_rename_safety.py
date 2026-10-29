"""Partial 2.4.2 Page Titled / 2.4.6 Headings and Labels rename preflight.

REQ-03/04/05/06/15 and AC-03/04/05/06/18: classification and preservation only;
no reference rewriting, output serialization or whole-WCAG acceptance.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from accessibility_checker.checks.worksheet_names import check_worksheet_names
from accessibility_checker.part_ownership import SheetOwner
from accessibility_checker.rename_safety import formula_reason
from accessibility_checker.results import Findings

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CHART = "http://schemas.openxmlformats.org/drawingml/2006/chart"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
DRAW = "http://schemas.openxmlformats.org/drawingml/2006/main"


class FormulaPreflightTests(unittest.TestCase):
    def setUp(self):
        self.sheets = tuple(SheetOwner(i, name, str(i + 1), "worksheet", f"s{i}.xml")
                            for i, name in enumerate(("Sheet1", "Other", "O'Brien", "A!B")))
        self.names = {(None, "namedrange"), (1, "localname")}

    def test_quoted_references_literals_unions_ranges_and_named_scopes(self):
        for formula in (
            "=SUM(Sheet1!$A$1:$B$9,Other!A1)", "='O''Brien'!A1+'A!B'!$C$2",
            '="Sheet1!A1 and INDIRECT() are plain text"',
            "=(Sheet1!A1,Other!B2)", "=SUM(Sheet1!$A:$D)", "=SUM(Sheet1!$1:$4)",
            "=IF(A1,,NamedRange)", "=Other!LocalName", "=1+2*3%", "=TRUE",
            "=IF(A1=0,\"O'Brien\",\"Sheet1\")",
        ):
            with self.subTest(formula=formula):
                self.assertIsNone(formula_reason(formula, self.sheets, self.names))

    def test_tokenizer_alone_is_not_proof_of_safe_reference_structure(self):
        for formula, reason in (
            ("=Sheet1:Other!A1", "3D"), ("='Sheet1:Other'!A1", "3D"),
            ("=[Book.xlsx]Sheet1!A1", "External"),
            ('=INDIRECT("Sheet1!A1")', "INDIRECT"), ('=EVALUATE("A1")', "EVALUATE"),
            ('=HYPERLINK("#Sheet1!A1","label")', "HYPERLINK"),
            ("=_xlfn.XLOOKUP(A1,A2,A3)", "extension"), ("=CUSTOMREF(A1)", "function"),
            ("=Table1[Column]", "structured"), ("=UnknownName", "name"),
            ("=Missing!A1", "qualifier"), ("=A1#", "tokenization"),
            ("=@A1", "operand"), ("=A1 B2", "intersection"),
            ("=SUM(A1+)", "operand"), ("=A1+", "Incomplete"),
            ("=SUM(A1", "Incomplete"), ("=A1)", "tokenization"),
            ("=A1048577", "bounds"), ("=LocalName", "name"),
        ):
            with self.subTest(formula=formula):
                self.assertIn(reason, formula_reason(formula, self.sheets, self.names))


class RenameInventoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "source.xlsx"

    def write(self, other_body="", names="", formula=None, formula_attributes=""):
        cell = '' if formula is None else '<row><c r="A1"><f ' + formula_attributes + '>' + formula + '</f><v/></c></row>'
        self.parts = {
            "xl/workbook.xml": f'<workbook xmlns="{MAIN}" xmlns:r="{DOC}"><sheets>'
            '<sheet name="Sheet1" sheetId="7" r:id="first"/>'
            '<sheet name="Other" sheetId="9" state="veryHidden" r:id="other"/>'
            f'</sheets><definedNames>{names}</definedNames></workbook>',
            "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{PKG}">'
            f'<Relationship Id="first" Type="{DOC}/worksheet" Target="worksheets/a.xml"/>'
            f'<Relationship Id="other" Type="{DOC}/worksheet" Target="worksheets/b.xml"/>'
            '</Relationships>',
            "xl/worksheets/a.xml": f'<worksheet xmlns="{MAIN}"><sheetData/></worksheet>',
            "xl/worksheets/b.xml": f'<worksheet xmlns="{MAIN}" xmlns:r="{DOC}"><sheetData>{cell}</sheetData>{other_body}</worksheet>',
        }
        self.save()

    def save(self):
        with ZipFile(self.path, "w") as archive:
            for name, data in self.parts.items():
                archive.writestr(name, data)

    def add_relationship(self, parent, kind, target, identifier="added"):
        directory, filename = parent.rsplit("/", 1)
        path = directory + "/_rels/" + filename + ".rels"
        root = ET.fromstring(self.parts.get(path, f'<Relationships xmlns="{PKG}"/>'))
        ET.SubElement(root, f"{{{PKG}}}Relationship", {
            "Id": identifier, "Type": f"{DOC}/{kind}", "Target": target,
        })
        self.parts[path] = ET.tostring(root)

    def assert_classification(self, classification, reason=None):
        before = self.path.read_bytes()
        result = check_worksheet_names(self.path)
        self.assertIsInstance(result, Findings)
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item["classification"], classification)
        self.assertEqual(item["worksheet"], "Sheet1")
        self.assertEqual(item["target"], "xl/worksheets/a.xml#sheetId=7")
        payload = json.dumps([hashlib.sha256(before).hexdigest(), "2.0.0",
                              "WORKSHEET_NAME", "Sheet1", item["target"]],
                             ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.assertEqual(item["findingId"], hashlib.sha256(payload).hexdigest())
        if reason is None:
            self.assertEqual(result.limitations, [])
        else:
            self.assertTrue(any(reason in limitation for limitation in result.limitations), result.limitations)
        repeated = check_worksheet_names(self.path)
        self.assertEqual(result, repeated)
        self.assertEqual(result.limitations, repeated.limitations)
        self.assertEqual(before, self.path.read_bytes())

    def test_safe_no_reference_workbook(self):
        self.write()
        self.assert_classification("REQUIRES_USER_INPUT")

    def test_safe_formulas_names_validation_formatting_and_internal_hyperlink(self):
        self.write(
            other_body='<dataValidations count="1"><dataValidation type="list" sqref="B1">'
            '<formula1>Sheet1!$A$1:$A$3</formula1></dataValidation></dataValidations>'
            '<conditionalFormatting sqref="A1"><cfRule type="expression" priority="1">'
            '<formula>Sheet1!A1&gt;0</formula></cfRule></conditionalFormatting>'
            '<hyperlinks><hyperlink ref="C1" location="\u0027Sheet1\u0027!A1"/></hyperlinks>',
            names='<definedName name="GlobalName">Sheet1!$A$1:$B$2</definedName>'
            '<definedName name="LocalName" localSheetId="1">Other!$A$1</definedName>',
            formula='SUM(Sheet1!A1,GlobalName,LocalName)+IF(A1=0,1,2)',
        )
        self.assert_classification("REQUIRES_USER_INPUT")

    def test_same_name_string_literals_do_not_become_references(self):
        self.write(formula='"Sheet1!A1 INDIRECT and [Book.xlsx] are text"')
        self.assert_classification("REQUIRES_USER_INPUT")

    def test_apostrophe_sheet_names_are_resolved_in_xml_formula_inventory(self):
        self.write(formula="'O''Brien'!$A$1+Sheet1!A2")
        self.parts['xl/workbook.xml'] = self.parts['xl/workbook.xml'].replace(
            'name="Other"', 'name="O\u0027Brien"',
        )
        self.save()
        self.assert_classification("REQUIRES_USER_INPUT")

    def test_unknown_metadata_and_object_formula_bindings_are_manual(self):
        self.write()
        self.add_relationship('xl/workbook.xml', 'styles', 'styles.xml')
        self.parts['xl/styles.xml'] = f'<styleSheet xmlns="{MAIN}"><futureReference/></styleSheet>'
        self.save()
        self.assert_classification("MANUAL_REVIEW", "unrecognized metadata element")
        self.write(other_body='<sheetPr codeName="Existing" macro="RunSomething"/>')
        self.assert_classification("MANUAL_REVIEW", "macro/query/object formula binding")

    def test_other_sheet_dangerous_formulas_and_formula_modes_are_global(self):
        for formula, attributes, reason in (
            ('Sheet1:Other!A1', '', '3D'), ('[Book.xlsx]Sheet1!A1', '', 'External'),
            ('INDIRECT("Sheet1!A1")', '', 'INDIRECT'), ('EVALUATE("A1")', '', 'EVALUATE'),
            ('HYPERLINK("#Sheet1!A1","here")', '', 'HYPERLINK'),
            ('_xlfn.XLOOKUP(A1,A2,A3)', '', 'extension'),
            ('Sheet1!A1', 't="shared" si="0"', 'shared/array'),
            ('Sheet1!A1', 't="array" ref="A1:A2"', 'shared/array'),
            ('_xlfn.SINGLE(A1)', '', 'extension'),
        ):
            with self.subTest(formula=formula, attributes=attributes):
                self.write(formula=formula, formula_attributes=attributes)
                self.assert_classification("MANUAL_REVIEW", reason)

    def test_reference_bearing_relationships_and_opaque_parts_are_manual(self):
        for kind in ("externalLink", "pivotTable", "pivotCacheDefinition", "slicer",
                     "queryTable", "connections", "oleObject", "package", "sheetMetadata"):
            with self.subTest(kind=kind):
                self.write()
                self.add_relationship("xl/workbook.xml", kind, "opaque.xml")
                self.parts["xl/opaque.xml"] = '<opaque/>'
                self.save()
                self.assert_classification("MANUAL_REVIEW", kind)
        for part, reason in (("_xmlsignatures/sig1.xml", "signed"),
                             ("xl/embeddings/other.xlsx", "opaque"),
                             ("customXml/item1.xml", "opaque")):
            with self.subTest(part=part):
                self.write()
                self.parts[part] = '<unknown/>'
                self.save()
                self.assert_classification("MANUAL_REVIEW", reason)

    def test_unknown_elements_and_attributes_are_explicit_limits(self):
        for body, reason in (("<extLst><futureReference/></extLst>", "element"),
                             ('<hyperlinks futureRef="Sheet1!A1"/>', "attribute")):
            with self.subTest(body=body):
                self.write(other_body=body)
                self.assert_classification("MANUAL_REVIEW", reason)

    def test_bad_defined_name_formula_blocks_rename(self):
        self.write(names='<definedName name="Dynamic">INDIRECT("Sheet1!A1")</definedName>')
        self.assert_classification("MANUAL_REVIEW", "defined name")

    def test_hidden_chartsheet_series_reference_is_supported(self):
        self.write()
        root = ET.fromstring(self.parts['xl/workbook.xml'])
        ET.SubElement(root.find('{*}sheets'), f'{{{MAIN}}}sheet', {
            'name': 'Chart', 'sheetId': '12', 'state': 'hidden', f'{{{DOC}}}id': 'charttab',
        })
        self.parts['xl/workbook.xml'] = ET.tostring(root)
        self.add_relationship('xl/workbook.xml', 'chartsheet', 'chartsheets/hidden.xml', 'charttab')
        self.parts['xl/chartsheets/hidden.xml'] = f'<chartsheet xmlns="{MAIN}" xmlns:r="{DOC}"><drawing r:id="draw"/></chartsheet>'
        self.add_relationship('xl/chartsheets/hidden.xml', 'drawing', '../drawings/actual.xml', 'draw')
        self.parts['xl/drawings/actual.xml'] = f'<x:wsDr xmlns:x="{XDR}" xmlns:a="{DRAW}" xmlns:c="{CHART}" xmlns:r="{DOC}"><x:absoluteAnchor><x:graphicFrame><a:graphic><a:graphicData uri="{CHART}"><c:chart r:id="series"/></a:graphicData></a:graphic></x:graphicFrame></x:absoluteAnchor></x:wsDr>'
        self.add_relationship('xl/drawings/actual.xml', 'chart', '../charts/actual.xml', 'series')
        self.parts['xl/charts/actual.xml'] = f'<c:chartSpace xmlns:c="{CHART}"><c:chart><c:plotArea><c:lineChart><c:ser><c:val><c:numRef><c:f>\u0027Sheet1\u0027!$A$1:$A$3</c:f></c:numRef></c:val></c:ser></c:lineChart></c:plotArea></c:chart></c:chartSpace>'
        self.save()
        self.assert_classification("REQUIRES_USER_INPUT")
        self.parts['xl/charts/actual.xml'] = self.parts['xl/charts/actual.xml'].replace("$A$1:$A$3", "[Book]A1")
        self.save()
        self.assert_classification("MANUAL_REVIEW", "External")

    def test_shared_worksheet_and_table_ownership_is_manual(self):
        self.write()
        rels = ET.fromstring(self.parts['xl/_rels/workbook.xml.rels'])
        rels[1].set('Target', 'worksheets/a.xml')
        self.parts['xl/_rels/workbook.xml.rels'] = ET.tostring(rels)
        self.save()
        self.assert_classification("MANUAL_REVIEW", "multiple owning sheets")
        self.write()
        for sheet in ('a', 'b'):
            self.parts[f'xl/worksheets/{sheet}.xml'] = f'<worksheet xmlns="{MAIN}" xmlns:r="{DOC}"><sheetData/><tableParts><tablePart r:id="table"/></tableParts></worksheet>'
            self.add_relationship(f'xl/worksheets/{sheet}.xml', 'table', '../tables/common.xml', 'table')
        self.parts['xl/tables/common.xml'] = f'<table xmlns="{MAIN}" id="1" displayName="Table1" ref="A1:B2"/>'
        self.save()
        self.assert_classification("MANUAL_REVIEW", "shared table ownership")

    def test_missing_structural_parts_or_malformed_xml_do_not_return_empty_success(self):
        for case in ('missing', 'malformed'):
            with self.subTest(case=case):
                self.write()
                if case == 'missing':
                    del self.parts['xl/worksheets/b.xml']
                else:
                    self.parts['xl/worksheets/b.xml'] = '<broken>'
                self.save()
                with self.assertRaises(KeyError if case == 'missing' else ET.ParseError):
                    check_worksheet_names(self.path)


if __name__ == '__main__':
    unittest.main()
