"""Markdown parsing and rendering, including tables and code detection.

Usage: python -m unittest discover -s tests -p "test_markdown.py"
"""
from __future__ import annotations

import textconverter
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR, read


class TestMarkdownParser(BaseConverterTest):

    def test_md_to_html_structure(self):
        """SampleMD.md → HTML: headings, paragraphs, table, code, blockquote, list."""
        content = self.convert_fixture("SampleMD.md", "SampleMD.html")
        self.assertIn("<h1>", content, "Missing h1 heading")
        self.assertIn("<h2>", content, "Missing h2 heading")
        self.assertIn("<h3>", content, "Missing h3 heading")
        self.assertIn("<p>", content, "Missing paragraph")
        self.assertIn("<table", content, "Missing table")
        self.assertIn("<ul>", content, "Missing unordered list")
        self.assertIn("<ol>", content, "Missing ordered list")
        self.assertIn("<pre>", content, "Missing pre/code block")
        self.assertIn("<blockquote>", content, "Missing blockquote")
        # Fenced code blocks present in SampleMD.md
        self.assertIn("def drytext_condense_file", content, "Missing fenced Python code")
        # Inline code
        self.assertIn("<code>", content, "Missing inline code")
        # Alert blockquotes
        self.assertIn("IMPORTANT", content, "Missing IMPORTANT alert")
        self.assertIn("CAUTION", content, "Missing CAUTION alert")
        # Bold and italic (renderer uses <b>/<i>)
        self.assertTrue("<b>" in content or "<strong>" in content, "Missing bold text")
        self.assertTrue("<i>" in content or "<em>" in content, "Missing italic text")

    def test_md_roundtrip(self):
        """SampleMD.md → MD: key structural elements survive the roundtrip."""
        content = self.convert_fixture("SampleMD.md", "SampleMD_out.md")
        self.assertIn("# Sample MD File", content, "Missing h1 title in roundtrip")
        self.assertIn("## 1. Title", content, "Missing h2 in roundtrip")
        # Table preserved
        self.assertIn("| Col One |", content, "Missing table header in roundtrip")
        self.assertIn("`foo.bar`", content, "Missing inline code in roundtrip")
        # Bold and italic
        self.assertIn("**table**", content, "Missing bold in roundtrip")
        self.assertIn("[link]", content, "Missing link in roundtrip")

    def test_code_block_fenced_and_unfenced(self):
        """CodeTest.md → HTML: fenced Python code detected, inline code preserved."""
        content = self.convert_fixture("CodeTest.md", "CodeTest.html", code_parsing=True)
        # Fenced block preserved
        self.assertIn("def fibonacci(n):", content, "Missing fibonacci function")
        self.assertIn("<pre>", content, "Missing pre tag for code block")
        # Inline code preserved (backtick notation)
        self.assertIn("<code>", content, "Missing inline code tag")

    def test_html_caption_wrapping(self):
        """HTML captions with links should be wrapped as plain paragraph text."""
        html_content = """
        <div class="thumbcaption">
            Una serie di <a href="http://example.com/codon">codoni</a> su una molecola di <a href="http://example.com/rna">RNA messaggero</a>.
        </div>
        """
        result = textconverter.convert_text(html_content, "html", "markdown")
        self.assertIn("[codoni](http://example.com/codon)", result)
        self.assertIn("[RNA messaggero](http://example.com/rna)", result)

    def test_md_table_escaped_pipe_in_code(self):
        r"""MD table: `\|` and pipes inside `code` spans stay inside their cell."""
        import json as _json
        md = (
            "| Name | Type | Note |\n"
            "|---|---|---|\n"
            "| `file_paths` | `str \\| list[str] \\| None` | holds a `a|b` value |\n"
        )
        ast = _json.loads(textconverter.convert_text(md, "markdown", "json"))
        row = ast["children"][0]["rows"][0]
        self.assertEqual(len(row["cells"]), 3, "escaped/code-span pipes split the row into extra cells")
        type_cell = row["cells"][1]["children"]
        self.assertEqual([n["type"] for n in type_cell], ["CodeInline"])
        self.assertEqual(type_cell[0]["code"], "str | list[str] | None")

        html = textconverter.convert_text(md, "markdown", "html")
        self.assertIn("<td><code>str | list[str] | None</code></td>", html)
        self.assertNotIn("\\|", html)

        # MD round-trip: literal pipe re-emitted escaped and still parses to 3 cells.
        md2 = textconverter.convert_text(md, "markdown", "markdown")
        self.assertIn(r"`str \| list[str] \| None`", md2)
        ast2 = _json.loads(textconverter.convert_text(md2, "markdown", "json"))
        self.assertEqual(len(ast2["children"][0]["rows"][0]["cells"]), 3)
