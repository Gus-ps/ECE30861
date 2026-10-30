"""Sparse worksheet metadata for partial 1.3.1 Info and Relationships checks."""

from accessibility_checker import safe_xml
from accessibility_checker.cell_reader import _namespace
from accessibility_checker.coordinates import canonical_range, range_sort_key


def worksheet_features(reader, sheet, names, *, with_paths=False):
    """Retain selected direct children only; discard grid XML as it is read."""
    result = []
    stack = []
    selected = None
    selected_path = None
    counts = {}
    with reader._archive.open(sheet.part) as stream:
        for event, element in safe_xml.iterparse(stream, ("start", "end")):
            if event == "start":
                if not stack:
                    namespace = _namespace(element, sheet.kind)
                if len(stack) == 1:
                    local = element.tag.rsplit("}", 1)[-1]
                    counts[local] = counts.get(local, 0) + 1
                if len(stack) == 1 and ((names is None and element.tag != f"{{{namespace}}}sheetData") or (names is not None and element.tag in {
                    f"{{{namespace}}}{name}" for name in names
                })):
                    selected = element
                    selected_path = f"/{sheet.kind}[1]/{local}[{counts[local]}]"
                stack.append(element)
                continue
            stack.pop()
            if element is selected:
                result.append((element, selected_path) if with_paths else element)
                selected = None
                if stack:
                    stack[-1].remove(element)
            elif selected is None:
                if stack:
                    stack[-1].remove(element)
                element.clear()
    return result


def merge_ranges(reader, sheet):
    ranges = set()
    for container in worksheet_features(reader, sheet, {"mergeCells"}):
        namespace = container.tag.split("}")[0] + "}"
        for merge in container.findall(namespace + "mergeCell"):
            ranges.add(canonical_range(merge.attrib["ref"]))
    return sorted(ranges, key=range_sort_key)


def contains(rectangle, row, column):
    top, left, bottom, right = range_sort_key(rectangle)
    return top <= row <= bottom and left <= column <= right


def overlaps(first, second):
    a, b, c, d = range_sort_key(first)
    e, f, g, h = range_sort_key(second)
    return a <= g and e <= c and b <= h and f <= d


def indexed_paths(root):
    """Local-name, sibling-counted locations; namespace is validated separately."""
    result = {root: '/' + root.tag.rsplit('}', 1)[-1] + '[1]'}
    pending = [root]
    while pending:
        parent = pending.pop()
        counts = {}
        for child in parent:
            name = child.tag.rsplit('}', 1)[-1]
            counts[name] = counts.get(name, 0) + 1
            result[child] = result[parent] + '/' + name + '[' + str(counts[name]) + ']'
            pending.append(child)
    return result
