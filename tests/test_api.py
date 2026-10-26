"""Source-independent AST passes applied by api.convert().

Usage: python -m unittest discover -s tests -p "test_api.py"
"""
from __future__ import annotations

import textconverter
from _support import BaseConverterTest, setUpModule, tearDownModule


class TestDiscardLinks(BaseConverterTest):

    def test_discard_links_is_source_independent(self):
        """--discard-links unwraps every link to its text, keeping a link-wrapped image."""
        src = ("[Modena](https://en.wikipedia.org/wiki/Modena) is a [city](http://x.test). "
               "[![alt](pic.jpg)](http://y.test)")
        md = textconverter.convert(src, to_format="markdown", from_format="markdown",
                                   discard_links=True)
        self.assertIn("Modena is a city.", md)
        self.assertNotIn("http", md)
        self.assertIn("![alt](pic.jpg)", md)
