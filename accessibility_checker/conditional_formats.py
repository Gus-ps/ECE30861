"""Finite x14 expression-rule profile; unknown extensions stay unsupported.

The supported worksheet extension contains xm:f reference text, local xm:sqref
ranges and, optionally, a bold-only differential font. It contains no external,
opaque or executable content. Formula safety is checked by rename_safety.
"""
import re

from accessibility_checker.coordinates import canonical_range

X14 = 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
XM = 'http://schemas.microsoft.com/office/excel/2006/main'
CF_URI = '{78c0d931-6437-407d-a8ee-f0aad7539e65}'
MAIN = {'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
        'http://purl.oclc.org/ooxml/spreadsheetml/main'}


def supported_x14_node(stack):
    """Recognize an element only at its exact supported worksheet ancestry."""
    root = stack[0].tag
    namespace = root[1:].split('}', 1)[0] if root.startswith('{') else ''
    if namespace not in MAIN or root != '{'+namespace+'}worksheet':
        return False
    ns = '{'+namespace+'}'
    tags = tuple(element.tag for element in stack)
    prefix = (root, ns+'extLst')
    if tags == prefix:
        return not stack[-1].attrib
    if len(tags) < 3 or tags[:2] != prefix or tags[2] != ns+'ext':
        return False
    extension = stack[2]
    if set(extension.attrib) != {'uri'} or extension.get('uri', '').casefold() != CF_URI:
        return False
    if len(tags) == 3:
        return True
    x14, xm = '{'+X14+'}', '{'+XM+'}'
    base = (x14+'conditionalFormattings',)
    formatting = base+(x14+'conditionalFormatting',)
    rule = formatting+(x14+'cfRule',)
    path = tags[3:]
    element = stack[-1]
    if path in (base, formatting, rule+(x14+'dxf',), rule+(x14+'dxf', ns+'font')):
        return not element.attrib
    if path == rule:
        return (set(element.attrib) <= {'type', 'priority', 'id'}
                and element.get('type') == 'expression'
                and re.fullmatch(r'[1-9][0-9]*', element.get('priority', ''), re.ASCII) is not None
                and re.fullmatch(r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}', element.get('id', '')) is not None)
    if path == rule+(xm+'f',):
        return not element.attrib and bool((element.text or '').strip())
    if path == formatting+(xm+'sqref',):
        if element.attrib or not (element.text or '').split():
            return False
        try:
            for reference in element.text.split():
                canonical_range(reference)
        except ValueError:
            return False
        return True
    if path == rule+(x14+'dxf', ns+'font', ns+'b'):
        return set(element.attrib) <= {'val'} and element.get('val', '1') in {'0', '1', 'false', 'true'}
    return False


def bold_only_x14_extension(extension, worksheet_namespace):
    """True only for fully recognized, non-color expression-rule extensions."""
    from xml.etree.ElementTree import Element
    worksheet = Element('{'+worksheet_namespace+'}worksheet')
    found_rule = False
    pending = [(extension, [worksheet])]
    while pending:
        element, parents = pending.pop()
        stack = parents+[element]
        if not supported_x14_node(stack):
            return False
        found_rule |= element.tag == '{'+X14+'}cfRule'
        pending.extend((child, stack) for child in element)
    return found_rule
