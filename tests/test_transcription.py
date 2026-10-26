"""Parsing of AI transcriptions: fences, HTML tables mixed with Markdown, formulas.

Usage: python -m unittest discover -s tests -p "test_transcription.py"
"""
from __future__ import annotations

from textconverter.ast import Heading, Paragraph, Table
from textconverter.parsers.transcription_parser import (
    equation_code, normalize_transcription, parse_transcription,
)
from _support import BaseConverterTest, setUpModule, tearDownModule


class TestTranscriptionParser(BaseConverterTest):

    def test_mixed_markdown_and_html_table_keep_order(self):
        text = "```markdown\n# Title\n\n<table><tr><td>1</td></tr></table>\n\nAfter.\n```"
        kinds = [type(n) for n in parse_transcription(text).children]
        self.assertEqual(kinds, [Heading, Table, Paragraph])

    def test_normalize_leaves_plain_markdown_alone(self):
        self.assertEqual(normalize_transcription("  **bold** text \n"), "**bold** text")

    def test_equation_code_delimiters(self):
        self.assertEqual(equation_code("$$ x^2 $$"), "x^2")
        self.assertEqual(equation_code("```latex\n\\[ y \\]\n```"), "y")
        self.assertEqual(equation_code(r"\begin{equation} z \end{equation}"), "z")
        self.assertIsNone(equation_code("plain words"))

    def test_bare_formula_only_when_classified_as_one(self):
        self.assertEqual(equation_code("a+b", bare_is_formula=True), "a+b")
        self.assertEqual(equation_code("$a+b$", bare_is_formula=True), "a+b")
        self.assertIsNone(equation_code("$5 and $6", bare_is_formula=False))
