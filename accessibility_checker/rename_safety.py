"""Read-only rename preflight for partial 2.4.2 Page Titled / 2.4.6 Headings
and Labels. Recognizes reference structure; does not rewrite or save anything.
"""

import posixpath
import re

from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.utils import FORMULAE
from openpyxl.utils.cell import column_index_from_string

from accessibility_checker import safe_xml
from accessibility_checker.coordinates import (
    cell_position,
    CoordinateError,
    MAX_ROW,
    MAX_COLUMN,
)
from accessibility_checker.part_ownership import (
    drawing_owners,
    internal_target,
    relationships,
    sheet_owners,
    referenced_part_owners,
)


# Finite structural profiles. Unknown constructs are disclosed, not guessed.
SHEET_TAGS = set(
    """worksheet chartsheet sheetPr tabColor outlinePr pageSetUpPr
dimension sheetViews sheetView selection pane sheetFormatPr cols col sheetData row
c f v is t r rPr rFont charset family b i strike outline shadow condense extend
color sz u vertAlign scheme rPh phoneticPr sheetCalcPr sheetProtection
protectedRanges protectedRange scenarios scenario inputCells autoFilter filterColumn
filters filter customFilters customFilter dynamicFilter colorFilter iconFilter
top10 sortState sortCondition mergeCells mergeCell conditionalFormatting cfRule
formula colorScale cfvo dataBar iconSet dataValidations dataValidation formula1
formula2 hyperlinks hyperlink printOptions pageMargins pageSetup headerFooter
oddHeader oddFooter evenHeader evenFooter firstHeader firstFooter rowBreaks
colBreaks brk drawing picture tableParts tablePart webPublishItems webPublishItem
sheetProtection sheetCalcPr""".split()
)
WORKBOOK_TAGS = set(
    """workbook fileVersion fileSharing workbookPr workbookProtection
bookViews workbookView sheets sheet definedNames definedName calcPr oleSize
customWorkbookViews customWorkbookView webPublishing fileRecoveryPr""".split()
)
DRAWING_TAGS = set(
    """wsDr twoCellAnchor oneCellAnchor absoluteAnchor from to pos ext
col colOff row rowOff pic sp cxnSp graphicFrame grpSp nvPicPr nvSpPr nvCxnSpPr
nvGraphicFramePr nvGrpSpPr cNvPr cNvPicPr cNvSpPr cNvCxnSpPr cNvGraphicFramePr
cNvGrpSpPr spPr grpSpPr xfrm blipFill style txBody clientData""".split()
)
CHART_TAGS = set(
    """chartSpace date1904 lang roundedCorners style chart title autoTitleDeleted
tx rich strRef strCache numRef numCache f v pt ptCount idx order ser cat val xVal
yVal bubbleSize multiLvlStrRef multiLvlStrCache lvl formatCode plotArea layout
manualLayout layoutTarget xMode yMode wMode hMode x y w h spPr txPr legend
legendPos legendEntry delete overlay printSettings headerFooter pageMargins pageSetup
barChart bar3DChart lineChart line3DChart areaChart area3DChart pieChart pie3DChart
doughnutChart ofPieChart scatterChart bubbleChart radarChart stockChart surfaceChart
surface3DChart dLbls dLbl showLegendKey showVal showCatName showSerName showPercent
showBubbleSize separator dLblPos grouping barDir varyColors gapWidth gapDepth overlap
axId catAx valAx dateAx serAx scaling logBase orientation max min axPos majorGridlines
minorGridlines numFmt majorTickMark minorTickMark tickLblPos crossAx crosses crossesAt
crossBetween auto lblAlgn lblOffset tickLblSkip tickMarkSkip noMultiLvlLbl
dispBlanksAs plotVisOnly showDLblsOverMax marker symbol size smooth trendline
trendlineType dispRSqr dispEq errBars errDir errBarType errValType noEndCap plus minus
explosion firstSliceAng holeSize splitType splitPos secondPieSize secondPiePt
custSplit wireframe bandFmts bandFmt shape pictureOptions pictureFormat pictureStackUnit
applyToFront applyToSides applyToEnd view3D rotX rotY rAngAx perspective depthPercent
hPercent floor sideWall backWall thickness upDownBars upBars downBars dropLines
hiLowLines serLines bubbleScale showNegBubbles sizeRepresents numLit strLit
baseTimeUnit majorUnit minorUnit majorTimeUnit minorTimeUnit dispUnits builtInUnit
custUnit dispUnitsLbl pivotSource name fmtId protection chartObject data formatting
selection userInterface pivotFmts pivotFmt""".split()
)
TABLE_TAGS = set(
    """table tableColumns tableColumn tableStyleInfo calculatedColumnFormula
totalsRowFormula autoFilter filterColumn filters filter customFilters customFilter
sortState sortCondition""".split()
)
A_TAGS = set(
    """graphic graphicData xfrm off ext chOff chExt ln solidFill noFill
gradFill gsLst gs schemeClr srgbClr sysClr scrgbClr prstClr hslClr tint shade
alpha alphaMod alphaOff lumMod lumOff satMod satOff hueMod hueOff comp inv gray
prstDash custDash ds round bevel miter headEnd tailEnd blip stretch fillRect tile
srcRect blipFill effectLst effectDag outerShdw innerShdw glow softEdge reflection
scene3d sp3d camera lightRig rot prstGeom avLst gd custGeom gdLst ahLst cxnLst
rect pathLst path moveTo lnTo cubicBezTo quadBezTo arcTo close pt
bodyPr lstStyle p pPr defRPr r rPr t endParaRPr latin ea cs sym hlinkClick hlinkMouseOver
fontRef lnRef fillRef effectRef style picLocks spLocks graphicFrameLocks grpSpLocks
cxnSpLocks stCxn endCxn extLst ext""".split()
)
METADATA_TAGS = {
    "styles": set(
        """styleSheet numFmts numFmt fonts font name rFont charset family
        b i u sz scheme strike outline shadow condense extend vertAlign color
        fills fill patternFill fgColor bgColor gradientFill stop borders border
        left right top bottom diagonal start end vertical horizontal cellStyleXfs
        xf alignment protection cellXfs cellStyles cellStyle dxfs dxf tableStyles
        tableStyle tableStyleElement colors indexedColors rgbColor mruColors""".split()
    ),
    "sharedStrings": set(
        "sst si t r rPr rFont charset family b i u sz scheme strike outline shadow condense extend vertAlign color rPh phoneticPr".split()
    ),
    "comments": set(
        "comments authors author commentList comment text t r rPr rFont charset family b i u sz scheme strike outline shadow condense extend vertAlign color rPh phoneticPr".split()
    ),
    "calcChain": {"calcChain", "c"},
    "theme": A_TAGS
    | set(
        """theme themeElements clrScheme dk1 lt1 dk2 lt2 accent1
        accent2 accent3 accent4 accent5 accent6 hlink folHlink fontScheme majorFont
        minorFont font fmtScheme fillStyleLst lnStyleLst effectStyleLst effectStyle
        bgFillStyleLst objectDefaults extraClrSchemeLst extraClrScheme clrMap
        custClrLst custClr bevelT bevelB alphaModFix sat lum hue invGamma gamma
        alphaBiLevel alphaCeiling alphaFloor grayscl biLevel duotone blur fillOverlay
        softEdge fillToRect lin path prstMaterial contourClr extrusionClr
        themeFamily""".split()
    ),
}
KNOWN_ATTRIBUTES = set(
    """name sheetId state id r s t ref sqref type val localSheetId
hidden title descr uri embed link space idx order si ca bx count showDropDown zoomToFit
allowBlank showErrorMessage showInputMessage errorStyle error errorTitle prompt
promptTitle imeMode operator priority dxfId stopIfTrue aboveAverage percent
bottom rank stdDev timePeriod text equalAverage anchor editAs fLocksWithSheet
fPrintsWithSheet colId min max width height customWidth bestFit outlineLevel
collapsed phonetic dyDescent customFormat ht customHeight spans thickTop thickBot
style sheet tabSelected workbookViewId zoomScale zoomScaleNormal view
showGridLines showRowColHeaders showZeros rightToLeft topLeftCell activeCell
activeCellId pane xSplit ySplit selection xWindow yWindow windowWidth windowHeight
activeTab firstSheet tabRatio visibility minimized showHorizontalScroll
showVerticalScroll showSheetTabs date1904 codeName filterMode published syncRef
syncHorizontal syncVertical transitionEvaluation transitionEntry enableFormatConditionsCalculation
summaryBelow summaryRight showOutlineSymbols applyStyles autoPageBreaks fitToPage
baseColWidth defaultColWidth defaultRowHeight zeroHeight thickBottom
horizontalCentered verticalCentered headings gridLines gridLinesSet blackAndWhite
left right top bottom header footer orientation paperSize scale fitToWidth
fitToHeight firstPageNumber useFirstPageNumber usePrinterDefaults copies
horizontalDpi verticalDpi errors cellComments draft pageOrder relId
display location tooltip targetMode autoFilterDateGrouping
calcId calcMode fullCalcOnLoad forceFullCalc calcCompleted calcOnSave
iterate iterateCount iterateDelta refMode concurrentCalc concurrentManualCount
appName lastEdited lowestEdited rupBuildId readOnlyRecommended userName
lockStructure lockWindows lockRevision workbookPassword revisionsPassword
displayName headerRowCount totalsRowCount totalsRowShown tableType tableId
totalsRowFunction totalsRowLabel uniqueName queryTableFieldId
showFirstColumn showLastColumn showRowStripes showColumnStripes
autoUpdate fullScreen personalView includePrintSettings includeHiddenRowCol
autoScale rotX rotY axId x y cx cy flipH flipV rot b i u sz lang dirty baseline
kern cap spc strike altLang kumimoji vert anchorCtr wrap lIns rIns tIns bIns
marL marR lvl indent algn defTabSz rtl eaLnBrk latinLnBrk hangingPunct
dist w h cmpd prst dash cap join noChangeAspect noChangeArrowheads
fPublished macro fmlaMacro fmlaLink fmlaPict fmlaTxbx textlink action endSnd
customHeight applyProtection protection locked scenarios objects selectLockedCells
selectUnlockedCells insertColumns insertRows deleteColumns deleteRows formatCells
formatColumns formatRows sort autoFilter pivotTables algorithmName hashValue saltValue spinCount
customWorkbookView lastView guid updateLinks showObjects backupFile saveExternalLinkValues
notAuto start end reversed scaleCrop linksUpToDate sharedDoc hyperlinksChanged
defaultThemeVersion filterPrivacy showInkAnnotation showPivotChartFilter
manualLayout showLegendKey showVal showCatName showSerName showPercent
formatCode sourceLinked xmlDataType dataDxfId headerRowDxfId totalsRowDxfId
connectionId published allowRefresh applyNumberFormats applyBorderFormats
ContentType PartName Extension""".split()
)
MAIN_NS = {
    "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "http://purl.oclc.org/ooxml/spreadsheetml/main",
}
CHART_NS = {
    "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "http://purl.oclc.org/ooxml/drawingml/chart",
}
DRAW_NS = {
    "http://schemas.openxmlformats.org/drawingml/2006/main",
    "http://purl.oclc.org/ooxml/drawingml/main",
}
XDR_NS = {
    "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "http://purl.oclc.org/ooxml/drawingml/spreadsheetDrawing",
}
DECORATIVE = "http://schemas.microsoft.com/office/drawing/2017/decorative"
NON_REFERENCE_KINDS = {
    "styles",
    "theme",
    "sharedStrings",
    "core-properties",
    "extended-properties",
    "custom-properties",
    "comments",
    "image",
    "thumbnail",
    "printerSettings",
    "calcChain",
}
SAFE_FUNCTIONS = frozenset(FORMULAE) | {"IMAGE"}


def _qualified_reference(value):
    """Split a token outside quoted sheet names, honoring doubled apostrophes."""
    quoted = False
    separator = None
    index = 0
    while index < len(value):
        if value[index] == "'":
            if quoted and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            quoted = not quoted
        elif value[index] == "!" and not quoted:
            if separator is not None:
                raise ValueError("Multiple sheet qualifiers")
            separator = index
        index += 1
    if quoted:
        raise ValueError("Unclosed quoted sheet name")
    if separator is None:
        return None, value
    qualifier, operand = value[:separator], value[separator + 1 :]
    if qualifier.startswith("'") and qualifier.endswith("'"):
        qualifier = qualifier[1:-1].replace("''", "'")
    elif "'" in qualifier:
        raise ValueError("Unsupported sheet quoting")
    return qualifier, operand


def _range_reason(value, sheets, names, scope):
    try:
        sheet, operand = _qualified_reference(value)
    except ValueError as error:
        return str(error)
    if "[" in value or "]" in value:
        return "External workbook or unsupported structured reference"
    if sheet is not None:
        if ":" in sheet:
            return "3D sheet reference"
        owners = [
            owner for owner in sheets if owner.name.casefold() == sheet.casefold()
        ]
        if len(owners) != 1:
            return "Unknown or ambiguous sheet qualifier"
        scope = owners[0].index
    bounds = operand.split(":")
    try:
        if len(bounds) in (1, 2) and all(
            re.fullmatch(r"\$?[A-Za-z]{1,3}\$?[0-9]+", item) for item in bounds
        ):
            for item in bounds:
                cell_position(item.replace("$", ""))
            return None
        if len(bounds) == 2 and all(
            re.fullmatch(r"\$?[A-Za-z]{1,3}", item) for item in bounds
        ):
            if all(
                column_index_from_string(item.replace("$", "").upper()) <= MAX_COLUMN
                for item in bounds
            ):
                return None
        if len(bounds) == 2 and all(
            re.fullmatch(r"\$?[0-9]{1,7}", item) for item in bounds
        ):
            if all(1 <= int(item.replace("$", "")) <= MAX_ROW for item in bounds):
                return None
    except (CoordinateError, ValueError):
        return "Reference outside the supported address bounds"
    key = operand.casefold()
    if (scope, key) in names or (None, key) in names:
        return None
    return "Unrecognized reference/name operand"


def formula_reason(text, sheets, names, scope=None):
    """Validate a token grammar and every reference; never evaluate a formula."""
    if not text:
        return "Empty or unsupported formula"
    try:
        tokens = Tokenizer(text if text.startswith("=") else "=" + text).items
    except (TokenizerError, IndexError) as error:
        return f"Unsupported formula tokenization ({type(error).__name__})"
    stack = []
    expect_operand = True
    previous = None
    for token in tokens:
        if token.type == "WHITE-SPACE":
            continue
        if token.type == "OPERAND":
            if not expect_operand:
                return "Unsupported adjacent operands/intersection"
            if token.subtype == "RANGE":
                reason = _range_reason(token.value, sheets, names, scope)
                if reason:
                    return reason
            elif token.subtype not in {"TEXT", "NUMBER", "LOGICAL", "ERROR"}:
                return "Unsupported formula operand"
            expect_operand = False
        elif token.type in {"FUNC", "PAREN"}:
            if token.subtype == "OPEN":
                if not expect_operand:
                    return "Unexpected formula opening token"
                if token.type == "FUNC":
                    function = token.value[:-1].upper()
                    if function in {"INDIRECT", "EVALUATE", "HYPERLINK"}:
                        return (
                            f"Reference construction or string destination: {function}"
                        )
                    if function not in SAFE_FUNCTIONS:
                        return f"Unsupported formula function/extension: {function}"
                stack.append(token.type)
                expect_operand = True
            else:
                if not stack or stack.pop() != token.type:
                    return "Unbalanced formula grouping"
                if expect_operand and token.type != "FUNC":
                    return "Empty formula group"
                if expect_operand and not (
                    previous is not None
                    and (
                        (previous.type == "FUNC" and previous.subtype == "OPEN")
                        or (previous.type == "SEP" and previous.subtype == "ARG")
                    )
                ):
                    return "Missing function operand"
                expect_operand = False
        elif token.type == "SEP" and token.subtype == "ARG":
            if not stack or stack[-1] != "FUNC":
                return "Unexpected function argument separator"
            expect_operand = True
        elif token.type == "OPERATOR-INFIX":
            if expect_operand:
                return "Missing formula operand"
            expect_operand = True
        elif token.type == "OPERATOR-PREFIX":
            if not expect_operand:
                return "Unexpected formula prefix"
        elif token.type == "OPERATOR-POSTFIX":
            if expect_operand:
                return "Missing postfix operand"
        else:
            return "Unsupported formula construct/array"
        previous = token
    if stack or expect_operand:
        return "Incomplete formula expression"
    return None


def rename_limitations(archive, root, workbook_relations):
    """Return stable whole-workbook blockers, or no blockers for the safe profile.

    Absence of blockers is structural preflight only, not proof that an editor
    exists or that serialized output would pass preservation/Excel inspection.
    """
    sheets = sheet_owners(root, workbook_relations)
    reasons = set()
    names = set()
    defined = root.findall("{*}definedNames/{*}definedName")
    for item in defined:
        scope = item.get("localSheetId")
        scope = None if scope is None else int(scope)
        key = (scope, item.attrib["name"].casefold())
        if key in names or (
            scope is not None and scope not in {s.index for s in sheets}
        ):
            reasons.add("Ambiguous defined-name scope")
        names.add(key)
    for item in defined:
        scope = item.get("localSheetId")
        reason = formula_reason(
            item.text, sheets, names, None if scope is None else int(scope)
        )
        if reason:
            reasons.add(f"xl/workbook.xml: defined name: {reason}")
    counts = {}
    if len({s.name.casefold() for s in sheets}) != len(sheets):
        reasons.add("Ambiguous case-insensitive sheet names")
    for sheet in sheets:
        if sheet.part is None:
            reasons.add("External sheet prevents complete reference inventory")
        else:
            counts.setdefault(sheet.part, set()).add(sheet.index)
    for part, owners in counts.items():
        if len(owners) > 1:
            reasons.add(
                f"{part}: multiple owning sheets make worksheet editing ambiguous"
            )
    for part, owners in drawing_owners(archive, sheets).items():
        if len(owners) > 1:
            reasons.add(
                f"{part}: shared drawing ownership prevents safe reference editing"
            )
    for part, owners in referenced_part_owners(
        archive, sheets, "tablePart", "table"
    ).items():
        if len(owners) > 1:
            reasons.add(
                f"{part}: shared table ownership prevents safe reference editing"
            )

    parts = {"xl/workbook.xml": "workbook"}
    parts.update({s.part: s.kind for s in sheets if s.part is not None})
    rel_paths = sorted(n for n in archive.namelist() if n.endswith(".rels"))
    for rel_path in rel_paths:
        directory, filename = posixpath.split(rel_path)
        parent = posixpath.join(posixpath.dirname(directory), filename[:-5])
        for rel in relationships(archive, parent).values():
            kind = rel.attrib["Type"].rsplit("/", 1)[-1]
            if kind == "hyperlink":
                if rel.get("TargetMode") != "External":
                    reason = _range_reason(
                        rel.attrib["Target"].removeprefix("#"), sheets, names, None
                    )
                    if reason:
                        reasons.add(f"{rel_path}: internal hyperlink: {reason}")
                continue
            if kind not in NON_REFERENCE_KINDS | {
                "officeDocument",
                "worksheet",
                "chartsheet",
                "drawing",
                "chart",
                "table",
            }:
                reasons.add(
                    f"{rel_path}: unsupported reference-bearing relationship: {kind}"
                )
                continue
            if rel.get("TargetMode") == "External":
                reasons.add(
                    f"{rel_path}: external {kind} prevents complete reference inventory"
                )
                continue
            target = internal_target(parent, rel)
            parts[target] = "workbook" if kind == "officeDocument" else kind

    # Minimal checker fixtures can omit package-level metadata. These known
    # non-reference parts remain understood even without a root relationship.
    parts.update(
        {
            n: kind
            for n, kind in (
                ("[Content_Types].xml", "contentTypes"),
                ("docProps/core.xml", "core-properties"),
                ("docProps/app.xml", "extended-properties"),
            )
            if n in archive.namelist()
        }
    )
    for part in sorted(parts):
        if part not in archive.namelist():
            archive.getinfo(part)  # Required missing structural parts remain failures.
    for part in sorted(archive.namelist()):
        if part.endswith("/") or part in rel_paths:
            continue
        if part.startswith("_xmlsignatures/"):
            reasons.add(f"{part}: signed package cannot be safely renamed")
            continue
        kind = parts.get(part)
        if kind is None:
            reasons.add(
                f"{part}: unrecognized/opaque package part may contain references"
            )
            continue
        if not part.endswith(".xml"):
            continue  # Known media/printer parts contain no Excel sheet references.
        with archive.open(part) as stream:
            stack = []
            for event, element in safe_xml.iterparse(stream, ("start", "end")):
                local = element.tag.rsplit("}", 1)[-1]
                namespace = (
                    element.tag[1:].split("}", 1)[0]
                    if element.tag.startswith("{")
                    else ""
                )
                if event == "start":
                    stack.append(element)
                    continue
                scope = next((s.index for s in sheets if s.part == part), None)
                if kind in NON_REFERENCE_KINDS - {
                    "core-properties",
                    "extended-properties",
                    "custom-properties",
                }:
                    if local in {"extLst", "ext", "AlternateContent"}:
                        reasons.add(
                            f"{part}: unrecognized metadata extension may contain references"
                        )
                    if namespace not in MAIN_NS | DRAW_NS | {
                        "http://schemas.openxmlformats.org/drawingml/2006/theme"
                    }:
                        reasons.add(f"{part}: unrecognized metadata namespace")
                    if kind in METADATA_TAGS and local not in METADATA_TAGS[kind]:
                        reasons.add(f"{part}: unrecognized metadata element: {local}")
                if kind not in NON_REFERENCE_KINDS | {"contentTypes"}:
                    allowed = {
                        "workbook": WORKBOOK_TAGS,
                        "worksheet": SHEET_TAGS,
                        "chartsheet": SHEET_TAGS,
                        "chart": CHART_TAGS,
                        "table": TABLE_TAGS,
                        "drawing": DRAWING_TAGS,
                    }[kind]
                    known = (
                        (
                            kind in {"workbook", "worksheet", "chartsheet", "table"}
                            and namespace in MAIN_NS
                            and local in allowed
                        )
                        or (
                            kind in {"chart", "drawing"}
                            and namespace in DRAW_NS
                            and local in A_TAGS
                        )
                        or (
                            kind == "chart"
                            and namespace in CHART_NS
                            and local in allowed
                        )
                        or (
                            kind == "drawing"
                            and namespace in XDR_NS
                            and local in allowed
                        )
                        or (
                            kind == "drawing"
                            and namespace in CHART_NS
                            and local == "chart"
                        )
                    )
                    if (
                        kind == "drawing"
                        and namespace == DECORATIVE
                        and local == "decorative"
                    ):
                        known = True
                    if kind == "drawing" and local in {"ext", "extLst"}:
                        known = namespace in DRAW_NS and (
                            local == "extLst"
                            or element.get("uri")
                            == "{C183D7F6-B498-43B3-948B-1728B52AA6E4}"
                        )
                        # xdr:ext (anchor size) is not an extension container.
                        known = known or (namespace in XDR_NS and local == "ext")
                    if not known:
                        reasons.add(
                            f"{part}: unsupported reference-bearing element: {local}"
                        )
                    for attribute in element.attrib:
                        attr_local = attribute.rsplit("}", 1)[-1]
                        if attr_local not in KNOWN_ATTRIBUTES:
                            reasons.add(
                                f"{part}: unsupported attribute on {local}: {attr_local}"
                            )
                        if attribute.startswith("{") and not attribute.startswith(
                            (
                                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}",
                                "{http://purl.oclc.org/ooxml/officeDocument/relationships}",
                                "{http://www.w3.org/XML/1998/namespace}",
                            )
                        ):
                            reasons.add(
                                f"{part}: unsupported namespaced attribute on {local}"
                            )
                    if local in {
                        "pivotSource",
                        "pivotFmts",
                        "pivotFmt",
                        "externalData",
                        "fld",
                    }:
                        reasons.add(
                            f"{part}: pivot/external/dynamic reference representation: {local}"
                        )
                    if local in {"hlinkClick", "hlinkMouseOver"} and element.get(
                        "action"
                    ):
                        reasons.add(f"{part}: unsupported drawing hyperlink action")
                    if any(
                        element.get(attribute)
                        for attribute in (
                            "macro",
                            "fmlaMacro",
                            "fmlaLink",
                            "fmlaPict",
                            "fmlaTxbx",
                            "textlink",
                            "connectionId",
                            "queryTableFieldId",
                        )
                    ):
                        reasons.add(
                            f"{part}: unsupported macro/query/object formula binding on {local}"
                        )
                    if local == "graphicData" and element.get("uri") not in CHART_NS:
                        reasons.add(f"{part}: unsupported drawing graphicData")
                    if local in {
                        "f",
                        "formula",
                        "formula1",
                        "formula2",
                        "calculatedColumnFormula",
                        "totalsRowFormula",
                    }:
                        if local == "f" and element.get("t", "normal") != "normal":
                            reasons.add(
                                f"{part}: shared/array/dynamic/data-table formula is outside rename profile"
                            )
                        else:
                            reason = formula_reason(element.text, sheets, names, scope)
                            if reason:
                                reasons.add(f"{part}: {reason}")
                    if local == "cfvo" and element.get("type") == "formula":
                        reason = formula_reason(
                            element.get("val"), sheets, names, scope
                        )
                        if reason:
                            reasons.add(f"{part}: conditional threshold: {reason}")
                    if local == "hyperlink" and element.get("location"):
                        reason = _range_reason(
                            element.get("location").removeprefix("#"),
                            sheets,
                            names,
                            scope,
                        )
                        if reason:
                            reasons.add(f"{part}: internal hyperlink: {reason}")
                stack.pop()
                if stack:
                    stack[-1].remove(element)
                element.clear()
    return tuple(sorted(reasons))
