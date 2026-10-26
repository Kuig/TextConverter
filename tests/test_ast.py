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


class TestJsonForm(BaseConverterTest):

    def test_node_types_lists_every_node_class(self):
        """NODE_TYPES names every concrete node class defined in ast.py, and not the base."""
        import inspect
        from textconverter import ast
        classes = {name for name, obj in inspect.getmembers(ast, inspect.isclass)
                   if issubclass(obj, ast.Node) and obj is not ast.Node}
        self.assertEqual(set(ast.NODE_TYPES), classes)

    def test_equation_env_round_trips(self):
        """A display environment survives JSON output and input."""
        from textconverter.ast import Equation
        from textconverter.parsers.json_parser import parse_json
        from textconverter.renderers.json_renderer import render_json
        doc = Document(children=[Equation(code="a &= b", env="align*")])
        self.assertEqual(parse_json(render_json(doc)), doc)

    def test_unknown_node_type_is_an_error(self):
        """A misspelled type no longer vanishes from the output."""
        from textconverter.parsers.json_parser import parse_json
        bad = '{"type": "Document", "children": [{"type": "Paragraph", "children": [{"type": "Txt", "content": "x"}]}]}'
        with self.assertRaisesRegex(ValueError, "Txt"):
            parse_json(bad)

    def test_base_node_and_untyped_objects_are_rejected(self):
        from textconverter.parsers.json_parser import parse_json
        for bad in ('{"type": "Node"}', '{"type": "Document", "children": [{"content": "x"}]}'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_json(bad)

    def test_missing_required_field_and_wrong_list_are_errors(self):
        from textconverter.parsers.json_parser import parse_json
        for bad in ('{"type": "Document", "children": [{"type": "Text"}]}',
                    '{"type": "Document", "children": "abc"}'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_json(bad)

    def test_unknown_keys_are_ignored(self):
        """Keys a node does not define are reported and dropped, not fatal."""
        from textconverter.parsers.json_parser import parse_json
        doc = parse_json('{"type": "Document", "children": [{"type": "Text", "content": "x", "colour": "red"}]}')
        self.assertEqual(doc.children, [Text(content="x")])
