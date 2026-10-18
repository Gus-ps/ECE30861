##  WCAG 2.1 Level A/AA checks for Excel workbooks.
##  Criteria come from ref/WCAG_2.1_Level_AA_Excel_Requirements.txt.
##  Not the Phase 3 pod oracle (see tester/suite for that); kept as the
##  Phase 4 verifier for remediated workbooks.
import colorsys
import html
import posixpath
import re
import struct
import zipfile
import xml.etree.ElementTree as ET

SC_NAMES = {
    "1.1.1": "Non-text Content",
    "1.3.1": "Info and Relationships",
    "1.3.2": "Meaningful Sequence",
    "1.3.3": "Sensory Characteristics",
    "1.4.1": "Use of Color",
    "1.4.3": "Contrast (Minimum)",
    "1.4.4": "Resize Text",
    "1.4.11": "Non-text Contrast",
    "2.1.1": "Keyboard",
    "2.1.2": "No Keyboard Trap",
    "2.1.4": "Character Key Shortcuts",
    "2.2.1": "Timing Adjustable",
    "2.2.2": "Pause, Stop, Hide",
    "2.4.2": "Page Titled",
    "2.4.3": "Focus Order",
    "2.4.4": "Link Purpose (In Context)",
    "2.4.6": "Headings and Labels",
    "2.5.3": "Label in Name",
    "3.1.1": "Language of Page",
    "3.2.1": "On Focus",
    "3.2.2": "On Input",
    "3.3.1": "Error Identification",
    "3.3.2": "Labels or Instructions",
    "3.3.3": "Error Suggestion",
    "4.1.2": "Name, Role, Value",
}
CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
DEFAULT_PALETTE = ("000000 FFFFFF FF0000 00FF00 0000FF FFFF00 FF00FF 00FFFF " * 2 +
                   "800000 008000 000080 808000 800080 008080 C0C0C0 808080 "
                   "9999FF 993366 FFFFCC CCFFFF 660066 FF8080 0066CC CCCCFF "
                   "000080 FF00FF FFFF00 00FFFF 800080 800000 008080 0000FF "
                   "00CCFF CCFFFF CCFFCC FFFF99 99CCFF FF99CC CC99FF FFCC99 "
                   "3366FF 33CCCC 99CC00 FFCC00 FF9900 FF6600 666699 969696 "
                   "003366 339966 003300 333300 993300 993366 333399 333333").split()
DEFAULT_SCHEME = {"dk1": "000000", "lt1": "FFFFFF", "dk2": "44546A", "lt2": "E7E6E6",
                  "accent1": "4472C4", "accent2": "ED7D31", "accent3": "A5A5A5",
                  "accent4": "FFC000", "accent5": "5B9BD5", "accent6": "70AD47",
                  "hlink": "0563C1", "folHlink": "954F72"}
THEME_INDEX = ["lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3",
               "accent4", "accent5", "accent6", "hlink", "folHlink"]
SCHEME_ALIAS = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}
PATTERN_WEIGHT = {"darkGray": 0.75, "mediumGray": 0.5, "lightGray": 0.25,
                  "gray125": 0.125, "gray0625": 0.0625}
CHART_TYPES = {"barChart", "bar3DChart", "lineChart", "line3DChart", "pieChart",
               "pie3DChart", "doughnutChart", "ofPieChart", "areaChart", "area3DChart",
               "scatterChart", "radarChart", "bubbleChart", "stockChart",
               "surfaceChart", "surface3DChart"}
PIE_TYPES = {"pieChart", "pie3DChart", "doughnutChart", "ofPieChart"}
LINE_TYPES = {"lineChart", "line3DChart", "scatterChart", "radarChart", "stockChart"}
CONTROL_KINDS = {"Button": "button", "CheckBox": "check box", "Drop": "drop-down",
                 "List": "list box", "Radio": "option button", "Spin": "spinner",
                 "Scroll": "scroll bar", "GBox": "group box", "Label": "label",
                 "EditBox": "edit box"}
DEFAULT_SHEET_NAME = re.compile(r"^(Sheet|Chart|Macro|Dialog)\s*\d+$", re.I)
DEFAULT_COLUMN_NAME = re.compile(r"^Column\d+$", re.I)
RAW_URL = re.compile(r"^(https?://|ftp://|www\.|mailto:|file:)", re.I)
GENERIC_LINK_TEXT = {"click here", "click", "here", "link", "this link", "more",
                     "read more", "learn more", "details", "info", "more info", "go",
                     "url", "website", "web site", "click this"}
SENSORY_PHRASES = re.compile(
    r"\b(red|green|blue|yellow|orange|purple|pink|gr[ae]y|colou?red|highlighted|shaded)"
    r"\s+(cells?|box(es)?|rows?|columns?|fields?|text|areas?|sections?|buttons?)\b"
    r"|\b(box|button|table|chart|section|cells?|column|area|image|shape)\s+(on|to|at)\s+the\s+"
    r"(left|right|top|bottom)\b"
    r"|\b(round|square|circular|triangular)\s+(buttons?|box(es)?|shapes?|icons?)\b", re.I)
CONTEXT_CHANGE = re.compile(
    r"\b(Sheets|Worksheets|Charts|Workbooks)\s*\([^)]*\)\s*\.\s*(Activate|Select)\b"
    r"|\bApplication\s*\.\s*Goto\b|\.\s*Show\b|\bFollowHyperlink\b"
    r"|\bWorkbooks\s*\.\s*(Open|Add)\b", re.I)
VBA_PROCEDURE = re.compile(
    r"^[ \t]*(?:(?:Public|Private|Friend)[ \t]+)?(?:Static[ \t]+)?(?:Sub|Function)[ \t]+(\w+)"
    r"[^\n]*\n(.*?)^[ \t]*End[ \t]+(?:Sub|Function)", re.M | re.S | re.I)


def is_on(value):
    return value in ("1", "true")

##  ---- Package / XML helpers ----

def strip_namespaces(root):
    ##  Drop namespaces (handles transitional and strict OOXML alike), keeping
    ##  relationship attributes as "r:<name>", then resolve mc:AlternateContent
    ##  to its first Choice so content isn't counted twice.
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
        for key in list(el.attrib):
            if "}" in key:
                ns, local = key[1:].split("}", 1)
                value = el.attrib.pop(key)
                el.attrib[("r:" + local) if ns.endswith("/relationships") else local] = value
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag != "AlternateContent":
                continue
            branch = None
            for tag in ("Choice", "Fallback"):
                branch = next((b for b in child if b.tag == tag), None)
                if branch is not None:
                    break
            index = list(parent).index(child)
            parent.remove(child)
            for offset, grandchild in enumerate(list(branch) if branch is not None else []):
                parent.insert(index + offset, grandchild)
    return root

def rel_of_type(rel_map, rel_type):
    return next((t for (kind, t, ext) in rel_map.values() if kind == rel_type and not ext), None)

def split_ref(ref):
    match = re.match(r"\$?([A-Za-z]+)\$?(\d+)", ref or "")
    if not match:
        return None
    col = 0
    for ch in match.group(1).upper():
        col = col * 26 + ord(ch) - 64
    return col, int(match.group(2))

def col_name(n):
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s

def cell_name(col, row):
    return f"{col_name(col)}{row}"

def compress(numbers, fmt=str):
    numbers = sorted(numbers)
    out = []
    start = prev = None
    for n in numbers + [None]:
        if start is None:
            start = prev = n
        elif n is not None and n == prev + 1:
            prev = n
        else:
            out.append(fmt(start) if start == prev else f"{fmt(start)}-{fmt(prev)}")
            start = prev = n
    return ", ".join(out)

class Workbook:
    ##  State shared by the checks for one workbook: the open package, the
    ##  resolved theme/styles, and the discrepancies found so far.
    def __init__(self, zf):
        self.zf = zf
        self.names = set(zf.namelist())
        self.issues = []
        self.notes = []
        self.scheme = {k: hexrgb(v) for k, v in DEFAULT_SCHEME.items()}
        self.palette = [hexrgb(v) for v in DEFAULT_PALETTE]
        self.fonts = []
        self.fills = []
        self.xfs = []
        self.dxfs = []
        self.shared_strings = []
        self.keyboard_macros = set()

    def add(self, sc, msg):
        self.issues.append((sc, msg))

    def load(self, part):
        if part not in self.names:
            return None
        try:
            return strip_namespaces(ET.fromstring(self.zf.read(part)))
        except ET.ParseError:
            self.notes.append(f"{part} is not well-formed XML and was skipped")
            return None

    def rels(self, part):
        rels_part = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
        out = {}
        root = self.load(rels_part)
        if root is None:
            return out
        for rel in root.iter("Relationship"):
            target = rel.get("Target", "")
            external = rel.get("TargetMode") == "External"
            if not external:
                if target.startswith("/"):
                    target = target[1:]
                else:
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
            out[rel.get("Id")] = (rel.get("Type", "").rsplit("/", 1)[-1], target, external)
        return out

##  ---- Color helpers ----

def hexrgb(value):
    try:
        value = value[-6:]
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (TypeError, ValueError):
        return None

def hexs(rgb):
    return "#%02X%02X%02X" % rgb

def adjust_lightness(rgb, func):
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    l = min(1.0, max(0.0, func(l)))
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l, s))

def luminance(rgb):
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

def ss_color(wb, el, default):
    ##  SpreadsheetML <color> / <fgColor> / <bgColor>
    if el is None or is_on(el.get("auto")):
        return default
    rgb = None
    try:
        if el.get("rgb"):
            rgb = hexrgb(el.get("rgb"))
        elif el.get("theme") is not None:
            index = int(el.get("theme"))
            rgb = wb.scheme.get(THEME_INDEX[index]) if index < len(THEME_INDEX) else None
        elif el.get("indexed") is not None:
            index = int(el.get("indexed"))
            rgb = wb.palette[index] if index < len(wb.palette) else None
        if rgb is None:
            return default
        tint = float(el.get("tint", 0))
    except ValueError:
        return default
    if tint < 0:
        rgb = adjust_lightness(rgb, lambda l: l * (1 + tint))
    elif tint > 0:
        rgb = adjust_lightness(rgb, lambda l: l * (1 - tint) + tint)
    return rgb

def dml_color(wb, parent):
    ##  DrawingML color choice inside a <solidFill>, <fgClr>, <gs>, ...
    if parent is None:
        return None
    for el in parent:
        if el.tag == "srgbClr":
            rgb = hexrgb(el.get("val"))
        elif el.tag == "sysClr":
            rgb = hexrgb(el.get("lastClr", "000000"))
        elif el.tag == "schemeClr":
            val = el.get("val", "")
            rgb = wb.scheme.get(SCHEME_ALIAS.get(val, val))
        else:
            continue
        if rgb is None:
            return None
        lum_mod, lum_off = 1.0, 0.0
        for mod in el:
            try:
                amount = int(mod.get("val", "100000")) / 100000
            except ValueError:
                continue
            if mod.tag == "lumMod":
                lum_mod = amount
            elif mod.tag == "lumOff":
                lum_off = amount
            elif mod.tag == "tint":
                rgb = tuple(round(c * amount + 255 * (1 - amount)) for c in rgb)
            elif mod.tag == "shade":
                rgb = tuple(round(c * amount) for c in rgb)
        if lum_mod != 1.0 or lum_off != 0.0:
            rgb = adjust_lightness(rgb, lambda l: l * lum_mod + lum_off)
        return rgb
    return None

def shape_fill(wb, sp_pr):
    ##  Returns an RGB tuple, "none" for noFill, or None when not specified.
    if sp_pr is None:
        return None
    if sp_pr.find("solidFill") is not None:
        return dml_color(wb, sp_pr.find("solidFill"))
    if sp_pr.find("noFill") is not None:
        return "none"
    if sp_pr.find("pattFill") is not None:
        return dml_color(wb, sp_pr.find("pattFill/fgClr"))
    if sp_pr.find("gradFill") is not None:
        return dml_color(wb, sp_pr.find("gradFill/gsLst/gs"))
    return None

def parse_fill(wb, fill):
    pattern = fill.find("patternFill")
    if pattern is not None:
        pattern_type = pattern.get("patternType", "none")
        if pattern_type == "none":
            return WHITE
        fg = ss_color(wb, pattern.find("fgColor"), BLACK)
        if pattern_type == "solid":
            return fg
        bg = ss_color(wb, pattern.find("bgColor"), WHITE)
        weight = PATTERN_WEIGHT.get(pattern_type, 0.5)
        return tuple(round(a * weight + b * (1 - weight)) for a, b in zip(fg, bg))
    gradient = fill.find("gradientFill")
    if gradient is not None:
        stops = [ss_color(wb, stop.find("color"), WHITE) for stop in gradient.findall("stop")]
        if stops:
            return tuple(round(sum(c[i] for c in stops) / len(stops)) for i in range(3))
    return WHITE

def parse_dxf(wb, dxf):
    if dxf is None:
        return None
    font = dxf.find("font")
    fill = dxf.find("fill")
    font_color = fill_color = None
    styled = False
    if font is not None:
        font_color = ss_color(wb, font.find("color"), None)
        for tag in ("b", "i", "u", "strike"):
            el = font.find(tag)
            if el is not None and el.get("val", "1") not in ("0", "false", "none"):
                styled = True
    if fill is not None:
        pattern = fill.find("patternFill")
        if pattern is not None and pattern.get("patternType", "solid") != "none":
            fill_color = ss_color(wb, pattern.find("bgColor"), None) or ss_color(wb, pattern.find("fgColor"), None)
    border = dxf.find("border")
    has_border = border is not None and any(side.get("style") for side in border)
    has_numfmt = dxf.find("numFmt") is not None
    return {"font": font_color, "fill": fill_color,
            "color_only": (font_color is not None or fill_color is not None)
            and not (styled or has_border or has_numfmt)}

def cell_format(wb, style_index):
    font_id, fill_id, _ = wb.xfs[style_index] if style_index < len(wb.xfs) else (0, 0, None)
    font = wb.fonts[font_id] if font_id < len(wb.fonts) else wb.fonts[0]
    fill = wb.fills[fill_id] if fill_id < len(wb.fills) else WHITE
    return font, fill

##  ---- VBA helpers (compound file + MS-OVBA decompression) ----

def cfb_streams(data):
    if data[:8] != CFB_SIGNATURE:
        return []
    sector_size = 1 << struct.unpack_from("<H", data, 0x1E)[0]
    mini_size = 1 << struct.unpack_from("<H", data, 0x20)[0]
    fat_count, dir_start = struct.unpack_from("<II", data, 0x2C)
    cutoff, minifat_start, minifat_count, difat_start, difat_count = struct.unpack_from("<IIIII", data, 0x38)
    per_sector = sector_size // 4

    def sector(i):
        return data[(i + 1) * sector_size:(i + 2) * sector_size]

    def unpack_all(blob):
        return list(struct.unpack("<%dI" % (len(blob) // 4), blob[:len(blob) // 4 * 4]))

    difat = list(struct.unpack_from("<109I", data, 0x4C))
    s = difat_start
    for _ in range(difat_count):
        if s >= 0xFFFFFFFA:
            break
        entries = unpack_all(sector(s))
        if len(entries) < per_sector:
            break
        difat.extend(entries[:-1])
        s = entries[-1]
    fat = []
    for s in difat[:fat_count]:
        if s < 0xFFFFFFFA:
            fat.extend(unpack_all(sector(s)))

    def chain(s, table):
        seen = set()
        while s < 0xFFFFFFFA and s < len(table) and s not in seen:
            seen.add(s)
            yield s
            s = table[s]

    def big_stream(s):
        return b"".join(sector(x) for x in chain(s, fat))

    directory = big_stream(dir_start)
    entries = []
    for o in range(0, len(directory) - 127, 128):
        name_len = struct.unpack_from("<H", directory, o + 64)[0]
        name = directory[o:o + max(min(name_len, 64) - 2, 0)].decode("utf-16-le", "ignore")
        left, right, child = struct.unpack_from("<III", directory, o + 68)
        start, size = struct.unpack_from("<II", directory, o + 116)
        entries.append((name, directory[o + 66], left, right, child, start, size))
    if not entries:
        return []
    mini_stream = big_stream(entries[0][5])
    minifat = unpack_all(big_stream(minifat_start)) if minifat_count else []

    def read(entry):
        if entry[6] < cutoff:
            return b"".join(mini_stream[x * mini_size:(x + 1) * mini_size]
                            for x in chain(entry[5], minifat))[:entry[6]]
        return big_stream(entry[5])[:entry[6]]

    out = []
    stack = [(entries[0][4], "")]
    seen = set()
    while stack:
        i, path = stack.pop()
        if i >= len(entries) or i in seen:
            continue
        seen.add(i)
        name, entry_type, left, right, child = entries[i][:5]
        stack += [(left, path), (right, path)]
        if entry_type == 1:
            stack.append((child, path + name + "/"))
        elif entry_type == 2:
            out.append((path + name, read(entries[i])))
    return out

def ovba_decompress(data):
    if not data or data[0] != 1:
        return b""
    out = bytearray()
    pos = 1
    while pos + 2 <= len(data):
        header = struct.unpack_from("<H", data, pos)[0]
        end = min(pos + (header & 0x0FFF) + 3, len(data))
        chunk_start = len(out)
        pos += 2
        if not header & 0x8000:
            out += data[pos:pos + 4096]
            pos += 4096
            continue
        while pos < end:
            flags = data[pos]
            pos += 1
            for bit in range(8):
                if pos >= end:
                    break
                if not flags & (1 << bit):
                    out.append(data[pos])
                    pos += 1
                    continue
                token = struct.unpack_from("<H", data, pos)[0]
                pos += 2
                bit_count = max((len(out) - chunk_start - 1).bit_length(), 4)
                offset = (token >> (16 - bit_count)) + 1
                length = (token & (0xFFFF >> bit_count)) + 3
                if offset > len(out):
                    raise ValueError("invalid copy token")
                for _ in range(length):
                    out.append(out[-offset])
        pos = end
    return bytes(out)

def vba_modules(data):
    modules = {}
    for path, blob in cfb_streams(data):
        pos = -1
        while True:
            pos = blob.find(b"\x00Attribut", pos + 1)
            if pos < 0:
                break
            if pos < 3 or blob[pos - 3] != 1:
                continue
            try:
                source = ovba_decompress(blob[pos - 3:])
            except (ValueError, IndexError, struct.error):
                continue
            if source.startswith(b"Attribute"):
                text = source.decode("latin-1")
                match = re.search(r'Attribute VB_Name = "([^"]+)"', text)
                modules[match.group(1) if match else path] = text
                break
    return modules

def macro_name(reference):
    return reference.split("!")[-1].split(".")[-1].strip("'\" ").lower()

def check_macro(wb, where, kind, name, reference):
    if reference and reference.strip() and macro_name(reference) not in wb.keyboard_macros:
        wb.add("2.1.1", f"{where}: {kind} '{name}' runs macro '{reference}' by mouse click only; "
                        f"no keyboard shortcut for that macro was found")

##  ---- GIF helper ----

def gif_animation(data):
    ##  Returns (frame count, frame delays in 1/100 s, loop count or None).
    if data[:3] != b"GIF" or len(data) < 13:
        return None
    pos = 13
    if data[10] & 0x80:
        pos += 3 * (2 << (data[10] & 7))
    frames, delays, loops, pending = 0, [], None, 0

    def skip_blocks(p):
        while p < len(data):
            n = data[p]
            p += 1
            if n == 0:
                break
            p += n
        return p

    while pos < len(data):
        block = data[pos]
        pos += 1
        if block == 0x3B:
            break
        if block == 0x21 and pos < len(data):
            label = data[pos]
            pos += 1
            if label == 0xF9 and pos + 4 <= len(data):
                pending = struct.unpack_from("<H", data, pos + 2)[0]
            elif label == 0xFF and data[pos + 1:pos + 12] == b"NETSCAPE2.0" and pos + 16 <= len(data):
                loops = struct.unpack_from("<H", data, pos + 14)[0]
            pos = skip_blocks(pos)
        elif block == 0x2C and pos + 9 <= len(data):
            frames += 1
            delays.append(pending)
            pending = 0
            packed = data[pos + 8]
            pos += 9
            if packed & 0x80:
                pos += 3 * (2 << (packed & 7))
            pos = skip_blocks(pos + 1)
        else:
            break
    return frames, delays, loops

##  ---- Workbook-level checks ----

def load_theme_and_styles(wb, workbook_rels):
    theme = wb.load(rel_of_type(workbook_rels, "theme") or "")
    if theme is not None:
        color_scheme = next(theme.iter("clrScheme"), None)
        if color_scheme is not None:
            for el in color_scheme:
                rgb = None
                for color in el:
                    rgb = hexrgb(color.get("val") if color.tag == "srgbClr" else color.get("lastClr"))
                    break
                if rgb is not None:
                    wb.scheme[el.tag] = rgb
    styles = wb.load(rel_of_type(workbook_rels, "styles") or "")
    if styles is not None:
        custom = styles.find("colors/indexedColors")
        if custom is not None:
            wb.palette = [hexrgb(c.get("rgb")) or BLACK for c in custom.findall("rgbColor")]
        for font in (styles.find("fonts") if styles.find("fonts") is not None else []):
            size = font.find("sz")
            bold = font.find("b")
            try:
                size = float(size.get("val")) if size is not None else 11.0
            except (TypeError, ValueError):
                size = 11.0
            wb.fonts.append({"size": size,
                             "bold": bold is not None and bold.get("val", "1") not in ("0", "false"),
                             "color": ss_color(wb, font.find("color"), BLACK)})
        for fill in (styles.find("fills") if styles.find("fills") is not None else []):
            wb.fills.append(parse_fill(wb, fill))
        for xf in (styles.find("cellXfs") if styles.find("cellXfs") is not None else []):
            wb.xfs.append((int(xf.get("fontId", 0)), int(xf.get("fillId", 0)), xf))
        for dxf in (styles.find("dxfs") if styles.find("dxfs") is not None else []):
            wb.dxfs.append(parse_dxf(wb, dxf))
    if not wb.fonts:
        wb.fonts.append({"size": 11.0, "bold": False, "color": BLACK})
    if not wb.fills:
        wb.fills.append(WHITE)

    sst = wb.load(rel_of_type(workbook_rels, "sharedStrings") or "")
    if sst is not None:
        for si in sst.findall("si"):
            parts = [si.find("t")] + [r.find("t") for r in si.findall("r")]
            wb.shared_strings.append("".join(t.text or "" for t in parts if t is not None))

def check_properties(wb, root_rels):
    ##  2.4.2 / 3.1.1: Document properties
    core = wb.load(rel_of_type(root_rels, "core-properties") or "docProps/core.xml")
    title = core.find("title") if core is not None else None
    if title is None or not (title.text or "").strip():
        wb.add("2.4.2", "Workbook has no Title document property (File > Info > Properties)")
    language = core.find("language") if core is not None else None
    if language is None or not (language.text or "").strip():
        wb.add("3.1.1", "Workbook has no Language document property (dc:language)")

def check_vba(wb, workbook_rels):
    ##  Part 2: workbooks with VBA macros
    vba_part = rel_of_type(workbook_rels, "vbaProject")
    if vba_part is None:
        vba_part = next((n for n in wb.names if n.lower().endswith("vbaproject.bin")), None)
    if not vba_part:
        return
    try:
        modules = vba_modules(wb.zf.read(vba_part))
    except (struct.error, IndexError, ValueError):
        modules = {}
    if not modules:
        wb.notes.append("the VBA project could not be read, so macro criteria "
                        "(2.1.x, 2.2.1, 3.2.x) were not verified")
    for module, source in modules.items():
        for match in re.finditer(r'Attribute\s+(\w+)\.VB_ProcData\.VB_Invoke_Func\s*=\s*"(.)\\n\d+"', source):
            if match.group(2).strip():
                wb.keyboard_macros.add(match.group(1).lower())
        code = re.sub(r"(?im)^[ \t]*('|Rem\b).*$", "", source)
        for match in re.finditer(r'\bOnKey\s*\(?\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?', code, re.I):
            key, target = match.group(1), match.group(2)
            if not target:
                continue
            wb.keyboard_macros.add(macro_name(target))
            modifiers = set()
            while key and key[0] in "^%+":
                modifiers.add(key[0])
                key = key[1:]
            if "^" not in modifiers and "%" not in modifiers and len(key) == 1:
                wb.add("2.1.4", f"VBA module '{module}' assigns the character key shortcut "
                                f"\"{match.group(1)}\" to '{target}' with Application.OnKey")
        for match in re.finditer(r"\bOnTime\b", code, re.I):
            wb.add("2.2.1", f"VBA module '{module}' sets a timer with Application.OnTime; no way to "
                            f"turn off, adjust or extend the time limit was found")
        for match in VBA_PROCEDURE.finditer(code):
            proc, body = match.group(1), match.group(2)
            lower = proc.lower()
            if lower in ("worksheet_selectionchange", "workbook_sheetselectionchange"):
                if CONTEXT_CHANGE.search(body) or re.search(r"\b(MsgBox|InputBox)\b", body, re.I):
                    wb.add("3.2.1", f"VBA module '{module}': {proc} changes context (switches sheet, "
                                    f"opens a dialog or workbook) when a cell receives focus")
            elif lower.endswith("_change") or lower == "workbook_sheetchange":
                if CONTEXT_CHANGE.search(body):
                    wb.add("3.2.2", f"VBA module '{module}': {proc} changes context (switches sheet, "
                                    f"opens a form or workbook) when a value is changed")
            elif lower.endswith("_queryclose"):
                if re.search(r"\bCancel\s*=\s*(True|1|-1)\b", body, re.I):
                    wb.add("2.1.2", f"VBA module '{module}': {proc} cancels closing the form, which can "
                                    f"trap keyboard users (Esc / close is blocked)")

def check_media(wb):
    ##  2.2.2: Animated images
    for name in sorted(wb.names):
        if name.lower().startswith("xl/media/") and name.lower().endswith(".gif"):
            info = gif_animation(wb.zf.read(name))
            if not info or info[0] < 2:
                continue
            frames, delays, loops = info
            cycle = sum(d if d > 1 else 10 for d in delays) / 100
            if loops == 0 or cycle * ((loops or 0) + 1) > 5:
                length = "loops forever" if loops == 0 else f"plays for {cycle * ((loops or 0) + 1):.1f}s"
                wb.add("2.2.2", f"Animated image {name} ({frames} frames) {length} and Excel provides "
                                f"no way to pause, stop or hide it")

def check_workbook(wb):
    ##  Runs every check; returns a reason string if the file can't be tested at all.
    root_rels = wb.rels("")
    workbook_part = rel_of_type(root_rels, "officeDocument") or "xl/workbook.xml"
    workbook = wb.load(workbook_part)
    if workbook is None:
        return "not a valid Excel workbook (no workbook part found)"
    workbook_rels = wb.rels(workbook_part)

    load_theme_and_styles(wb, workbook_rels)
    check_properties(wb, root_rels)
    check_vba(wb, workbook_rels)

    for sheet in workbook.iter("sheet"):
        sheet_name = sheet.get("name", "")
        where = f"Sheet '{sheet_name}'"
        if sheet.get("state") in ("hidden", "veryHidden"):
            continue
        rel = workbook_rels.get(sheet.get("r:id"))
        part = rel[1] if rel else None
        root = wb.load(part) if part else None
        if root is None:
            wb.notes.append(f"{where} could not be read")
            continue
        try:
            check_sheet(wb, sheet_name, where, part, root)
        except (ValueError, KeyError, IndexError, TypeError) as error:
            wb.notes.append(f"{where} could not be fully tested ({error})")

    check_media(wb)
    return None

##  ---- Chart checks ----

def check_chart(wb, chart_part, label):
    space = wb.load(chart_part)
    if space is None:
        return
    chart = space.find("chart")
    if chart is None:
        return
    plot = chart.find("plotArea")
    groups = [g for g in plot if g.tag in CHART_TYPES] if plot is not None else []
    series_count = sum(len(g.findall("ser")) for g in groups)

    title_deleted = chart.find("autoTitleDeleted")
    title_deleted = title_deleted is not None and is_on(title_deleted.get("val", "1"))
    if chart.find("title") is None and (title_deleted or series_count != 1):
        wb.add("2.4.6", f"{label} has no chart title")

    if plot is not None:
        for axis in plot:
            if axis.tag not in ("catAx", "valAx", "dateAx"):
                continue
            deleted = axis.find("delete")
            if deleted is not None and is_on(deleted.get("val", "1")):
                continue
            position = axis.find("axPos")
            position = position.get("val") if position is not None else ""
            direction = "horizontal" if position in ("b", "t") else "vertical" if position in ("l", "r") else axis.tag
            if axis.find("title") is None:
                wb.add("2.4.6", f"{label} has no {direction} axis title")

    background = WHITE
    for sp_pr in (space.find("spPr"), plot.find("spPr") if plot is not None else None):
        fill = shape_fill(wb, sp_pr)
        if isinstance(fill, tuple):
            background = fill
    accents = [wb.scheme[f"accent{i}"] for i in range(1, 7)]

    for group in groups:
        is_pie = group.tag in PIE_TYPES
        is_line = group.tag in LINE_TYPES
        series = group.findall("ser")
        vary = group.find("varyColors")
        vary = is_on(vary.get("val", "1")) if vary is not None else is_pie

        named_labels = any(
            is_on(el.get("val", "1"))
            for lbls in group.iter("dLbls")
            for el in lbls
            if el.tag in ("showSerName", "showCatName"))
        patterned = any(True for _ in group.iter("pattFill"))
        markers = False
        if is_line:
            symbols = [el.get("val") for el in group.iter("symbol")]
            if symbols:
                markers = any(val != "none" for val in symbols)
            else:
                marker = group.find("marker")
                style = group.find("scatterStyle")
                radar = group.find("radarStyle")
                markers = ((marker is not None and is_on(marker.get("val", "1")))
                           or (style is not None and style.get("val") in ("lineMarker", "marker"))
                           or (radar is not None and radar.get("val") == "marker"))
        points = 0
        if series:
            count = series[0].find("val//ptCount")
            if count is not None and (count.get("val") or "").isdigit():
                points = int(count.get("val"))
        if (len(series) > 1 or (is_pie and vary and points > 1)) and not (named_labels or patterned or markers):
            what = "slices" if is_pie else "series"
            wb.add("1.4.1", f"{label}: {what} are distinguished by color only "
                            f"(no series/category data labels, patterns or markers)")

        for position, ser in enumerate(series):
            idx = ser.find("idx")
            idx = int(idx.get("val", position)) if idx is not None else position
            tx = ser.find("tx")
            name = next((v.text for v in tx.iter("v")), None) if tx is not None else None
            name = name or f"Series {idx + 1}"
            colors = []
            if is_pie and vary:
                explicit = {}
                for point in ser.findall("dPt"):
                    pidx = point.find("idx")
                    if pidx is not None:
                        explicit[int(pidx.get("val", 0))] = shape_fill(wb, point.find("spPr"))
                for p in range(max(points, len(explicit))):
                    color = explicit.get(p) or accents[p % 6]
                    colors.append((f"slice {p + 1} of '{name}'", color))
            else:
                sp_pr = ser.find("spPr")
                if is_line:
                    color = shape_fill(wb, sp_pr.find("ln")) if sp_pr is not None and sp_pr.find("ln") is not None else None
                    if color == "none":
                        color = shape_fill(wb, ser.find("marker/spPr"))
                else:
                    color = shape_fill(wb, sp_pr)
                colors.append((f"series '{name}'", color or accents[idx % 6]))
            for what, color in colors:
                if not isinstance(color, tuple):
                    continue
                ratio = contrast(color, background)
                if ratio < 3:
                    wb.add("1.4.11", f"{label}: {what} color {hexs(color)} has a contrast ratio of "
                                     f"{ratio:.2f}:1 against the background {hexs(background)} (minimum 3:1)")

##  ---- Sheet checks ----

def check_link(wb, where, ref, text, target):
    ##  2.4.4: Hyperlink text
    stripped = (text or "").strip()
    if not stripped:
        wb.add("2.4.4", f"{where} cell {ref}: hyperlink has no display text")
    elif RAW_URL.match(stripped) or (target and stripped.lower().rstrip("/") == target.lower().rstrip("/")):
        wb.add("2.4.4", f"{where} cell {ref}: hyperlink displays a raw address (\"{stripped[:80]}\") "
                        f"instead of descriptive text")
    elif stripped.lower().strip(".!:> ") in GENERIC_LINK_TEXT:
        wb.add("2.4.4", f"{where} cell {ref}: hyperlink text \"{stripped}\" does not describe its destination")

def check_sheet(wb, sheet_name, where, part, root):
    sheet_rels = wb.rels(part)

    ##  2.4.2: Sheet name
    if DEFAULT_SHEET_NAME.match(sheet_name.strip()):
        wb.add("2.4.2", f"{where} has a default name; give it a descriptive tab name")

    ##  Cells
    cells = {}
    hidden_rows, hidden_cols, row_heights = set(), set(), {}
    next_row = 1
    for row in root.iter("row"):
        r = int(row.get("r", next_row))
        next_row = r + 1
        if is_on(row.get("hidden")):
            hidden_rows.add(r)
        if is_on(row.get("customHeight")) and row.get("ht"):
            row_heights[r] = float(row.get("ht"))
        next_col = 1
        for c in row.findall("c"):
            ref = split_ref(c.get("r"))
            col = ref[0] if ref else next_col
            next_col = col + 1
            value = c.find("v")
            formula = c.find("f")
            cell_type = c.get("t")
            if cell_type == "inlineStr":
                text = "".join(t.text or "" for t in c.iter("t"))
            elif value is None or value.text is None:
                continue
            elif cell_type == "s":
                index = int(value.text)
                text = wb.shared_strings[index] if index < len(wb.shared_strings) else ""
            else:
                text = value.text
            if text == "":
                continue
            cells[(col, r)] = (text, int(c.get("s", 0)),
                               formula.text if formula is not None and formula.text else "")
    for col in root.iter("col"):
        if is_on(col.get("hidden")):
            hidden_cols.update(range(int(col.get("min", 1)), int(col.get("max", col.get("min", 1))) + 1))

    tables = []
    for tp in root.iter("tablePart"):
        rel = sheet_rels.get(tp.get("r:id"))
        table = wb.load(rel[1]) if rel else None
        if table is not None:
            tables.append(table)

    ##  Controls (form controls and ActiveX)
    control_ids = set()
    captions = {}
    for legacy in root.iter("legacyDrawing"):
        rel = sheet_rels.get(legacy.get("r:id"))
        if rel and rel[1] in wb.names:
            vml = wb.zf.read(rel[1]).decode("utf-8", "ignore")
            for match in re.finditer(r'<v:shape\b[^>]*?\bid="_x0000_s(\d+)"[^>]*>(.*?)</v:shape>', vml, re.S | re.I):
                box = re.search(r"<v:textbox\b[^>]*>(.*?)</v:textbox>", match.group(2), re.S | re.I)
                if box:
                    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", box.group(1))).split())
                    if text:
                        captions[int(match.group(1))] = text
    for control in root.iter("control"):
        try:
            shape_id = int(control.get("shapeId", -1))
        except ValueError:
            shape_id = -1
        if shape_id in control_ids:
            continue
        control_ids.add(shape_id)
        name = control.get("name", f"control {shape_id}")
        props = control.find("controlPr")
        alt = (props.get("altText") or "").strip() if props is not None else ""
        rel = sheet_rels.get(control.get("r:id"))
        kind = "control"
        if rel and "activeX" in rel[1]:
            kind = "ActiveX control"
        elif rel:
            ctrl_props = wb.load(rel[1])
            if ctrl_props is not None:
                kind = CONTROL_KINDS.get(ctrl_props.get("objectType"), "form control")
        if not alt:
            wb.add("4.1.2", f"{where}: {kind} '{name}' has no accessible name (alt text); also fails 1.1.1")
        caption = captions.get(shape_id)
        if caption and alt and caption.lower() not in alt.lower():
            wb.add("2.5.3", f"{where}: {kind} '{name}' shows the label \"{caption}\" but its accessible "
                            f"name \"{alt}\" does not contain it")
        if props is not None:
            check_macro(wb, where, kind, name, props.get("macro"))

    ##  Drawing objects (images, charts, shapes, text boxes, SmartArt)
    object_count = 0
    for drawing in root.iter("drawing"):
        rel = sheet_rels.get(drawing.get("r:id"))
        drawing_part = rel[1] if rel else None
        drawing_root = wb.load(drawing_part) if drawing_part else None
        if drawing_root is None:
            continue
        drawing_rels = wb.rels(drawing_part)
        for anchor in drawing_root:
            obj = next((el for el in anchor if el.tag in
                        ("sp", "pic", "graphicFrame", "grpSp", "cxnSp", "contentPart")), None)
            if obj is None:
                continue
            props = obj.find("./*/cNvPr")
            if props is None:
                continue
            try:
                object_id = int(props.get("id", -1))
            except ValueError:
                object_id = -1
            if object_id in control_ids or is_on(props.get("hidden")):
                continue
            object_count += 1
            name = props.get("name", f"object {object_id}")
            chart_ref = next((el for el in obj.iter("chart") if el.get("r:id")), None)
            if obj.tag == "pic":
                kind = "picture"
            elif obj.tag == "graphicFrame":
                kind = "chart" if chart_ref is not None else "SmartArt/graphic"
            elif obj.tag == "grpSp":
                kind = "group"
            elif obj.tag == "cxnSp":
                kind = "connector"
            elif obj.find("./nvSpPr/cNvSpPr") is not None and is_on(obj.find("./nvSpPr/cNvSpPr").get("txBox")):
                kind = "text box"
            else:
                kind = "shape"
            decorative = any(el.tag == "decorative" and is_on(el.get("val", "1")) for el in props.iter())
            if not (props.get("descr") or "").strip() and not decorative:
                wb.add("1.1.1", f"{where}: {kind} '{name}' has no alt text and is not marked as decorative")
            check_macro(wb, where, kind, name, obj.get("macro"))
            if chart_ref is not None:
                chart_rel = drawing_rels.get(chart_ref.get("r:id"))
                if chart_rel:
                    check_chart(wb, chart_rel[1], f"{where}: chart '{name}'")

    if root.tag != "worksheet":
        return

    visible = {k: v for k, v in cells.items() if k[0] not in hidden_cols and k[1] not in hidden_rows}

    ##  2.4.2: Blank sheet
    if not cells and object_count == 0 and not tables:
        wb.add("2.4.2", f"{where} is blank; remove unused sheets")
        return

    ##  1.3.1: Merged cells
    for merge in root.iter("mergeCell"):
        wb.add("1.3.1", f"{where}: merged cells {merge.get('ref')}")

    ##  1.3.1 / 2.4.6: Tables
    for table in tables:
        table_name = table.get("displayName") or table.get("name") or "table"
        if table.get("headerRowCount") == "0":
            wb.add("1.3.1", f"{where}: table '{table_name}' ({table.get('ref')}) has no header row")
        else:
            for column in table.iter("tableColumn"):
                if DEFAULT_COLUMN_NAME.match((column.get("name") or "").strip()):
                    wb.add("2.4.6", f"{where}: table '{table_name}' has a blank or default column "
                                    f"header '{column.get('name')}'")
    if cells:
        rows = {r for (_, r) in cells}
        cols = {c for (c, _) in cells}
        if not tables and len(rows) > 1 and len(cols) > 1:
            wb.add("1.3.1", f"{where}: data is not formatted as an Excel Table with a header row")
        blank_rows = set(range(min(rows), max(rows) + 1)) - rows - hidden_rows
        if blank_rows:
            wb.add("1.3.1", f"{where}: blank row(s) {compress(blank_rows)} inside the used range")
        blank_cols = set(range(min(cols), max(cols) + 1)) - cols - hidden_cols
        if blank_cols:
            wb.add("1.3.1", f"{where}: blank column(s) {compress(blank_cols, col_name)} inside the used range")

        ##  1.3.2 / 2.4.3: Content should start at A1
        if min(rows) != 1 or min(cols) != 1:
            wb.add("1.3.2", f"{where}: content starts at {cell_name(min(cols), min(rows))} instead of A1, "
                            f"so the reading and focus order begins on empty cells (also 2.4.3)")

    ##  1.4.3: Text contrast, 1.4.4: clipped rows, 1.3.3: sensory instructions
    failures = {}
    row_font = {}
    for (col, r), (text, style, formula) in sorted(visible.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        font, fill = cell_format(wb, style)
        row_font[r] = max(row_font.get(r, 0), font["size"])
        if not text.strip():
            continue
        large = font["size"] >= 18 or (font["bold"] and font["size"] >= 14)
        minimum = 3.0 if large else 4.5
        ratio = contrast(font["color"], fill)
        if ratio < minimum:
            failures.setdefault((font["color"], fill, minimum, round(ratio, 2)), []).append(cell_name(col, r))
        if SENSORY_PHRASES.search(text):
            wb.add("1.3.3", f"{where} cell {cell_name(col, r)}: instructions rely on color, shape or "
                            f"position (\"{text.strip()[:80]}\")")
    for (fg, bg, minimum, ratio), refs in failures.items():
        wb.add("1.4.3", f"{where} cell(s) {', '.join(refs)}: text {hexs(fg)} on {hexs(bg)} has a contrast "
                        f"ratio of {ratio:.2f}:1 (minimum {minimum:g}:1)")
    for r, height in sorted(row_heights.items()):
        if r in hidden_rows or height <= 0 or r not in row_font:
            continue
        if height < row_font[r] * 1.2:
            wb.add("1.4.4", f"{where} row {r}: fixed row height {height:g}pt is too small for "
                            f"{row_font[r]:g}pt text, so text is clipped")

    ##  2.4.4: Hyperlinks
    linked = set()
    for link in root.iter("hyperlink"):
        ref = (link.get("ref") or "").split(":")[0]
        pos = split_ref(ref)
        if not pos:
            continue
        linked.add(pos)
        rel = sheet_rels.get(link.get("r:id"))
        target = rel[1] if rel else link.get("location", "")
        text = cells[pos][0] if pos in cells else link.get("display", "")
        check_link(wb, where, ref, text, target)
    for pos, (text, _, formula) in cells.items():
        if pos in linked or not re.match(r"\s*(_xlfn\.)?HYPERLINK\s*\(", formula, re.I):
            continue
        target = re.search(r'HYPERLINK\s*\(\s*"([^"]*)"', formula, re.I)
        check_link(wb, where, cell_name(*pos), text, target.group(1) if target else "")

    ##  1.4.1 / 1.4.3: Conditional formatting
    for cf in root.iter("conditionalFormatting"):
        sqref = cf.get("sqref") or (cf.find("sqref").text if cf.find("sqref") is not None else "")
        for rule in cf.iter("cfRule"):
            rule_type = rule.get("type", "")
            if rule_type == "colorScale":
                wb.add("1.4.1", f"{where} {sqref}: color scale conditional formatting conveys values by color only")
                continue
            dxf = parse_dxf(wb, rule.find("dxf"))
            if dxf is None and rule.get("dxfId") is not None:
                index = int(rule.get("dxfId"))
                dxf = wb.dxfs[index] if index < len(wb.dxfs) else None
            if dxf is None:
                continue
            if dxf["color_only"]:
                wb.add("1.4.1", f"{where} {sqref}: conditional formatting rule ({rule_type}) changes only "
                                f"color; add text, a symbol, an icon or a font style as well")
            fg, bg = dxf["font"] or BLACK, dxf["fill"] or WHITE
            ratio = contrast(fg, bg)
            if ratio < 4.5:
                wb.add("1.4.3", f"{where} {sqref}: conditional formatting rule ({rule_type}) shows text "
                                f"{hexs(fg)} on {hexs(bg)} with a contrast ratio of {ratio:.2f}:1 (minimum 4.5:1)")

    ##  3.3.1 / 3.3.2 / 3.3.3: Data validation (input cells)
    for dv in root.iter("dataValidation"):
        sqref = dv.get("sqref") or (dv.find("sqref").text if dv.find("sqref") is not None else "")
        if not sqref:
            continue
        validates = dv.get("type", "none") != "none"
        message = (dv.get("error") or "").strip()
        prompt = (dv.get("prompt") or "").strip() if is_on(dv.get("showInputMessage")) else ""
        if validates:
            if not is_on(dv.get("showErrorMessage")):
                wb.add("3.3.1", f"{where} {sqref}: data validation error alert is turned off, so invalid "
                                f"entries are not identified to the user")
            elif not message:
                wb.add("3.3.1", f"{where} {sqref}: data validation uses Excel's generic error alert, which "
                                f"does not describe the error")
                wb.add("3.3.3", f"{where} {sqref}: data validation error alert gives no suggestion for "
                                f"correcting the entry")
        for area in sqref.split():
            start = split_ref(area.split(":")[0])
            if not start:
                continue
            col, r = start
            labelled = (any((c, r) in cells for c in range(1, col))
                        or any((col, rr) in cells for rr in range(1, r)))
            if not labelled and not prompt:
                wb.add("3.3.2", f"{where} {area}: input cell has no visible label or input message")

def testFile(infile, filename):
    ##  Tests an Excel workbook (.xlsx / .xlsm) against the automatable WCAG 2.1
    ##  Level A/AA criteria. Every discrepancy found is recorded, not just the first one.
    line = ""
    fatal = None
    issues, notes = [], []
    with open(infile, "rb") as file:
        line = line + filename
        head = file.read(8)
        file.seek(0)
        if head == CFB_SIGNATURE:
            fatal = "file is encrypted or in legacy .xls format and cannot be tested"
        else:
            try:
                zf = zipfile.ZipFile(file)
            except zipfile.BadZipFile:
                fatal = "not a valid Excel workbook (.xlsx / .xlsm)"
            else:
                with zf:
                    wb = Workbook(zf)
                    try:
                        fatal = check_workbook(wb)
                    except Exception as error:
                        wb.notes.append(f"testing stopped early because of an unexpected error: {error!r}")
                    issues, notes = wb.issues, wb.notes

    if fatal:
        line = line + " failed: " + fatal
    elif issues:
        issues.sort(key=lambda issue: tuple(int(p) for p in issue[0].split(".")))
        line = line + f" failed: {len(issues)} issue(s)"
        for sc, msg in issues:
            line = line + f"\n- [{sc} {SC_NAMES[sc]}] {msg}"
    else:
        line = line + " passed"
    for note in notes:
        line = line + f"\n- Note: {note}"
    return(line + "\n")
