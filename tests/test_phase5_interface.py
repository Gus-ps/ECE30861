from html.parser import HTMLParser
from pathlib import Path
import unittest

PAGE = Path(__file__).resolve().parent.parent / 'static' / 'index.html'
FIELDS = {'input', 'select', 'textarea'}
NAMED = {'button', 'a'}


class Page(HTMLParser):
    """Static markup only; elements built by the inline script are not seen."""

    def __init__(self):
        super().__init__()
        self.label_for, self.fields, self.named, self.open, self.in_label = set(), [], [], [], 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'label':
            self.in_label += 1
            self.label_for.add(attrs.get('for'))
        if tag in FIELDS and attrs.get('type') != 'hidden':
            self.fields.append(dict(attrs, wrapped=self.in_label > 0))
        if tag in NAMED and (tag == 'button' or 'href' in attrs):
            self.open.append(dict(attrs, tag=tag, text=''))

    def handle_data(self, data):
        for element in self.open:
            element['text'] += data

    def handle_endtag(self, tag):
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


if __name__ == '__main__':
    unittest.main()
