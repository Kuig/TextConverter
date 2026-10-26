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


def _md(text: str, to: str = "markdown", **options) -> str:
    return textconverter.convert_text(text, "markdown", to, textconverter.ConvertOptions(**options))


def _doc(text: str):
    from textconverter.parsers.markdown_parser import parse_markdown
    return parse_markdown(text)


class TestMarkdownFixes(BaseConverterTest):
    """Markdown that used to lose or alter content."""

    def test_text_right_after_a_heading_is_kept(self):
        self.assertEqual(_md("# Title\nBody line here").strip(), "# Title\n\nBody line here")

    def test_empty_header_cell_keeps_its_column(self):
        """A pivot-style table (empty corner cell) used to lose its last column."""
        md = _md("| | Q1 | Q2 |\n|---|---|---|\n| a | 1 | 2 |")
        self.assertEqual(md.splitlines(), ["|  | Q1 | Q2 |", "|---|---|---|", "| a | 1 | 2 |"])

    def test_a_dash_is_not_a_table_separator(self):
        from textconverter.ast import Paragraph
        self.assertIsInstance(_doc("use a | b\nfoo-bar").children[0], Paragraph)

    def test_undefined_reference_stays_text(self):
        """matrix[i][j] used to become a link to '#'."""
        from textconverter.ast import Link, walk
        doc = _doc("see matrix[i][j] here")
        self.assertFalse([n for n in walk(doc) if isinstance(n, Link)])
        self.assertIn(r"matrix\[i\]\[j\]", _md("see matrix[i][j] here"))

    def test_reference_links_in_list_continuation_lines(self):
        from textconverter.ast import Link, walk
        doc = _doc("- item\n  more [y][r]\n\n[r]: https://x.test")
        links = [n for n in walk(doc) if isinstance(n, Link)]
        self.assertEqual([l.url for l in links], ["https://x.test"])

    def test_intraword_underscores_are_not_emphasis(self):
        from textconverter.ast import Text, walk
        doc = _doc("call my_var_name now")
        self.assertFalse([n for n in walk(doc) if isinstance(n, Text) and n.italic])

    def test_nested_emphasis(self):
        from textconverter.ast import Text
        (text,) = _doc("**_both_**").children[0].children
        self.assertEqual(text, Text(content="both", bold=True, italic=True))

    def test_strikethrough(self):
        from textconverter.ast import Text
        self.assertIn(Text(content="gone", strikethrough=True), _doc("a ~~gone~~ b").children[0].children)
        self.assertIn("<s>gone</s>", _md("a ~~gone~~ b", "html"))

    def test_starred_citation_macro(self):
        from textconverter.ast import Citation
        children = _doc(r"as \citet*{knuth} shows").children[0].children
        self.assertIn(Citation(keys=["knuth"], style="citet"), children)

    def test_bullet_before_code_fence_attaches_the_code(self):
        from textconverter.ast import CodeBlock, ListBlock
        doc = _doc("• item\n```\nx = 1\n```")
        self.assertIsInstance(doc.children[0], ListBlock)
        self.assertIsInstance(doc.children[0].items[0].children[-1], CodeBlock)

    def test_abstraction_is_not_an_abstract(self):
        self.assertNotIn("**Abstract**", _md("> Abstraction is key"))


class TestMarkdownEscaping(BaseConverterTest):
    """Literal text that looks like Markdown survives a Markdown round trip."""

    CASES = [
        "Use *args and **kwargs",
        "price is $5 and $10",
        "a [bracket] and a `tick`",
        "_leading underscore and trailing_",
        r"a C:\path\to and a \* star",
        "# not a heading",
        "1. not a list",
        "- not a bullet",
        "> not a quote",
        "---",
        r"\footnote{x} typed literally",
        "two ~~tildes~~",
    ]

    def test_literal_text_round_trips(self):
        from textconverter.ast import Document, Paragraph, Text
        from textconverter.parsers.markdown_parser import parse_markdown
        from textconverter.renderers.markdown_renderer import render_markdown
        for literal in self.CASES:
            with self.subTest(literal=literal):
                doc = Document(children=[Paragraph(children=[Text(content=literal)])])
                back = parse_markdown(render_markdown(doc))
                self.assertEqual(back, doc, render_markdown(doc))

    def test_code_with_backticks(self):
        from textconverter.ast import CodeBlock, CodeInline, Document, Paragraph
        from textconverter.parsers.markdown_parser import parse_markdown
        from textconverter.renderers.markdown_renderer import render_markdown
        doc = Document(children=[
            Paragraph(children=[CodeInline(code="a`b")]),
            CodeBlock(code="```\nnested\n```", language="md"),
        ])
        self.assertEqual(parse_markdown(render_markdown(doc)), doc)

    def test_urls_with_spaces_and_parentheses(self):
        from textconverter.ast import Document, Link, Paragraph, Text
        from textconverter.parsers.markdown_parser import parse_markdown
        from textconverter.renderers.markdown_renderer import render_markdown
        for url in ("https://en.wikipedia.org/wiki/Foo_(bar)", "my file (1).pdf", "a)b"):
            with self.subTest(url=url):
                doc = Document(children=[Paragraph(children=[Link(url=url, content=[Text(content="x")])])])
                self.assertEqual(parse_markdown(render_markdown(doc)), doc, render_markdown(doc))

    def test_described_image_round_trips(self):
        """The description block the renderer writes is read back into Image.description."""
        from textconverter.ast import Document, Image, Paragraph
        from textconverter.images import lower_image_descriptions
        from textconverter.parsers.markdown_parser import parse_markdown
        from textconverter.renderers.markdown_renderer import render_markdown
        image = Image(src="imgs/my_pic.png", description="A *red* car.\n\n| a | b |\n|---|---|\n| 1 | 2 |",
                      category="photo_drawing_or_comic")
        doc = Document(children=[Paragraph(children=[image])])
        lower_image_descriptions(doc)
        back = parse_markdown(render_markdown(doc))
        (img,) = back.children[0].children
        self.assertEqual((img.src, img.category), ("imgs/my_pic.png", "photo_drawing_or_comic"))
        self.assertIn("| 1 | 2 |", img.description)


class TestCodeDetection(BaseConverterTest):

    def test_detected_code_is_not_altered(self):
        """Emphasis removal used to turn __init__ into init and a * b * c into a  b  c."""
        code = "def __init__(self, my_var):\n    self.my_var = a * b * c\n    return self.my_var"
        md = _md("Some intro text here.\n\n" + code, code_parsing=True)
        self.assertIn(code, md)
