"""Read-only part ownership for partial 1.1.1 Non-text Content and 2.4.2
Page Titled (related 2.4.6 Headings and Labels). No editing or safe-edit claim.
"""

import posixpath
from dataclasses import dataclass
from urllib.parse import urlsplit

from accessibility_checker import safe_xml


def relationship_id(element):
    return next(value for key, value in element.attrib.items() if key.endswith("}id"))


def relationships(archive, part):
    directory, name = posixpath.split(part)
    path = posixpath.join(directory, "_rels", name + ".rels")
    root = safe_xml.fromstring(archive.read(path))
    result = {}
    for item in root:
        identifier = item.attrib["Id"]
        if identifier in result:
            raise ValueError(f"Duplicate relationship ID in {path}: {identifier}")
        result[identifier] = item
    return result


def internal_target(part, relationship):
    target = relationship.attrib["Target"]
    url = urlsplit(target)
    if relationship.get("TargetMode") == "External" or url.scheme or url.netloc:
        raise ValueError("External relationships are not internal package parts")
    result = posixpath.normpath(posixpath.join(posixpath.dirname(part), target)).lstrip("/")
    if result == ".." or result.startswith("../"):
        raise ValueError("Relationship target escapes package")
    return result


@dataclass(frozen=True)
class SheetOwner:
    index: int
    name: str
    sheet_id: str
    kind: str
    part: str | None


def sheet_owners(root, relations, workbook_part="xl/workbook.xml"):
    owners = []
    for index, sheet in enumerate(root.findall("{*}sheets/{*}sheet")):
        rel = relations[relationship_id(sheet)]
        kind = rel.attrib["Type"].rsplit("/", 1)[-1]
        if kind not in ("worksheet", "chartsheet"):
            continue
        part = None if rel.get("TargetMode") == "External" else internal_target(workbook_part, rel)
        owners.append(SheetOwner(index, sheet.attrib["name"], sheet.attrib["sheetId"], kind, part))
    return tuple(owners)


def drawing_owners(archive, owners):
    return referenced_part_owners(archive, owners, "drawing", "drawing")


def referenced_part_owners(archive, owners, element_name, relationship_kind):
    """Map actually referenced internal parts to distinct owning sheets.

    Repeated references from one sheet do not create additional owners; distinct
    sheet definitions sharing a sheet part still are distinct owners. Unused
    relationships and external destinations are not counted or fetched.
    """
    result = {}
    references = {}
    for owner in owners:
        if owner.part is None:
            continue
        if owner.part not in references:
            identifiers = set()
            with archive.open(owner.part) as stream:
                stack = []
                for event, element in safe_xml.iterparse(stream, ("start", "end")):
                    if event == "start":
                        stack.append(element)
                        continue
                    if element.tag.rsplit("}", 1)[-1] == element_name:
                        identifiers.add(relationship_id(element))
                    stack.pop()
                    if stack:
                        stack[-1].remove(element)
                    element.clear()
            # No drawing means no drawing relationship file is required.
            rels = relationships(archive, owner.part) if identifiers else {}
            references[owner.part] = {
                internal_target(owner.part, rels[identifier]) for identifier in identifiers
                if rels[identifier].get("TargetMode") != "External"
                and rels[identifier].attrib["Type"].endswith("/" + relationship_kind)
            }
        for part in references[owner.part]:
            result.setdefault(part, set()).add(owner)
    return {part: frozenset(sheets) for part, sheets in result.items()}
