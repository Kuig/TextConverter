"""HTML parsing: structure, tables with spans, main-content extraction.

Usage: python -m unittest discover -s tests -p "test_html.py"
"""
from __future__ import annotations

import textconverter
from _support import BaseConverterTest, setUpModule, tearDownModule


class TestHtmlParser(BaseConverterTest):

    def test_sample_html_to_markdown(self):
        """SampleHtml.htm → MD: text content, lists, table, links survive parsing."""
        content = self.convert_fixture("SampleHtml.htm", "SampleHtml.md")
        # Headings
        self.assertIn("Titolo di Livello 1", content, "Missing h1 content")
        self.assertIn("Sottotitolo di Livello 2", content, "Missing h2 content")
        # Table content
        self.assertIn("Mario Rossi", content, "Missing table row content")
        self.assertIn("Laura Bianchi", content, "Missing table row content")
        # List items
        self.assertIn("grassetto", content, "Missing list item content")
        self.assertIn("corsivo", content, "Missing list item content")
        # Link preserved
        self.assertIn("https://www.google.it", content, "Missing hyperlink")

    def test_html_table_colspan_rowspan(self):
        """HTML colspan/rowspan flatten to a rectangular grid in every target."""
        import json as _json
        html = (
            "<table><tbody>"
            "<tr><td rowspan='2'>ID</td><td colspan='2'>Group</td><td rowspan='2'>Tail</td></tr>"
            "<tr><td>G1</td><td>G2</td></tr>"
            "<tr><td>1</td><td><div>Left</div><div>Right</div></td><td>x</td><td>y</td></tr>"
            "</tbody></table>"
        )

        def _data_rows(md_text):
            return [l for l in md_text.splitlines()
                    if l.strip().startswith("|") and set(l.strip()) - set("|-: ")]

        md = textconverter.convert_text(html, "html", "markdown")
        rows = _data_rows(md)
        self.assertEqual(len({l.count("|") for l in rows}), 1, f"ragged markdown table: {rows}")
        self.assertIn("Left Right", md, "adjacent <div> cell text glued together")
        self.assertNotIn("LeftRight", md)

        # extract_html path strips unknown attrs; colspan/rowspan must survive it too.
        md_x = textconverter.convert_text(html, "html", "markdown", textconverter.ConvertOptions(extract_html=True))
        self.assertEqual(len({l.count("|") for l in _data_rows(md_x)}), 1, "ragged table after extract_html")

        tex = textconverter.convert_text(html, "html", "latex")
        body = [l for l in tex.splitlines() if l.rstrip().endswith("\\\\") and "&" in l]
        self.assertTrue(body)
        self.assertEqual(len({l.count("&") for l in body}), 1, f"ragged latex table: {body}")

        ast = textconverter.convert_text(html, "html", "json")
        self.assertNotIn("_colspan", ast)
        self.assertNotIn("_rowspan", ast)
        table = _json.loads(ast)["children"][0]
        self.assertEqual({len(r["cells"]) for r in table["rows"]}, {4})

    def test_main_content_extraction(self):
        """MainContentTest.html → MD with extract_html=True: only main block, no nav/footer."""
        content = self.convert_fixture("MainContentTest.html", "MainContentTest.md", extract_html=True)
        self.assertIn("Main Title", content, "Missing main content title")
        self.assertIn("This is the main content.", content, "Missing main content paragraph")
        self.assertNotIn("Footer info", content, "Footer should be stripped")
        self.assertNotIn("Home", content, "Nav should be stripped")


def _md(html: str, **options) -> str:
    return textconverter.convert_text(html, "html", "markdown", textconverter.ConvertOptions(**options))


class TestHtmlRobustness(BaseConverterTest):
    """Malformed or real-world HTML that used to lose or corrupt content."""

    def test_extraction_keeps_escaped_markup_as_text(self):
        """The pre-pass decoded entities and re-emitted them as tags."""
        page = ('<html><body><main><p>a &lt;b&gt; c</p><pre><code>&lt;div&gt;</code></pre>'
                '<img src="x.png" alt="say &quot;hi&quot; ok"></main></body></html>')
        md = _md(page, extract_html=True)
        self.assertIn(r"a \<b> c", md)  # escaped: "<b>" would be read as bold
        self.assertIn("<div>", md)
        self.assertIn('say "hi" ok', md)

    def test_unclosed_items_in_dropped_navigation_keep_the_page(self):
        """Omitted </li> inside <nav> used to make the rest of the page vanish."""
        md = _md("<html><body><nav><ul><li>a<li>b</ul></nav><p>content</p></body></html>", extract_html=True)
        self.assertIn("content", md)
        self.assertNotIn("- a", md)

    def test_stray_end_tag_does_not_end_the_main_block_early(self):
        md = _md("<body><main><div></span><p>one</p></div><p>two</p></main><p>out</p></body>", extract_html=True)
        self.assertIn("one", md)
        self.assertIn("two", md)
        self.assertNotIn("out", md)

    def test_void_tags_do_not_leak_formatting(self):
        """<br> inside <b> used to make the text after </b> bold."""
        self.assertEqual(_md("<p><b>bold<br>still</b> after</p>").strip(), "**bold**  \n**still** after")

    def test_whitespace(self):
        """Source line breaks are spaces; a space between inline elements survives."""
        self.assertEqual(_md("<p>hello\n   world <b>bold</b> <i>it</i></p>").strip(), "hello world **bold** _it_")

    def test_code_end_tag_inside_pre_keeps_the_quote_open(self):
        md = _md("<blockquote><pre><code>x</code></pre><p>after</p></blockquote>")
        self.assertIn("> after", md)

    def test_header_row_without_thead(self):
        """A first row of <th> is the header (the usual Wikipedia table)."""
        md = _md("<table><tr><th>H1</th><th>H2</th></tr><tr><td>1</td><td>2</td></tr></table>")
        self.assertEqual(md.splitlines()[:3], ["| H1 | H2 |", "|---|---|", "| 1 | 2 |"])

    def test_unclosed_rows_and_cells(self):
        md = _md("<table><tr><th>A<th>B<tr><td>1<td>2<tr><td>3<td>4</table>")
        self.assertEqual(md.splitlines(), ["| A | B |", "|---|---|", "| 1 | 2 |", "| 3 | 4 |"])

    def test_title_is_a_heading_only_without_h1(self):
        self.assertTrue(_md("<html><head><title>T</title></head><body><p>x</p></body></html>").startswith("# T"))
        self.assertNotIn("# T", _md("<html><head><title>T</title></head><body><h1>Main</h1></body></html>"))

    def test_round_trip_adds_no_document_heading_and_keeps_the_language(self):
        """md → html → md used to add '# Document' and drop the code language."""
        html = textconverter.convert_text("```python\nx = 1\n```", "markdown", "html")
        md = textconverter.convert_text(html, "html", "markdown")
        self.assertEqual(md.strip(), "```python\nx = 1\n```")

    def test_code_language_needs_a_language_class(self):
        md = _md('<pre class="highlight"><code class="lang-rust">fn</code></pre>')
        self.assertIn("```rust", md)
        self.assertIn("```\n", _md('<pre class="highlight python">x</pre>'))

    def test_lazy_loaded_image_source(self):
        md = _md('<p><img src="data:image/gif;base64,R0lG" data-src="real.png" alt="a">'
                 '<img srcset="small.png 1x, big.png 2x" alt="b"></p>')
        self.assertIn("![a](real.png)", md)
        self.assertIn("![b](small.png)", md)

    def test_strikethrough(self):
        self.assertIn("~~gone gone~~", _md("<p>a <s>gone</s> <del>gone</del></p>"))

    def test_abstraction_is_not_an_abstract(self):
        self.assertNotIn("**Abstract**", _md("<blockquote><p>Abstraction is key</p></blockquote>"))
        self.assertIn("**Abstract**", _md("<blockquote><p>Abstract: we study x</p></blockquote>"))


def _html(html: str) -> str:
    """HTML → HTML, body only."""
    out = textconverter.convert_text(html, "html", "html")
    return out.split("<body>")[1].split("</body>")[0].strip()


def _parse(html: str):
    from textconverter.parsers.html_parser import parse_html
    return parse_html(html)


class TestHtmlStructures(BaseConverterTest):
    """Captions, figures, stray content, scripts, lists and TextConverter's own markers."""

    def test_table_caption_is_the_caption_not_a_header(self):
        html = "<table><caption>Cap</caption><tr><th>A</th></tr><tr><td>1</td></tr></table>"
        (table,) = _parse(html).children
        self.assertEqual([c.children[0].content for c in table.headers], ["A"])
        self.assertEqual(table.caption[0].content, "Cap")
        self.assertIn("<caption>Cap</caption>", _html(html))
        self.assertEqual(_md(html).splitlines()[0], "Table: Cap")

    def test_stray_content_in_lists_and_tables_is_kept(self):
        """Text directly in <ul>, <table> or <tr> used to crash the renderers."""
        self.assertEqual(_md("<ul>stray<li>a</li></ul>").strip(), "- stray\n- a")
        md = _md("<table>before<tr>row text<td>1</td></tr></table>")
        self.assertTrue(md.startswith("before row text\n\n|"), md)
        for html in ("<ul>x<li>a</li></ul>", "<table>t<tr><td>1</td></tr></table>"):
            with self.subTest(html=html):
                _html(html)

    def test_cell_outside_a_row_opens_one(self):
        self.assertIn("| 1 | 2 |", _md("<table><td>1</td><td>2</td></table>"))

    def test_figure_caption_and_label_round_trip(self):
        html = ('<figure data-label="fig:a"><a href="big.png"><img src="f.png" alt="F"></a>'
                '<figcaption>The <b>caption</b></figcaption></figure>')
        doc = _parse(html)
        image = next(n for n in __import__("textconverter").ast.walk(doc)
                     if isinstance(n, __import__("textconverter").ast.Image))
        self.assertEqual(image.label, "fig:a")
        self.assertEqual([t.content for t in image.caption], ["The ", "caption"])
        out = _html(html)
        self.assertIn('<figure data-label="fig:a">', out)
        self.assertNotIn("<p><figure", out)
        self.assertEqual(_parse(out), doc)
        self.assertIn("Figure: The **caption**", _md(html))

    def test_a_discarded_figure_takes_its_caption_with_it(self):
        md = _md('<figure><img src="f.png"><figcaption>Cap</figcaption></figure><p>after</p>', image_handling="discard")
        self.assertEqual(md.strip(), "after")

    def test_anchor_without_href_is_plain_text(self):
        self.assertEqual(_md("<p>x <a name='top'>anchor</a> y</p>").strip(), "x anchor y")

    def test_mathml_without_tex_keeps_its_text(self):
        from textconverter.ast import Equation
        (para,) = _parse("<p>m <math><mi>x</mi><mo>+</mo><mn>1</mn></math> e</p>").children
        self.assertIn(Equation(code="x+1", inline=True), para.children)
        (para,) = _parse("<p>m <math></math> e</p>").children
        self.assertFalse(any(isinstance(n, Equation) for n in para.children))

    def test_superscript_and_subscript(self):
        from textconverter.ast import Text
        (para,) = _parse("<p>H<sub>2</sub>O and x<sup>2</sup></p>").children
        self.assertIn(Text(content="2", script="sub"), para.children)
        self.assertEqual(_html("<p>H<sub>2</sub>O and x<sup>2</sup></p>"), "<p>H<sub>2</sub>O and x<sup>2</sup></p>")

    def test_list_start_and_task_items(self):
        html = ('<ol start="3"><li>three</li></ol>'
                '<ul><li><input type="checkbox" checked> done</li><li><input type="checkbox"> todo</li></ul>')
        ordered, tasks = _parse(html).children
        self.assertEqual(ordered.start, 3)
        self.assertEqual([i.checked for i in tasks.items], [True, False])
        out = _html(html)
        self.assertIn('<ol start="3">', out)
        self.assertIn('<li><input type="checkbox" disabled checked /> done</li>', out)
        self.assertEqual(_parse(out), _parse(html))

    def test_tight_list_and_display_formula_outside_paragraphs(self):
        self.assertIn("<li>a</li>", _html("<ul><li><p>a</p></li></ul>"))
        out = textconverter.convert_text(r"x \[ a+b \] y", "latex", "html")
        self.assertNotIn("<p><div", out)

    def test_page_title(self):
        out = textconverter.convert_text("# Main *title*\n\ntext", "markdown", "html")
        self.assertIn("<title>Main title</title>", out)
        self.assertIn("<title>Document</title>", textconverter.convert_text("text", "markdown", "html"))

    def test_metadata_round_trip(self):
        from textconverter.ast import Document, Paragraph, Text
        from textconverter.renderers.html_renderer import render_html
        doc = Document(title=[Text(content="T", bold=True)], author=[Text(content="A")],
                       date=[Text(content="2026")], children=[Paragraph(children=[Text(content="x")])])
        out = render_html(doc)
        self.assertIn("<title>T</title>", out)
        self.assertEqual(_parse(out), doc)
        self.assertEqual(_parse(textconverter.convert_text(out, "html", "html", textconverter.ConvertOptions(
            extract_html=True))), doc)

    def test_wikipedia_backlinks_go_with_the_citation_marks(self):
        content = self.convert_fixture("WikipediaSample.html", "WikipediaSample_clean.md", extract_html=True)
        self.assertIn("Full citation text for reference one.", content)
        self.assertNotIn("cite_ref", content)


class TestHtmlReferenceMacros(BaseConverterTest):
    """LaTeX reference macros are kept visible in HTML and read back from it."""

    TEX = r"A\footnote{Nota \textbf{b}.} \cite{a,b} \citet{c} \citep[e.g.][p.~3]{d} see \ref{sec:x}."

    def test_latex_html_latex_is_identical(self):
        tex = textconverter.convert_text(self.TEX, "latex", "latex")
        html = textconverter.convert_text(self.TEX, "latex", "html")
        self.assertIn(r'<span class="tc-ref">\cite{a,b}</span>', html)
        self.assertEqual(textconverter.convert_text(html, "html", "latex"), tex)
        self.assertEqual(textconverter.convert_text(html, "html", "markdown"),
                         textconverter.convert_text(self.TEX, "latex", "markdown"))

    def test_bare_macros_in_textconverter_html(self):
        """HTML written by 0.3.0 carried the macros as plain text."""
        from textconverter.ast import Citation, Footnote, Text
        body = r"<p>A\footnote{Nota <b>b</b>.} \cite{a,b} and \ref{x} <code>\cite{no}</code></p>"
        ours = '<html><head><meta name="generator" content="TextConverter"></head><body>' + body
        (para,) = _parse(ours).children
        self.assertIn(Footnote(content=[Text(content="Nota "), Text(content="b", bold=True), Text(content=".")]),
                      para.children)
        self.assertIn(Citation(keys=["a", "b"]), para.children)
        self.assertIn(r"\cite{no}", textconverter.convert_text(ours, "html", "markdown"))
        (other,) = _parse("<html><body>" + body).children
        self.assertFalse(any(isinstance(n, (Citation, Footnote)) for n in other.children))


class TestHtmlTableHeaders(BaseConverterTest):

    def _grid(self, html: str) -> tuple[list[str], list[list[str]]]:
        from textconverter.renderers._common import plain_text
        (table,) = _parse(html).children
        return ([plain_text(c.children) for c in table.headers],
                [[plain_text(c.children) for c in row.cells] for row in table.rows])

    def test_a_second_head_row_opens_the_body(self):
        html = "<table><thead><tr><th>A</th></tr><tr><th>B</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>"
        self.assertEqual(self._grid(html), (["A"], [["B"], ["1"]]))

    def test_a_first_row_of_spanning_headers_is_the_header(self):
        html = "<table><tr><th colspan=2>A</th><th>B</th></tr><tr><td>1</td><td>2</td><td>3</td></tr></table>"
        self.assertEqual(self._grid(html), (["A", "", "B"], [["1", "2", "3"]]))

    def test_a_nested_table_is_the_text_of_its_cell(self):
        html = ("<table><tr><th>A</th></tr><tr><td><table><tr><td>x</td><td>y</td></tr><tr><td>z</td></tr></table></td></tr></table>")
        (table,) = _parse(html).children
        from textconverter.ast import Table, walk
        self.assertEqual(sum(isinstance(n, Table) for n in walk(table)), 1)
        self.assertEqual(self._grid(html)[1], [["x y\nz"]])
        self.assertIn("| x y<br>z |", textconverter.convert_text(html, "html", "markdown"))


class TestHtmlBibliography(BaseConverterTest):

    def test_it_is_marked_and_read_back(self):
        tex = "\\begin{document}\n\\begin{thebibliography}{9}\n\\bibitem{a} A.\n\\end{thebibliography}\n\\end{document}"
        html = textconverter.convert_text(tex, "latex", "html")
        self.assertIn('class="tc-bib"', html)
        self.assertIn('"type": "Bibliography"', textconverter.convert_text(html, "html", "json"))
