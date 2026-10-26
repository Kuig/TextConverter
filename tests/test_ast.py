"""The shared AST traversal helpers in textconverter.ast.

Usage: python -m unittest discover -s tests -p "test_ast.py"
"""
from __future__ import annotations

import textconverter
from textconverter.ast import (
    Document, Image, Link, Paragraph, Table, TableCell, TableRow, Text, child_lists, walk,
)
from _support import BaseConverterTest, setUpModule, tearDownModule


def _table_with_images() -> Document:
    """A table with an image in a header cell and a link-wrapped image in a body cell."""
    header = TableCell(children=[Image(src="head.png")])
    body = TableCell(children=[Link(url="http://x.test", content=[Image(src="body.png")])])
    return Document(children=[Table(headers=[header], rows=[TableRow(cells=[body])])])


class TestWalk(BaseConverterTest):

    def test_walk_reaches_headers_and_link_content(self):
        """walk() visits every child attribute, including table headers and link content."""
        srcs = [n.src for n in walk(_table_with_images()) if isinstance(n, Image)]
        self.assertEqual(srcs, ["head.png", "body.png"])

    def test_child_lists_are_live_and_skip_text_content(self):
        """child_lists() returns the node's own lists; Text.content (a string) is not one."""
        para = Paragraph(children=[Text(content="a"), Image(src="x.png")])
        (children,) = child_lists(para)
        children[:] = [c for c in children if not isinstance(c, Image)]
        self.assertEqual(para.children, [Text(content="a")])
        self.assertEqual(child_lists(Text(content="a")), [])

    def test_discard_removes_images_everywhere(self):
        """image_handling='discard' also drops images in table headers and inside links."""
        md = textconverter.convert(
            "| ![h](head.png) |\n|---|\n| [![b](body.png)](http://x.test) |\n",
            to_format="markdown", from_format="markdown", image_handling="discard",
        )
        self.assertNotIn(".png", md)
