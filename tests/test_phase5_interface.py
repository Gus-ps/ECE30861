from html.parser import HTMLParser
from pathlib import Path
import re
import unittest

PAGE = Path(__file__).resolve().parent.parent / 'static' / 'index.html'
FIELDS = {'input', 'select', 'textarea'}
NAMED = {'button', 'a'}


class Page(HTMLParser):
    """Static markup only; elements built by the inline script are not seen."""

    def __init__(self):
        super().__init__()
        self.label_for, self.fields, self.named, self.open, self.in_label = set(), [], [], [], 0
        self.css, self.in_style, self.regions = '', False, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'role' in attrs or 'aria-live' in attrs:
            self.regions.append(attrs)
        self.in_style = tag == 'style'
        self.css += attrs.get('style') or ''
        if tag == 'label':
            self.in_label += 1
            self.label_for.add(attrs.get('for'))
        if tag in FIELDS and attrs.get('type') != 'hidden':
            self.fields.append(dict(attrs, wrapped=self.in_label > 0))
        if tag in NAMED and (tag == 'button' or 'href' in attrs):
            self.open.append(dict(attrs, tag=tag, text=''))

    def handle_data(self, data):
        if self.in_style:
            self.css += data
        for element in self.open:
            element['text'] += data

    def handle_endtag(self, tag):
        self.in_style = False
        if tag == 'label':
            self.in_label -= 1
        if self.open and tag == self.open[-1]['tag']:
            self.named.append(self.open.pop())


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.page = Page()
        self.page.feed(PAGE.read_text(encoding='utf-8'))

    def test_inputs_have_labels_and_controls_have_names(self):
        self.assertTrue(self.page.fields and self.page.named)
        for field in self.page.fields:
            with self.subTest(field=field.get('id')):
                self.assertTrue(field['wrapped'] or field.get('id') in self.page.label_for
                                or field.get('aria-label') or field.get('aria-labelledby'))
        for element in self.page.named:
            with self.subTest(element=element.get('id') or element['text']):
                self.assertTrue(element['text'].strip() or element.get('aria-label') or element.get('aria-labelledby'))

    def test_focus_is_always_visible(self):
        css = re.sub(r'\s+', '', self.page.css)
        # A global :focus-visible rule covers every element, including script-built ones.
        self.assertRegex(css, r'(^|})(\*)?:focus-visible\{[^}]*outline:[2-9]px(solid|double)#[0-9a-f]{3,6}')
        self.assertNotRegex(css, r'outline(-style|-width)?:(none|0(?![\d.]))')

    def test_status_and_error_live_regions_exist(self):
        roles = {(r.get('id'), r.get('role'), r.get('aria-live')) for r in self.page.regions}
        self.assertIn(('status', 'status', 'polite'), roles)
        self.assertIn(('error', 'alert', None), roles)
        script = PAGE.read_text(encoding='utf-8')
        self.assertIn("el('error').textContent=error?t:''", script)  # errors go to the alert region as text


if __name__ == '__main__':
    unittest.main()
