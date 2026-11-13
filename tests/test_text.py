"""Plain text input and output: the block conventions, wrapped text, notes, encodings, round trips.

Usage: python -m unittest discover -s tests -p "test_text.py"
"""
from __future__ import annotations
import codecs
import tempfile
from pathlib import Path

from textconverter import ConvertOptions, convert, convert_text
from textconverter.ast import (
    Abstract, BlockQuote, CodeBlock, Document, Equation, Footnote, Heading, HorizontalRule, Image, LineBreak, Link,
    ListBlock, ListItem, Paragraph, Table, TableCell, TableRow, Text, walk,
)
from textconverter.formats import infer_input_format, infer_output_format
from textconverter.parsers.text_parser import parse_text
from textconverter.renderers._common import plain_text
from textconverter.renderers.json_renderer import render_json
from textconverter.renderers.text_renderer import render_text
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR  # noqa: F401


def _para(text: str) -> Paragraph:
    return Paragraph(children=[Text(content=text)])


def _blocks(doc: Document) -> list[str]:
    """The types of the document's blocks, empty paragraphs left out (text does not write them)."""
    return [type(node).__name__ for node in doc.children if not (isinstance(node, Paragraph) and not node.children)]


class TestTextRenderer(BaseConverterTest):

    def test_title_and_metadata(self):
        doc = Document(title=[Text(content="A Title")], author=[Text(content="Ada"), LineBreak(author_separator=True),
                                                                Text(content="Bob")], date=[Text(content="2026")])
        self.assertEqual(render_text(doc), "=======\nA Title\n=======\nAuthor: Ada \\and Bob\nDate: 2026\n")

    def test_headings_are_underlined_by_level(self):
        doc = Document(children=[Heading(level=1, children=[Text(content="One")]),
                                 Heading(level=2, children=[Text(content="Two")]),
                                 Heading(level=3, children=[Text(content="A")])])
        self.assertEqual(render_text(doc), "One\n===\n\nTwo\n---\n\nA\n~~~\n")

    def test_underline_counts_wide_characters_twice(self):
        doc = Document(children=[Heading(level=1, children=[Text(content="日本語")])])
        self.assertEqual(render_text(doc), "日本語\n======\n")

    def test_inline_markup_is_not_written(self):
        doc = Document(children=[Paragraph(children=[
            Text(content="bold", bold=True), Text(content=" and "), Link(url="https://a.org", content=[Text(content="a link")]),
            Text(content=" and "), Link(url="https://b.org", content=[Text(content="https://b.org")])])])
        self.assertEqual(render_text(doc), "bold and a link (https://a.org) and https://b.org\n")

    def test_lists_code_quote_and_rule(self):
        doc = Document(children=[
            ListBlock(ordered=False, items=[ListItem(children=[_para("a"), ListBlock(ordered=True, items=[
                ListItem(children=[_para("b")])])]), ListItem(children=[_para("c")], checked=True)]),
            CodeBlock(code="x = 1\n\n  y = 2"),
            BlockQuote(children=[_para("q")], alert_type="NOTE"),
            HorizontalRule()])
        self.assertEqual(render_text(doc), "- a\n  1. b\n- [x] c\n\n    x = 1\n\n      y = 2\n\n> [!NOTE]\n> q\n\n* * *\n")

    def test_grid_table(self):
        table = Table(headers=[TableCell(children=[Text(content="Name")]), TableCell(children=[Text(content="Value")])],
                      rows=[TableRow(cells=[TableCell(children=[Text(content="a"), LineBreak(), Text(content="b")]),
                                            TableCell(children=[Text(content="表")])])],
                      caption=[Text(content="Numbers")])
        self.assertEqual(render_text(Document(children=[table])),
                         "Table: Numbers\n\n"
                         "+------+-------+\n"
                         "| Name | Value |\n"
                         "+======+=======+\n"
                         "| a    | 表    |\n"
                         "| b    |       |\n"
                         "+------+-------+\n")

    def test_footnotes_are_numbered_at_the_end(self):
        doc = Document(children=[Paragraph(children=[
            Text(content="One"), Footnote(content=[Text(content="first"), Footnote(content=[Text(content="inner")])]),
            Text(content=" two"), Footnote(content=[Text(content="second")])])])
        self.assertEqual(render_text(doc), "One[1] two[2]\n\n[1] first[3]\n\n[2] second\n\n[3] inner\n")

    def test_display_formula(self):
        doc = Document(children=[Equation(code="a = b", env="align")])
        self.assertEqual(render_text(doc), "$$\n\\begin{align}\na = b\n\\end{align}\n$$\n")

    def test_images_are_dropped_by_default(self):
        md = "Before\n\n![logo](logo.png)\n\nAfter\n"
        self.assertEqual(convert_text(md, "markdown", "text"), "Before\n\nAfter\n")

    def test_a_description_stays_as_text(self):
        image = Image(src="logo.png", description="A red logo.", category="figure")
        source = render_json(Document(children=[Paragraph(children=[image])]))
        text = convert_text(source, "json", "text", ConvertOptions(image_handling="replace"))
        self.assertIn("A red logo.", text)
        self.assertNotIn("logo.png", text)


class TestTextParser(BaseConverterTest):

    def test_inline_text_stays_literal(self):
        doc = parse_text("*not italic* _nor_ `code` # nor heading\n")
        self.assertEqual(_blocks(doc), ["Paragraph"])
        self.assertEqual(plain_text(doc.children), "*not italic* _nor_ `code` # nor heading")

    def test_line_breaks_are_kept(self):
        doc = parse_text("Ada Lovelace\n12 Some Street\nLondon\n")
        self.assertEqual(sum(isinstance(n, LineBreak) for n in doc.children[0].children), 2)

    def test_text_wrapped_at_a_fixed_width_is_joined(self):
        words = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore "
                 "et dolore magna aliqua ut enim ad minim veniam quis nostrud exercitation ullamco laboris nisi").split()
        lines, line = [], ""
        for word in words * 2:
            if line and len(line) + 1 + len(word) > 60:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        lines.append(line)
        source = "\n".join(lines) + "\n\nBest regards,\nMario Rossi\nVia Roma 1\n"
        doc = parse_text(source)
        self.assertFalse(any(isinstance(n, LineBreak) for n in doc.children[0].children))
        self.assertEqual(plain_text(doc.children[0].children), " ".join(words * 2))
        self.assertEqual(sum(isinstance(n, LineBreak) for n in doc.children[1].children), 2, "a signature was joined")

    def test_short_lines_are_not_a_wrapped_text(self):
        """Verses of similar length look full, but nobody wraps text that narrow."""
        verse = "The woods are lovely, dark and deep,\nBut I have promises to keep,\nAnd miles to go before I sleep,\n"
        doc = parse_text(verse + "\n" + verse)
        self.assertEqual(sum(isinstance(n, LineBreak) for n in doc.children[0].children), 2)

    def test_blocks(self):
        source = ("Title\n=====\n\nSub\n---\n\n- a\n  - b\n- [ ] c\n\n3. x\n4. y\n\n    code\n\n> [!TIP]\n> quoted\n\n"
                  "* * *\n\n$$\nE = mc^2\n$$\n")
        doc = parse_text(source)
        self.assertEqual(_blocks(doc), ["Heading", "Heading", "ListBlock", "ListBlock", "CodeBlock", "BlockQuote",
                                        "HorizontalRule", "Equation"])
        self.assertEqual([h.level for h in doc.children[:2]], [1, 2])
        bullets, numbered = doc.children[2:4]
        self.assertIsInstance(bullets.items[0].children[1], ListBlock)
        self.assertIs(bullets.items[1].checked, False)
        self.assertEqual((numbered.ordered, numbered.start, len(numbered.items)), (True, 3, 2))
        self.assertEqual(doc.children[4].code, "code")
        self.assertEqual(doc.children[5].alert_type, "TIP")
        self.assertEqual(doc.children[7].code, "E = mc^2")

    def test_numbering_that_starts_again_is_another_list(self):
        doc = parse_text("1. a\n2. b\n\n1. c\n")
        self.assertEqual([len(lb.items) for lb in doc.children], [2, 1])

    def test_paragraph_is_interrupted_by_a_list(self):
        doc = parse_text("Ingredients:\n- eggs\n- milk\n")
        self.assertEqual(_blocks(doc), ["Paragraph", "ListBlock"])

    def test_grid_table(self):
        table = parse_text("+---+----+\n| a | 表 |\n+===+====+\n| 1 | x  |\n| 2 |    |\n+---+----+\n").children[0]
        self.assertEqual([plain_text(c.children) for c in table.headers], ["a", "表"])
        self.assertEqual(len(table.rows), 1)
        self.assertIsInstance(table.rows[0].cells[0].children[1], LineBreak)

    def test_title_metadata_and_abstract(self):
        doc = parse_text("=====\nTitle\n=====\nAuthor: Ada \\and Bob\nDate: 2026\n\n> Abstract:\n> Short.\n")
        self.assertEqual(plain_text(doc.title), "Title")
        self.assertTrue(any(isinstance(n, LineBreak) and n.author_separator for n in doc.author))
        self.assertEqual(plain_text(doc.date), "2026")
        self.assertIsInstance(doc.children[0], Abstract)
        self.assertEqual(plain_text(doc.children[0].children), "Short.")

    def test_urls_and_macros(self):
        children = parse_text("See https://example.org/a. and \\cite{key}.\n").children[0].children
        self.assertEqual([type(n).__name__ for n in children], ["Text", "Link", "Text", "Citation", "Text"])
        self.assertEqual(children[1].url, "https://example.org/a")

    def test_footnotes_need_their_definitions(self):
        doc = parse_text("One[1] two[2].\n\n[1] First.\n\n[2] Second.\n")
        notes = [n for n in walk(doc) if isinstance(n, Footnote)]
        self.assertEqual([plain_text(n.content) for n in notes], ["First.", "Second."])
        self.assertEqual(len(doc.children), 1)
        undefined = parse_text("As shown in [1] and [2].\n")
        self.assertFalse(any(isinstance(n, Footnote) for n in walk(undefined)))

    def test_a_note_in_a_note(self):
        source = render_text(Document(children=[Paragraph(children=[
            Text(content="a"), Footnote(content=[Text(content="b"), Footnote(content=[Text(content="c")])])])]))
        outer = parse_text(source).children[0].children[1]
        self.assertIsInstance(outer.content[1], Footnote)
        self.assertEqual(plain_text(outer.content[1].content), "c")

    def test_tabs_after_the_indentation_are_code(self):
        doc = parse_text("    if x:\n    \treturn 1\n")
        self.assertEqual(doc.children[0].code, "if x:\n\treturn 1")


class TestTextFiles(BaseConverterTest):

    def test_extensions(self):
        self.assertEqual(infer_input_format("notes.TXT"), "text")
        self.assertEqual(infer_output_format("out.txt"), "text")

    def test_encodings(self):
        text = "Città perché\n"
        for name, data in (("utf8", text.encode("utf-8")), ("bom", codecs.BOM_UTF8 + text.encode("utf-8")),
                           ("cp1252", text.encode("cp1252")), ("utf16", text.encode("utf-16"))):
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / "a.txt"
                src.write_bytes(data)
                self.assertEqual(convert(str(src), "markdown"), "Città perché\n")

    def test_code_parsing_fences_unindented_code(self):
        source = "Run this:\n\nimport os\nprint(os.getcwd())\n"
        doc_text = convert_text(source, "text", "markdown", ConvertOptions(code_parsing=True))
        self.assertIn("```", doc_text)

    def test_round_trip_is_identical(self):
        """Every structured fixture, written as text, reads back to the same text."""
        for name in ("SampleMD.md", "SampleLatex.tex", "Journal TEX.tex", "Test_docx.docx", "Test_slides.pptx",
                     "Test_sheets.xlsx", "WikipediaSample.html"):
            with self.subTest(name):
                text = convert(str(INPUT_DIR / name), "text")
                self.assertEqual(convert_text(text, "text", "text"), text)

    def test_markdown_keeps_its_blocks(self):
        source = (INPUT_DIR / "SampleMD.md").read_text(encoding="utf-8")
        # Text holds no images: the paragraphs that only had one go
        markdown = convert_text(source, "markdown", "json", ConvertOptions(image_handling="discard"))
        through_text = convert_text(convert_text(source, "markdown", "text"), "text", "json")
        from textconverter.parsers.json_parser import parse_json
        self.assertEqual(_blocks(parse_json(through_text)), _blocks(parse_json(markdown)))
