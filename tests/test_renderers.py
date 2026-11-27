"""Behaviour shared by the Markdown, HTML, LaTeX and text renderers, checked on all of them.

Usage: python -m unittest discover -s tests -p "test_renderers.py"
"""
from __future__ import annotations

from textconverter.ast import (
    Citation, Document, Equation, Heading, LineBreak, Link, ListBlock, ListItem, Paragraph, Table, TableCell,
    TableRow, Text,
)
from textconverter.parsers.markdown_parser import parse_markdown
from textconverter.renderers.html_renderer import render_html
from textconverter.renderers.latex_renderer import render_latex
from textconverter.renderers.markdown_renderer import render_markdown
from textconverter.renderers.text_renderer import render_text
from _support import BaseConverterTest, setUpModule, tearDownModule


def _cell(text: str) -> TableCell:
    return TableCell(children=[Text(content=text)])


def _doc(*children) -> Document:
    return Document(children=list(children))


class TestTables(BaseConverterTest):

    def _ragged(self) -> Document:
        """No header; the first row is shorter than the second."""
        return _doc(Table(rows=[TableRow(cells=[_cell("a")]),
                                TableRow(cells=[_cell("b"), _cell("c"), _cell("LAST")])]))

    def test_no_renderer_drops_cells(self):
        """LaTeX used to size the table on its first row and cut the longer ones."""
        doc = self._ragged()
        for render in (render_markdown, render_html, render_latex):
            with self.subTest(render=render.__name__):
                self.assertIn("LAST", render(doc))
        self.assertIn("{|c|c|c|}", render_latex(doc))

    def test_rows_are_padded_to_the_widest(self):
        md = render_markdown(self._ragged())
        widths = {line.count("|") for line in md.splitlines() if line.startswith("|")}
        self.assertEqual(widths, {4})
        self.assertEqual(render_html(self._ragged()).count("<td>"), 6)

    def test_header_shorter_than_rows(self):
        doc = _doc(Table(headers=[_cell("H")], rows=[TableRow(cells=[_cell("x"), _cell("y")])]))
        self.assertIn("| H |  |", render_markdown(doc))
        self.assertIn("H &  \\\\", render_latex(doc))


class TestInlineFeatures(BaseConverterTest):

    def test_strikethrough_everywhere(self):
        doc = _doc(Paragraph(children=[Text(content="old", strikethrough=True)]))
        self.assertIn("~~old~~", render_markdown(doc))
        self.assertIn("<s>old</s>", render_html(doc))
        tex = render_latex(doc)
        self.assertIn(r"\sout{old}", tex)
        self.assertIn(r"\usepackage[normalem]{ulem}", tex)

    def test_latex_preamble_follows_content(self):
        cite = _doc(Paragraph(children=[Citation(keys=["k"], style="citet")]))
        self.assertIn(r"\usepackage{natbib}", render_latex(cite))
        self.assertNotIn(r"\usepackage{natbib}", render_latex(_doc(Paragraph(children=[Citation(keys=["k"])]))))
        math = render_latex(_doc(Equation(code="x")))
        self.assertIn(r"\usepackage{amsmath}", math)
        self.assertNotIn("amsmath", render_latex(_doc(Paragraph(children=[Text(content="x")]))))

    def test_equation_environments(self):
        """An align body used to be placed in an equation environment, which does not compile."""
        tex = render_latex(_doc(Equation(code="a &= b", env="align*")))
        self.assertIn("\\begin{align*}\na &= b\n\\end{align*}", tex)
        tex = render_latex(_doc(Equation(code="a &= b \\\\ c &= d")))
        self.assertIn("\\begin{aligned}", tex)
        self.assertIn("\\[\nx\n\\]", render_latex(_doc(Equation(code="x"))))
        self.assertIn("\\begin{equation}\nx\n\\end{equation}", render_latex(_doc(Equation(code="x", env="equation"))))
        self.assertIn("\\begin{equation}\n\\label{a} x\n\\end{equation}", render_latex(_doc(Equation(code="\\label{a} x"))))

    def test_latex_link_urls(self):
        doc = _doc(Paragraph(children=[Link(url="https://x.org/~u/a_b?q=1&r=50%#top", content=[Text(content="l")])]))
        tex = render_latex(doc)
        self.assertIn(r"\href{https://x.org/~u/a\_b?q=1\&r=50\%\#top}{l}", tex)

    def test_line_break_at_paragraph_edges_is_dropped_in_latex(self):
        """A LaTeX line break with no line before it is a compile error."""
        doc = _doc(Paragraph(children=[LineBreak(), Text(content="x"), LineBreak()]))
        body = render_latex(doc).split("\\begin{document}")[1]
        self.assertNotIn("\\\\", body)

    def test_html_neutralises_script_links(self):
        doc = _doc(Paragraph(children=[Link(url=" JavaScript:alert(1)", content=[Text(content="x")])]))
        self.assertIn('<a href="#">x</a>', render_html(doc))

    def test_html_escapes_reference_macros(self):
        doc = _doc(Paragraph(children=[Citation(keys=["a<b"])]))
        self.assertIn(r"\cite{a&lt;b}", render_html(doc))


class TestDisplayFormulas(BaseConverterTest):
    """A display formula inside a paragraph (as HTML pages and LaTeX write it)."""

    _FORMULA = Equation(code="a = b\n+ c", inline=False)

    def _paragraph(self) -> Document:
        return _doc(Paragraph(children=[Text(content="states that: "), self._FORMULA, Text(content=" where x")]))

    def test_text_formats_write_it_as_a_block_of_its_own(self):
        for render in (render_markdown, render_text):
            with self.subTest(render=render.__name__):
                out = render(self._paragraph())
                self.assertEqual(out, "states that:\n\n$$\na = b\n+ c\n$$\n\nwhere x\n")

    def test_markdown_reads_it_back_as_written(self):
        md = render_markdown(self._paragraph())
        doc = parse_markdown(md)
        self.assertEqual([type(c) for c in doc.children], [Paragraph, Equation, Paragraph])
        self.assertEqual(doc.children[1], self._FORMULA)
        self.assertEqual(render_markdown(doc), md)

    def test_in_a_list_item_it_stays_in_the_item(self):
        doc = _doc(ListBlock(ordered=False, items=[ListItem(children=[
            Paragraph(children=[Text(content="a "), self._FORMULA, Text(content=" b")])])]))
        md = render_markdown(doc)
        self.assertEqual(md, "- a\n\n    $$\n    a = b\n    + c\n    $$\n\n    b\n")
        (item,) = parse_markdown(md).children[0].items
        self.assertEqual(item.children[1], self._FORMULA)

    def test_where_only_inline_content_fits_it_keeps_to_one_line(self):
        doc = _doc(Heading(level=1, children=[Text(content="T "), self._FORMULA]),
                   Table(headers=[_cell("h")], rows=[TableRow(cells=[TableCell(children=[self._FORMULA])])]))
        md = render_markdown(doc)
        self.assertIn("# T $a = b + c$\n", md)
        self.assertIn("| $a = b + c$ |", md)
        heading, table = parse_markdown(md).children
        self.assertIsInstance(heading, Heading)
        self.assertIsInstance(table, Table)
        self.assertIn("| $$a = b + c$$ |", render_text(doc))

    def test_html_and_latex_keep_it_in_place(self):
        self.assertEqual(render_html(self._paragraph()).count("<p>"), 2)
        self.assertIn("states that: \\[\na = b\n+ c\n\\] where x", render_latex(self._paragraph()))

    def test_markdown_formula_lines_are_not_blocks(self):
        for line in ("+ c", "- c", "1. c", "# c", "> c"):
            with self.subTest(line=line):
                (equation,) = parse_markdown(f"$$\na = b\n{line}\n$$\n").children
                self.assertEqual(equation, Equation(code=f"a = b\n{line}", inline=False))
