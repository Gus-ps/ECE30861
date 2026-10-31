"""1.4.1 Use of Color / 1.4.3 Contrast (Minimum): read-only static styles.

No accessibility verdict, rendering, formula execution or workbook saving.
Frozen fallback palette follows corrected context pack 2.1.1.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from accessibility_checker import safe_xml
from accessibility_checker.cell_reader import _namespace, _part, _relationships
from accessibility_checker.color_palette import INDEXED_RGB
from accessibility_checker.coordinates import canonical_range
from accessibility_checker.worksheet_features import contains, worksheet_features


class UnsupportedRendering(ValueError):
    """Valid stored rendering cannot be resolved under the screening profile."""


@dataclass(frozen=True)
class StaticStyle:
    font_rgb: tuple[int, int, int]
    fill_rgb: tuple[int, int, int]
    size: Decimal
    bold: bool
    font_name: str | None
    assumptions: tuple[str, ...] = ()


def rgb(value):
    if (
        not isinstance(value, str)
        or re.fullmatch(r"(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", value) is None
    ):
        raise UnsupportedRendering("Color has no supported concrete RGB value.")
    return tuple(int(value[-6:][offset : offset + 2], 16) for offset in (0, 2, 4))


def tinted(color, tint):
    """Exact rational HSL lightness transform; final channels use half-up rounding."""
    t = Decimal(str(tint))
    if not t.is_finite() or not -1 <= t <= 1:
        raise UnsupportedRendering("Tint is outside -1..1.")
    t = Fraction(t)
    channels = [Fraction(c, 255) for c in color]
    low, high = min(channels), max(channels)
    lightness = (high + low) / 2
    adjusted = lightness * (1 + t) if t < 0 else lightness * (1 - t) + t
    if high == low:
        output = [adjusted] * 3
    else:
        chroma = high - low
        saturation = chroma / (1 - abs(2 * lightness - 1))
        new_chroma = (1 - abs(2 * adjusted - 1)) * saturation
        offset = adjusted - new_chroma / 2
        output = [(channel - low) / chroma * new_chroma + offset for channel in channels]
    values = [max(Fraction(0), min(Fraction(1), channel)) * 255 for channel in output]
    return tuple((2 * v.numerator + v.denominator) // (2 * v.denominator) for v in values)


def resolve_color(element, *, theme=(), palette=None):
    active = [key for key in ("rgb", "theme", "indexed", "auto") if element.get(key) is not None]
    if len(active) != 1:
        raise UnsupportedRendering("Conflicting or missing active color sources.")
    key = active[0]
    value = element.get(key)
    if key == "rgb":
        color = rgb(value)
    elif key == "auto":
        raise UnsupportedRendering("Automatic color has no concrete RGB fallback.")
    else:
        if not value.isascii() or not value.isdigit() or len(value.lstrip("0")) > 5:
            raise UnsupportedRendering("Invalid theme/indexed color index.")
        index = int(value)
        if key == "theme":
            if index >= len(theme) or theme[index] is None:
                raise UnsupportedRendering("Theme color has no concrete RGB fallback.")
            color = theme[index]
        else:
            if palette is None:
                palette = tuple(rgb(value) for value in INDEXED_RGB)
            if index >= len(palette) or index >= 64:
                raise UnsupportedRendering(
                    "Indexed color is outside the concrete workbook palette."
                )
            color = palette[index]
    return tinted(color, element.get("tint", "0"))


def relative_luminance(color):
    channels = [c / 255 for c in color]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(weight * c for weight, c in zip((0.2126, 0.7152, 0.0722), linear))


def contrast_ratio(first, second):
    a, b = sorted((relative_luminance(first), relative_luminance(second)))
    return (b + 0.05) / (a + 0.05)


def _flag(value, default=False):
    if value is None:
        return default
    if value not in {"0", "1", "true", "false"}:
        raise UnsupportedRendering("Unsupported style boolean value.")
    return value in {"1", "true"}


def _index(value, elements, kind):
    if not value.isascii() or not value.isdigit() or len(value.lstrip("0")) > 7:
        raise UnsupportedRendering(f"Invalid {kind} index.")
    index = int(value)
    if index >= len(elements):
        raise UnsupportedRendering(f"{kind} index is not available.")
    return elements[index]


class StyleResolver:
    """Resolve styles from the original package and explicit worksheet metadata."""

    def __init__(self, reader):
        self.reader = reader
        relations = _relationships(reader._archive, reader.workbook_part)
        self.ns = None
        self.fonts = []
        self.fills = []
        self.xfs = []
        self.bases = []
        self.palette = None
        self.theme = ()
        self.theme_fonts = {}
        self._sheet_styles = {}
        self._table_overlays = {}
        for kind in ("styles", "theme"):
            matching = [r for r in relations.values() if r.attrib["Type"].endswith("/" + kind)]
            if len(matching) > 1:
                raise ValueError("Ambiguous workbook " + kind + " relationships")
            if not matching:
                continue
            relation = matching[0]
            if relation.get("TargetMode") == "External":
                raise UnsupportedRendering("External style/theme content is not fetched.")
            root = safe_xml.fromstring(
                reader._archive.read(_part(reader.workbook_part, relation.attrib["Target"]))
            )
            if kind == "styles":
                self.ns = "{" + _namespace(root, "styleSheet") + "}"
                for field, container, name in [
                    ("fonts", "fonts", "font"),
                    ("fills", "fills", "fill"),
                    ("xfs", "cellXfs", "xf"),
                    ("bases", "cellStyleXfs", "xf"),
                ]:
                    setattr(self, field, root.findall(self.ns + container + "/" + self.ns + name))
                indexed = root.find(self.ns + "colors/" + self.ns + "indexedColors")
                if indexed is not None:
                    if any(c.tag != self.ns + "rgbColor" for c in indexed):
                        raise UnsupportedRendering(
                            "Unsupported workbook indexed palette representation."
                        )
                    self.palette = tuple(rgb(c.attrib["rgb"]) for c in indexed)
            else:
                self._read_theme(root)

    def _read_theme(self, root):
        namespaces = (
            "http://schemas.openxmlformats.org/drawingml/2006/main",
            "http://purl.oclc.org/ooxml/drawingml/main",
        )
        namespace = next((ns for ns in namespaces if root.tag == "{" + ns + "}theme"), None)
        if namespace is None:
            raise UnsupportedRendering("Unsupported theme namespace.")
        ns = "{" + namespace + "}"
        scheme = root.find(ns + "themeElements/" + ns + "clrScheme")
        colors = []
        for name in (
            "lt1",
            "dk1",
            "lt2",
            "dk2",
            "accent1",
            "accent2",
            "accent3",
            "accent4",
            "accent5",
            "accent6",
            "hlink",
            "folHlink",
        ):
            entry = [] if scheme is None else scheme.findall(ns + name)
            color = None
            if len(entry) == 1 and len(entry[0]) == 1:
                item = entry[0][0]
                if len(item) == 0 and item.tag in {ns + "srgbClr", ns + "sysClr"}:
                    value = item.get("val") if item.tag == ns + "srgbClr" else item.get("lastClr")
                    if value is not None:
                        color = rgb(value)
            colors.append(color)
        self.theme = tuple(colors)
        for kind in ("major", "minor"):
            latin = root.find(
                ns + "themeElements/" + ns + "fontScheme/" + ns + kind + "Font/" + ns + "latin"
            )
            if latin is not None and latin.get("typeface"):
                self.theme_fonts[kind] = latin.get("typeface")

    def _worksheet_styles(self, sheet):
        if sheet.part in self._sheet_styles:
            return self._sheet_styles[sheet.part]
        columns = []
        for container in worksheet_features(self.reader, sheet, {"cols"}):
            ns = container.tag.split("}")[0] + "}"
            for column in container.findall(ns + "col"):
                if column.get("style") is not None:
                    first, last = int(column.attrib["min"]), int(column.attrib["max"])
                    if not 1 <= first <= last <= 16384:
                        raise ValueError("Column style interval outside worksheet bounds")
                    columns.append((first, last, column.get("style")))
        self._sheet_styles[sheet.part] = columns
        return columns

    def resolve(self, sheet, cell):
        if sheet.part not in self._table_overlays:
            overlays = []
            containers = worksheet_features(self.reader, sheet, {"tableParts"})
            relations = _relationships(self.reader._archive, sheet.part) if containers else {}
            for container in containers:
                ns_ = container.tag.split("}")[0] + "}"
                for item in container.findall(ns_ + "tablePart"):
                    identifiers = [v for k, v in item.attrib.items() if k.endswith("}id")]
                    if len(identifiers) != 1:
                        raise ValueError("Missing/ambiguous table relationship")
                    relation = relations[identifiers[0]]
                    if relation.get("TargetMode") == "External":
                        raise UnsupportedRendering(
                            "External table style overlay cannot be resolved."
                        )
                    table = safe_xml.fromstring(
                        self.reader._archive.read(_part(sheet.part, relation.attrib["Target"]))
                    )
                    table_ns = "{" + _namespace(table, "table") + "}"
                    style = table.find(table_ns + "tableStyleInfo")
                    if style is not None and style.get("name"):
                        overlays.append(canonical_range(table.attrib["ref"]))
            self._table_overlays[sheet.part] = overlays
        if any(
            contains(rectangle, cell.row, cell.column)
            for rectangle in self._table_overlays[sheet.part]
        ):
            raise UnsupportedRendering("Table-style overlay prevents a static rendering result.")
        ns = self.ns
        if cell.style_id is not None:
            style_id = cell.style_id
        elif cell.row_style_id is not None:
            style_id = cell.row_style_id
        else:
            styles = {
                style
                for first, last, style in self._worksheet_styles(sheet)
                if first <= cell.column <= last
            }
            if len(styles) > 1:
                raise UnsupportedRendering("Conflicting covering column styles.")
            style_id = next(iter(styles), "0")
        if not self.xfs:
            if style_id != "0":
                raise UnsupportedRendering("Referenced cell style is unavailable.")
            return StaticStyle(
                (0, 0, 0),
                (255, 255, 255),
                Decimal(11),
                False,
                None,
                (
                    "Missing font color/fill are screened as black on white; default font size is 11 pt.",
                ),
            )
        xf = _index(style_id, self.xfs, "cellXf")
        if xf.get("xfId") is not None:
            base = _index(xf.get("xfId"), self.bases, "base style")
            if base.get("xfId") is not None:
                raise UnsupportedRendering("Recursive base-style inheritance is unsupported.")
        else:
            base = None
        font = self._component(xf, base, "fontId", "applyFont", self.fonts)
        fill = self._component(xf, base, "fillId", "applyFill", self.fills)
        assumptions = []
        color = font.find(ns + "color")
        if color is None:
            foreground = (0, 0, 0)
            assumptions.append("Missing font color is screened as black.")
        else:
            foreground = resolve_color(color, theme=self.theme, palette=self.palette)
        pattern = fill.find(ns + "patternFill")
        if fill.find(ns + "gradientFill") is not None or pattern is None or len(fill) != 1:
            raise UnsupportedRendering("Gradient or ambiguous fill rendering is unsupported.")
        kind = pattern.get("patternType", "none")
        if kind == "none":
            background = (255, 255, 255)
            assumptions.append("Missing fill is screened as white.")
        elif kind == "solid":
            colors = pattern.findall(ns + "fgColor")
            if len(colors) != 1:
                raise UnsupportedRendering("Solid fill has no unambiguous foreground color.")
            background = resolve_color(colors[0], theme=self.theme, palette=self.palette)
        else:
            raise UnsupportedRendering("Patterned fill rendering is unsupported.")
        if len(font.findall(ns + "color")) > 1:
            raise UnsupportedRendering("Multiple font colors are ambiguous.")
        size = font.find(ns + "sz")
        point_size = Decimal(size.attrib["val"]) if size is not None else Decimal(11)
        if not point_size.is_finite() or point_size <= 0:
            raise UnsupportedRendering("Unsupported font size.")
        if size is None:
            assumptions.append("Missing font size is screened as 11 pt.")
        bold = font.find(ns + "b")
        bold_value = _flag(bold.get("val"), True) if bold is not None else False
        name = font.find(ns + "name")
        font_name = name.get("val") if name is not None else None
        scheme = font.find(ns + "scheme")
        if scheme is not None and scheme.get("val") in {"major", "minor"}:
            font_name = self.theme_fonts.get(scheme.get("val"), font_name)
        if font.find(ns + "vertAlign") is not None:
            raise UnsupportedRendering("Superscript/subscript rendered font size is unsupported.")
        if cell.rich_text:
            # Run provenance comes from original shared/inline OOXML, not text.
            formats = {properties for _, properties in cell.rich_runs}
            if len(formats) > 1:
                raise UnsupportedRendering("Mixed rich-text styling is unsupported.")
            if formats and next(iter(formats)):
                raise UnsupportedRendering("Explicit rich-text run styling is not yet resolved.")
        return StaticStyle(
            foreground, background, point_size, bold_value, font_name, tuple(assumptions)
        )

    def _component(self, xf, base, attribute, apply_flag, elements):
        if xf.get(apply_flag) is not None and not _flag(xf.get(apply_flag)):
            if base is None:
                raise UnsupportedRendering("Disabled style component has no referenced base style.")
            identifier = base.get(attribute, "0")
        else:
            identifier = xf.get(attribute, base.get(attribute, "0") if base is not None else "0")
        return _index(identifier, elements, attribute)
