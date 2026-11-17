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
        self.ids, self.tabindex, self.inline_handlers = {}, [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.ids[attrs.get('id')] = tag
        if 'tabindex' in attrs:
            self.tabindex.append(int(attrs['tabindex']))
        self.inline_handlers += [(tag, name) for name in attrs if name.startswith('on')]
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

    def test_keyboard_order_and_native_activation(self):
        script = PAGE.read_text(encoding='utf-8')
        self.assertFalse([i for i in self.page.tabindex if i > 0])
        self.assertFalse([h for h in self.page.inline_handlers if h[0] not in ('button', 'form')])
        # Click handlers only on buttons (Enter and Space work natively); forms use onsubmit.
        for target, event in re.findall(r"el\('([\w-]+)'\)\.on(\w+)=", script):
            with self.subTest(target=target):
                self.assertEqual(self.page.ids[target], 'form' if event == 'submit' else 'button')
        for variable in re.findall(r'(\w+)\.onclick=', script):  # script-built controls
            self.assertRegex(script, rf"const {variable}=text\('button'")
        self.assertNotRegex(script, r'key(down|up|press)|addEventListener|focus\(\)')  # no custom key handling or focus moves
        css = re.sub(r'\s+', '', self.page.css)
        self.assertNotRegex(css, r'[;{](order|position):|flex-direction:\w+-reverse|grid-area|float:')  # visual order = DOM order


if __name__ == '__main__':
    unittest.main()
