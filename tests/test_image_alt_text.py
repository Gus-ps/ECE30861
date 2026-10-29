"""WCAG 2.1 1.1.1 Non-text Content: retained title/description detection,
with Phase 4 object-level missing/duplicate-ID target tests.

Related to REQ-03/04/05/06 and AC-03/04/05/06; not full criterion coverage.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from accessibility_checker.checks.image_alt_text import check_image_alt_text

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
DRAW = "http://schemas.openxmlformats.org/drawingml/2006/main"
DECORATIVE = "http://schemas.microsoft.com/office/drawing/2017/decorative"


def relationships(items):
    root = ET.Element(f"{{{PKG}}}Relationships")
    for identifier, kind, target in items:
        ET.SubElement(
            root,
            f"{{{PKG}}}Relationship",
            {
                "Id": identifier,
                "Type": f"{DOC}/{kind}",
                "Target": target,
            },
        )
    return root


class ImageAltTextTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "images.xlsx"

    def test_background_only_without_drawing_relationships(self):
        self.write_metadata([("Budget", None, None)])
        self.rewrite_part(
            "xl/worksheets/sheet17.xml",
            lambda root: ET.SubElement(
                root, f"{{{MAIN}}}picture", {f"{{{DOC}}}id": "background"}
            ),
        )
        findings = check_image_alt_text(self.path)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["classification"], "MANUAL_REVIEW")
        self.assertEqual(
            findings[0]["target"],
            "xl/worksheets/sheet17.xml#xml=/worksheet[1]/picture[1]",
        )

    def test_large_grid_streams_and_keeps_exact_image_formula_path(self):
        self.write_metadata([("Budget", None, None)])

        def add_grid(root):
            data = root.find(f"{{{MAIN}}}sheetData")
            for index in range(1, 10001):
                row = ET.SubElement(data, f"{{{MAIN}}}row", {"r": str(index)})
                cell = ET.SubElement(row, f"{{{MAIN}}}c", {"r": f"A{index}"})
                ET.SubElement(cell, f"{{{MAIN}}}v").text = "1"
                if index == 10000:
                    ET.SubElement(
                        cell, f"{{{MAIN}}}f"
                    ).text = 'IMAGE("https://example.com/image.png")'

        self.rewrite_part("xl/worksheets/sheet17.xml", add_grid)
        from accessibility_checker.checks.image_alt_text import _sheet_objects

        with (
            ZipFile(self.path) as archive,
            archive.open("xl/worksheets/sheet17.xml") as stream,
        ):
            self.assertEqual(len(_sheet_objects(stream)), 1)
        findings = check_image_alt_text(self.path)
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0]["target"].endswith("/row[10000]/c[1]"))

    def write_metadata(self, sheets):
        """Build only parts read by the checker, not an Excel-created sample.

        Sheet and drawing part numbers deliberately differ from workbook order.
        Each sheet is (name, state, picture specifications).
        """
        root = ET.Element(f"{{{MAIN}}}workbook")
        sheet_list = ET.SubElement(root, f"{{{MAIN}}}sheets")
        workbook_relationships = []
        with ZipFile(self.path, "w") as archive:
            for index, (name, state, pictures) in enumerate(sheets):
                sheet_file = f"sheet{17 - index}.xml"
                drawing_file = f"drawing{90 - index}.xml"
                attributes = {
                    "name": name,
                    "sheetId": str(index + 1),
                    f"{{{DOC}}}id": f"rId{index}",
                }
                if state is not None:
                    attributes["state"] = state
                ET.SubElement(sheet_list, f"{{{MAIN}}}sheet", attributes)
                workbook_relationships.append(
                    (f"rId{index}", "worksheet", f"worksheets/{sheet_file}")
                )
                sheet = ET.Element(f"{{{MAIN}}}worksheet")
                ET.SubElement(sheet, f"{{{MAIN}}}sheetData")
                if pictures is not None:
                    ET.SubElement(
                        sheet, f"{{{MAIN}}}drawing", {f"{{{DOC}}}id": "rId42"}
                    )
                    # Test both relative and package-absolute relationship targets.
                    target = (
                        f"../drawings/{drawing_file}"
                        if index == 0
                        else f"/xl/drawings/{drawing_file}"
                    )
                    rels = relationships([("rId42", "drawing", target)])
                    archive.writestr(
                        f"xl/worksheets/_rels/{sheet_file}.rels", ET.tostring(rels)
                    )
                    drawing = ET.Element(f"{{{XDR}}}wsDr")
                    for image_index, specification in enumerate(pictures, 1):
                        anchor = ET.SubElement(
                            drawing,
                            f"{{{XDR}}}{specification.get('anchor', 'twoCellAnchor')}",
                        )
                        kind = specification.get("kind", "pic")
                        picture = ET.SubElement(anchor, f"{{{XDR}}}{kind}")
                        nonvisual_kind = {
                            "pic": "nvPicPr",
                            "sp": "nvSpPr",
                            "cxnSp": "nvCxnSpPr",
                            "graphicFrame": "nvGraphicFramePr",
                        }[kind]
                        nonvisual = ET.SubElement(picture, f"{{{XDR}}}{nonvisual_kind}")
                        attributes = {
                            "id": str(image_index),
                            "name": f"photo{image_index}.png",
                        }
                        for attribute in ("descr", "title"):
                            if attribute in specification:
                                attributes[attribute] = specification[attribute]
                        properties = ET.SubElement(
                            nonvisual, f"{{{XDR}}}cNvPr", attributes
                        )
                        if "decorative" in specification:
                            extensions = ET.SubElement(properties, f"{{{DRAW}}}extLst")
                            extension = ET.SubElement(
                                extensions,
                                f"{{{DRAW}}}ext",
                                {
                                    "uri": "{C183D7F6-B498-43B3-948B-1728B52AA6E4}",
                                },
                            )
                            ET.SubElement(
                                extension,
                                f"{{{DECORATIVE}}}decorative",
                                {
                                    "val": specification["decorative"],
                                },
                            )
                        if kind == "graphicFrame":
                            chart_ns = (
                                "http://schemas.openxmlformats.org/drawingml/2006/chart"
                            )
                            graphic = ET.SubElement(picture, f"{{{DRAW}}}graphic")
                            data = ET.SubElement(
                                graphic, f"{{{DRAW}}}graphicData", {"uri": chart_ns}
                            )
                            ET.SubElement(
                                data,
                                f"{{{chart_ns}}}chart",
                                {f"{{{DOC}}}id": f"chart{image_index}"},
                            )
                            chart_part = f"chart{index}_{image_index}.xml"
                            archive.writestr(
                                f"xl/charts/{chart_part}",
                                f'<c:chartSpace xmlns:c="{chart_ns}"/>',
                            )
                    chart_rels = [
                        (f"chart{i}", "chart", f"../charts/chart{index}_{i}.xml")
                        for i, spec in enumerate(pictures, 1)
                        if spec.get("kind") == "graphicFrame"
                    ]
                    if chart_rels:
                        archive.writestr(
                            f"xl/drawings/_rels/{drawing_file}.rels",
                            ET.tostring(relationships(chart_rels)),
                        )
                    archive.writestr(
                        f"xl/drawings/{drawing_file}", ET.tostring(drawing)
                    )
                archive.writestr(f"xl/worksheets/{sheet_file}", ET.tostring(sheet))
            archive.writestr("xl/workbook.xml", ET.tostring(root))
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                ET.tostring(relationships(workbook_relationships)),
            )

    def test_req04_ac04_missing_empty_whitespace_and_title_only(self):
        self.write_metadata(
            [
                (
                    "Budget",
                    None,
                    [
                        {},
                        {"descr": ""},
                        {"descr": " \t\n\u3000"},
                        {"title": "Sales forecast"},
                    ],
                )
            ]
        )
        findings = check_image_alt_text(self.path)
        self.assertEqual(
            [item["target"] for item in findings],
            [f"xl/drawings/drawing90.xml#id={index}" for index in range(1, 5)],
        )
        self.assertEqual(
            [item["message"] for item in findings],
            [
                "Object is missing alternative text title and description (descr).",
                "Object is missing alternative text title and description (descr).",
                "Object is missing alternative text title and description (descr).",
                "Object is missing alternative text description (descr).",
            ],
        )

    def test_req04_ac04_description_present(self):
        self.write_metadata(
            [
                (
                    "Budget",
                    "visible",
                    [
                        {"title": "Sales", "descr": "Sales increased during the year."},
                        {"title": "Logo", "descr": "  A logo  "},
                    ],
                )
            ]
        )
        self.assertEqual(check_image_alt_text(self.path), [])

    def test_req04_ac04_decorative_boolean_values(self):
        self.write_metadata(
            [
                (
                    "Budget",
                    None,
                    [
                        {"decorative": "1"},
                        {"decorative": "true"},
                        {"decorative": "0"},
                        {"decorative": "false"},
                    ],
                )
            ]
        )
        findings = check_image_alt_text(self.path)
        self.assertEqual(
            [item["target"] for item in findings],
            [f"xl/drawings/drawing90.xml#id={i}" for i in range(1, 5)],
        )
        self.assertEqual(
            [item["classification"] for item in findings],
            [
                "MANUAL_REVIEW",
                "MANUAL_REVIEW",
                "REQUIRES_USER_INPUT",
                "REQUIRES_USER_INPUT",
            ],
        )

    def test_req04_ac04_relationship_mapping_multiple_images_and_sheets(self):
        self.write_metadata(
            [
                ("Second", "visible", [{}, {"title": "Title", "descr": "Present"}, {}]),
                ("First", "visible", [{"descr": ""}]),
            ]
        )
        self.assertEqual(
            [
                (item["worksheet"], item["target"])
                for item in check_image_alt_text(str(self.path))
            ],
            [
                ("First", "xl/drawings/drawing89.xml#id=1"),
                ("Second", "xl/drawings/drawing90.xml#id=1"),
                ("Second", "xl/drawings/drawing90.xml#id=3"),
            ],
        )

    def test_req04_ac04_hidden_sheets_shapes_and_charts_included(self):
        self.write_metadata(
            [
                ("Hidden", "hidden", [{}]),
                ("VeryHidden", "veryHidden", [{}]),
                ("Visible", None, [{"kind": "sp"}, {"kind": "graphicFrame"}]),
                ("NoDrawing", None, None),
            ]
        )
        self.assertEqual(
            [(f["worksheet"], f["target"]) for f in check_image_alt_text(self.path)],
            [
                ("Hidden", "xl/drawings/drawing90.xml#id=1"),
                ("VeryHidden", "xl/drawings/drawing89.xml#id=1"),
                ("Visible", "xl/drawings/drawing88.xml#id=1"),
                ("Visible", "xl/drawings/drawing88.xml#id=2"),
            ],
        )

    def test_req04_ac04_all_standard_anchor_types(self):
        self.write_metadata(
            [
                (
                    "Budget",
                    None,
                    [
                        {"anchor": "oneCellAnchor"},
                        {"anchor": "twoCellAnchor"},
                        {"anchor": "absoluteAnchor"},
                    ],
                )
            ]
        )
        self.assertEqual(
            [item["target"] for item in check_image_alt_text(self.path)],
            [f"xl/drawings/drawing90.xml#id={index}" for index in range(1, 4)],
        )

    def test_req05_ac05_finding_contract_and_repeatability(self):
        self.write_metadata(
            [
                ("Second", None, [{} for _ in range(12)]),
                ("First", None, [{}]),
            ]
        )
        findings = check_image_alt_text(self.path)
        self.assertEqual(findings, check_image_alt_text(self.path))
        self.assertEqual(len({item["findingId"] for item in findings}), 13)
        for item in findings:
            self.assertEqual(
                set(item),
                {
                    "findingId",
                    "ruleId",
                    "category",
                    "worksheet",
                    "target",
                    "classification",
                    "message",
                    "recommendation",
                },
            )
            self.assertTrue(all(isinstance(value, str) for value in item.values()))
            self.assertRegex(item["findingId"], r"\A[A-Za-z0-9_-]{1,64}\Z")
            self.assertEqual(item["ruleId"], "ALT_TEXT")
            self.assertEqual(item["category"], "NON_TEXT_CONTENT")
            self.assertEqual(item["classification"], "REQUIRES_USER_INPUT")
            for field in ("message", "recommendation"):
                self.assertTrue(1 <= len(item[field]) <= 500)
        self.assertEqual(
            findings,
            sorted(
                findings,
                key=lambda item: (item["ruleId"], item["worksheet"], item["target"]),
            ),
        )

    def test_req03_ac03_original_bytes_unchanged(self):
        self.write_metadata([("Budget", None, [{}, {"descr": "Present"}])])
        before = self.path.read_bytes()
        check_image_alt_text(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def rewrite_part(self, part, transform):
        with ZipFile(self.path) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        root = ET.fromstring(parts[part])
        transform(root)
        parts[part] = ET.tostring(root)
        with ZipFile(self.path, "w") as archive:
            for name, data in parts.items():
                archive.writestr(name, data)

    def test_title_only_description_only_and_exact_whitespace(self):
        whitespace = "".join(
            map(
                chr,
                [
                    9,
                    10,
                    13,
                    32,
                    133,
                    160,
                    5760,
                    *range(8192, 8203),
                    8232,
                    8233,
                    8239,
                    8287,
                    12288,
                ],
            )
        )
        self.write_metadata(
            [
                (
                    "Budget",
                    None,
                    [
                        {"descr": "Explanation"},
                        {"title": "Title", "descr": whitespace},
                        {"title": whitespace, "descr": "Explanation"},
                        {"title": "\u200b", "descr": "\u200b"},
                        {
                            "title": "Title",
                            "descr": "Description",
                            "decorative": "true",
                        },
                    ],
                )
            ]
        )
        findings = check_image_alt_text(self.path)
        self.assertEqual(
            [f["target"].split("#")[-1] for f in findings],
            ["id=1", "id=2", "id=3", "id=5"],
        )
        self.assertEqual(
            findings[0]["message"], "Object is missing alternative text title."
        )
        self.assertEqual(
            findings[1]["message"],
            "Object is missing alternative text description (descr).",
        )
        self.assertEqual(
            findings[2]["message"], "Object is missing alternative text title."
        )
        self.assertEqual(findings[3]["classification"], "MANUAL_REVIEW")

    def test_group_children_are_checked_individually(self):
        self.write_metadata([("Budget", None, [{}, {"kind": "sp"}])])

        def group_children(root):
            anchors = list(root)
            children = [anchor[0] for anchor in anchors]
            for anchor in anchors:
                root.remove(anchor)
            anchor = ET.SubElement(root, f"{{{XDR}}}twoCellAnchor")
            group = ET.SubElement(anchor, f"{{{XDR}}}grpSp")
            nonvisual = ET.SubElement(group, f"{{{XDR}}}nvGrpSpPr")
            ET.SubElement(nonvisual, f"{{{XDR}}}cNvPr", {"id": "99", "name": "Group"})
            group.extend(children)

        self.rewrite_part("xl/drawings/drawing90.xml", group_children)
        self.assertEqual(
            [f["target"] for f in check_image_alt_text(self.path)],
            ["xl/drawings/drawing90.xml#id=1", "xl/drawings/drawing90.xml#id=2"],
        )

    def test_ambiguous_parent_group_preserves_safe_nested_children(self):
        for case in ("missing_properties", "duplicate_properties", "multiple_markers",
                     "invalid_marker", "foreign_marker"):
            with self.subTest(case=case):
                self.write_metadata([("Budget", None, [
                    {}, {"title": "Complete", "descr": "Description"}, {"kind": "sp"},
                ])])

                def group(root):
                    children = [anchor[0] for anchor in root]
                    for anchor in list(root):
                        root.remove(anchor)
                    anchor = ET.SubElement(root, f"{{{XDR}}}twoCellAnchor")
                    outer = ET.SubElement(anchor, f"{{{XDR}}}grpSp")
                    nv = ET.SubElement(outer, f"{{{XDR}}}nvGrpSpPr")
                    if case != "missing_properties":
                        properties = ET.SubElement(nv, f"{{{XDR}}}cNvPr", {"id": "99"})
                        if case == "duplicate_properties":
                            ET.SubElement(nv, f"{{{XDR}}}cNvPr", {"id": "98"})
                        else:
                            ext = ET.SubElement(properties, f"{{{DRAW}}}extLst")
                            marker_ns = "urn:unknown" if case == "foreign_marker" else DECORATIVE
                            ET.SubElement(ext, f"{{{marker_ns}}}decorative", {
                                "val": "invalid" if case == "invalid_marker" else "true",
                            })
                            if case == "multiple_markers":
                                ET.SubElement(ext, f"{{{DECORATIVE}}}decorative", {"val": "false"})
                    outer.extend(children[:2])
                    inner = ET.SubElement(outer, f"{{{XDR}}}grpSp")
                    nv = ET.SubElement(inner, f"{{{XDR}}}nvGrpSpPr")
                    ET.SubElement(nv, f"{{{XDR}}}cNvPr", {"id": "100"})
                    inner.append(children[2])

                self.rewrite_part("xl/drawings/drawing90.xml", group)
                before = self.path.read_bytes()
                result = check_image_alt_text(self.path)
                parent_target = (
                    "xl/drawings/drawing90.xml#xml=/wsDr[1]/twoCellAnchor[1]/grpSp[1]"
                    if case in ("missing_properties", "duplicate_properties")
                    else "xl/drawings/drawing90.xml#id=99"
                )
                self.assertEqual({f["target"]: f["classification"] for f in result}, {
                    parent_target: "MANUAL_REVIEW",
                    "xl/drawings/drawing90.xml#id=1": "REQUIRES_USER_INPUT",
                    "xl/drawings/drawing90.xml#id=3": "REQUIRES_USER_INPUT",
                })
                self.assertEqual(len(result.limitations), 1)
                repeated = check_image_alt_text(self.path)
                self.assertEqual(result, repeated)
                self.assertEqual(result.limitations, repeated.limitations)
                self.assertEqual(before, self.path.read_bytes())

    def test_group_decorative_flags_do_not_inherit_and_wrappers_stay_unselected(self):
        for flag in (None, "0", "false", "1", "true"):
            with self.subTest(flag=flag):
                self.write_metadata([("Budget", None, [
                    {}, {"title": "Complete", "descr": "Description"},
                ])])

                def group(root):
                    children = [anchor[0] for anchor in root]
                    for anchor in list(root):
                        root.remove(anchor)
                    anchor = ET.SubElement(root, f"{{{XDR}}}twoCellAnchor")
                    outer = ET.SubElement(anchor, f"{{{XDR}}}grpSp")
                    nv = ET.SubElement(outer, f"{{{XDR}}}nvGrpSpPr")
                    properties = ET.SubElement(nv, f"{{{XDR}}}cNvPr", {"id": "99"})
                    if flag is not None:
                        ext = ET.SubElement(properties, f"{{{DRAW}}}extLst")
                        ET.SubElement(ext, f"{{{DECORATIVE}}}decorative", {"val": flag})
                    outer.extend(children)
                    wrapper = ET.SubElement(outer, "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent")
                    ET.SubElement(wrapper, f"{{{XDR}}}pic")

                self.rewrite_part("xl/drawings/drawing90.xml", group)
                result = check_image_alt_text(self.path)
                expected = {
                    "xl/drawings/drawing90.xml#id=1": "REQUIRES_USER_INPUT",
                    "xl/drawings/drawing90.xml#xml=/wsDr[1]/twoCellAnchor[1]/grpSp[1]/AlternateContent[1]": "MANUAL_REVIEW",
                }
                if flag in ("1", "true"):
                    expected["xl/drawings/drawing90.xml#id=99"] = "MANUAL_REVIEW"
                self.assertEqual({f["target"]: f["classification"] for f in result}, expected)
                self.assertEqual(len(result.limitations), 2 if flag in ("1", "true") else 1)

    def test_missing_duplicate_ids_and_unsupported_objects_produce_reviews(self):
        for case in ("missing", "duplicate", "unknown", "background"):
            with self.subTest(case=case):
                self.write_metadata([("Budget", None, [{}, {}])])

                def change(root):
                    props = list(root.iter(f"{{{XDR}}}cNvPr"))
                    if case == "missing":
                        del props[1].attrib["id"]
                    elif case == "duplicate":
                        props[1].set("id", "1")
                    elif case == "unknown":
                        ET.SubElement(root[1], f"{{{XDR}}}unknownObject")
                    else:
                        ET.SubElement(
                            root, f"{{{MAIN}}}picture", {f"{{{DOC}}}id": "background"}
                        )

                part = (
                    "xl/worksheets/sheet17.xml"
                    if case == "background"
                    else "xl/drawings/drawing90.xml"
                )
                self.rewrite_part(part, change)
                before = self.path.read_bytes()
                findings = check_image_alt_text(self.path)
                self.assertEqual(self.path.read_bytes(), before)
                reviews = [
                    f for f in findings if f["classification"] == "MANUAL_REVIEW"
                ]
                expected_targets = {
                    "missing": [
                        "xl/drawings/drawing90.xml#xml=/wsDr[1]/twoCellAnchor[2]/pic[1]"
                    ],
                    "duplicate": [
                        f"xl/drawings/drawing90.xml#xml=/wsDr[1]/twoCellAnchor[{i}]/pic[1]"
                        for i in (1, 2)
                    ],
                    "unknown": [
                        "xl/drawings/drawing90.xml#xml=/wsDr[1]/twoCellAnchor[2]/unknownObject[1]"
                    ],
                    "background": [
                        "xl/worksheets/sheet17.xml#xml=/worksheet[1]/picture[1]"
                    ],
                }
                self.assertEqual([f["target"] for f in reviews], expected_targets[case])
                self.assertEqual(len(findings.limitations), len(reviews))
                for item, limitation in zip(reviews, findings.limitations):
                    self.assertIn(item["target"], limitation)
                    self.assertIn("Budget", limitation)
                # Other assessable objects retain their findings instead of being lost.
                self.assertEqual(
                    len(findings), 2 if case in ("missing", "duplicate") else 3
                )
                self.assertEqual(findings, check_image_alt_text(self.path))
                self.assertEqual(
                    findings.limitations, check_image_alt_text(self.path).limitations
                )

    def test_phase4_duplicate_pic_targets_match_shared_example(self):
        self.write_metadata([("Expenses", None, [{}, {}])])
        with ZipFile(self.path) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        drawing = ET.fromstring(parts.pop("xl/drawings/drawing90.xml"))
        for properties in drawing.iter(f"{{{XDR}}}cNvPr"):
            properties.set("id", "7")
        parts["xl/drawings/drawing1.xml"] = ET.tostring(drawing)
        relation_part = "xl/worksheets/_rels/sheet17.xml.rels"
        rels = ET.fromstring(parts[relation_part])
        rels[0].set("Target", "../drawings/drawing1.xml")
        parts[relation_part] = ET.tostring(rels)
        with ZipFile(self.path, "w") as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
        before = self.path.read_bytes()
        findings = check_image_alt_text(self.path)
        expected = [
            f"xl/drawings/drawing1.xml#xml=/wsDr[1]/twoCellAnchor[{i}]/pic[1]"
            for i in (1, 2)
        ]
        self.assertEqual([item["target"] for item in findings], expected)
        self.assertEqual(len({item["findingId"] for item in findings}), 2)
        source = hashlib.sha256(before).hexdigest()
        for item, target in zip(findings, expected):
            payload = json.dumps(
                [source, "2.0.0", "ALT_TEXT", "Expenses", target],
                ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8")
            self.assertEqual(item["findingId"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(item["ruleId"], "ALT_TEXT")
            self.assertEqual(item["category"], "NON_TEXT_CONTENT")
            self.assertEqual(item["classification"], "MANUAL_REVIEW")
        self.assertEqual(findings.limitations, [
            f"Expenses: {target}: Missing or duplicate drawing ID; indexed XML location used."
            for target in expected
        ])
        repeated = check_image_alt_text(self.path)
        self.assertEqual(findings, repeated)
        self.assertEqual(findings.limitations, repeated.limitations)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_and_duplicate_targets_for_each_supported_object_kind(self):
        for kind in ("pic", "sp", "cxnSp", "graphicFrame", "grpSp"):
            for case in ("missing", "duplicate"):
                with self.subTest(kind=kind, case=case):
                    initial_kind = "sp" if kind == "grpSp" else kind
                    self.write_metadata([("Budget", None, [{"kind": initial_kind}] * 2)])

                    def change(root):
                        if kind == "grpSp":
                            for anchor in root:
                                anchor[0].tag = f"{{{XDR}}}grpSp"
                                anchor[0][0].tag = f"{{{XDR}}}nvGrpSpPr"
                                ET.SubElement(anchor[0], f"{{{XDR}}}grpSpPr")
                        properties = list(root.iter(f"{{{XDR}}}cNvPr"))
                        if case == "missing":
                            del properties[0].attrib["id"]
                        else:
                            properties[1].set("id", "1")

                    self.rewrite_part("xl/drawings/drawing90.xml", change)
                    before = self.path.read_bytes()
                    findings = check_image_alt_text(self.path)
                    reviews = [f for f in findings if f["classification"] == "MANUAL_REVIEW"]
                    expected = [
                        f"xl/drawings/drawing90.xml#xml=/wsDr[1]/twoCellAnchor[{i}]/{kind}[1]"
                        for i in ((1,) if case == "missing" else (1, 2))
                    ]
                    self.assertEqual([f["target"] for f in reviews], expected)
                    self.assertEqual(len(findings.limitations), len(expected))
                    if case == "missing" and kind != "grpSp":
                        normal = [f for f in findings if f["classification"] == "REQUIRES_USER_INPUT"]
                        self.assertEqual([f["target"] for f in normal], ["xl/drawings/drawing90.xml#id=2"])
                    self.assertEqual(findings, check_image_alt_text(self.path))
                    self.assertEqual(self.path.read_bytes(), before)

    def test_nested_group_targets_use_each_child_object_and_preserve_unique_id(self):
        self.write_metadata([("Budget", None, [
            {}, {}, {"kind": "sp"}, {"kind": "cxnSp"}, {"kind": "graphicFrame"},
        ])])

        def group(root):
            children = [anchor[0] for anchor in root]
            for anchor in list(root):
                root.remove(anchor)
            anchor = ET.SubElement(root, f"{{{XDR}}}twoCellAnchor")
            outer = ET.SubElement(anchor, f"{{{XDR}}}grpSp")
            props = ET.SubElement(outer, f"{{{XDR}}}nvGrpSpPr")
            ET.SubElement(props, f"{{{XDR}}}cNvPr", {"name": "Missing group ID"})
            ET.SubElement(outer, f"{{{XDR}}}grpSpPr")
            children[1].find("{*}nvPicPr/{*}cNvPr").set("id", "1")
            for child in children[2:4]:
                del child.find("{*}*/{*}cNvPr").attrib["id"]
            outer.extend(children[:3])
            inner = ET.SubElement(outer, f"{{{XDR}}}grpSp")
            props = ET.SubElement(inner, f"{{{XDR}}}nvGrpSpPr")
            ET.SubElement(props, f"{{{XDR}}}cNvPr", {"id": "99"})
            ET.SubElement(inner, f"{{{XDR}}}grpSpPr")
            inner.append(children[3])
            outer.append(children[4])

        self.rewrite_part("xl/drawings/drawing90.xml", group)
        before = self.path.read_bytes()
        findings = check_image_alt_text(self.path)
        prefix = "xl/drawings/drawing90.xml#xml=/wsDr[1]/twoCellAnchor[1]/grpSp[1]"
        expected_reviews = [prefix + suffix for suffix in (
            "", "/grpSp[1]/cxnSp[1]", "/pic[1]", "/pic[2]", "/sp[1]",
        )]
        reviews = [f for f in findings if f["classification"] == "MANUAL_REVIEW"]
        self.assertEqual([f["target"] for f in reviews], expected_reviews)
        self.assertEqual(len(findings), 6)
        self.assertEqual(len({f["findingId"] for f in findings}), 6)
        self.assertEqual(findings[0]["target"], "xl/drawings/drawing90.xml#id=5")
        self.assertEqual(len(findings.limitations), 5)
        self.assertEqual(findings, check_image_alt_text(self.path))
        self.assertEqual(self.path.read_bytes(), before)

    def test_chartsheet_drawing_is_inspected(self):
        self.write_metadata([("Chart", "hidden", [{}])])

        def chartsheet_relationship(root):
            root[0].set("Type", f"{DOC}/chartsheet")

        self.rewrite_part("xl/_rels/workbook.xml.rels", chartsheet_relationship)
        findings = check_image_alt_text(self.path)
        self.assertEqual(
            [(f["worksheet"], f["target"]) for f in findings],
            [("Chart", "xl/drawings/drawing90.xml#id=1")],
        )

    def test_execution_failure_still_propagates(self):
        self.write_metadata([("Budget", None, [{}])])
        self.rewrite_part(
            "xl/worksheets/sheet17.xml",
            lambda root: root.find(f"{{{MAIN}}}drawing").set(f"{{{DOC}}}id", "missing"),
        )
        before = self.path.read_bytes()
        with self.assertRaises(KeyError):
            check_image_alt_text(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_wrapped_external_and_decorative_group_reviews(self):
        for case in ("wrapper", "external", "decorative_group"):
            with self.subTest(case=case):
                self.write_metadata([("Budget", None, [{}])])

                def change(root):
                    anchor = root[0]
                    if case == "wrapper":
                        anchor.tag = "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent"
                    elif case == "external":
                        blip = ET.SubElement(anchor[0], f"{{{DRAW}}}blip")
                        blip.set(f"{{{DOC}}}link", "externalImage")
                    else:
                        child = anchor[0]
                        anchor.remove(child)
                        group = ET.SubElement(anchor, f"{{{XDR}}}grpSp")
                        nv = ET.SubElement(group, f"{{{XDR}}}nvGrpSpPr")
                        props = ET.SubElement(nv, f"{{{XDR}}}cNvPr", {"id": "99"})
                        ext = ET.SubElement(
                            ET.SubElement(props, f"{{{DRAW}}}extLst"), f"{{{DRAW}}}ext"
                        )
                        ET.SubElement(
                            ext, f"{{{DECORATIVE}}}decorative", {"val": "true"}
                        )
                        group.append(child)

                self.rewrite_part("xl/drawings/drawing90.xml", change)
                if case == "external":
                    rels = relationships(
                        [
                            (
                                "externalImage",
                                "image",
                                "https://example.invalid/picture.png",
                            )
                        ]
                    )
                    rels[0].set("TargetMode", "External")
                    with ZipFile(self.path, "a") as archive:
                        archive.writestr(
                            "xl/drawings/_rels/drawing90.xml.rels", ET.tostring(rels)
                        )
                before = self.path.read_bytes()
                findings = check_image_alt_text(self.path)
                reviews = [
                    f for f in findings if f["classification"] == "MANUAL_REVIEW"
                ]
                self.assertEqual(len(reviews), 1)
                self.assertEqual(len(findings.limitations), 1)
                expected = {
                    "wrapper": "xl/drawings/drawing90.xml#xml=/wsDr[1]/AlternateContent[1]",
                    "external": "xl/drawings/drawing90.xml#id=1",
                    "decorative_group": "xl/drawings/drawing90.xml#id=99",
                }
                self.assertEqual(reviews[0]["target"], expected[case])
                self.assertEqual(len(findings), 2 if case == "decorative_group" else 1)
                self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
