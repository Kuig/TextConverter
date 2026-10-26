"""HTML parsing: structure, tables with spans, main-content extraction.

Usage: python -m unittest discover -s tests -p "test_html.py"
"""
from __future__ import annotations

import textconverter
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR, read


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
        self.assertIn("a <b> c", md)
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
        self.assertIn("~~gone~~", _md("<p>a <s>gone</s> <del>gone</del></p>"))

    def test_abstraction_is_not_an_abstract(self):
        self.assertNotIn("**Abstract**", _md("<blockquote><p>Abstraction is key</p></blockquote>"))
        self.assertIn("**Abstract**", _md("<blockquote><p>Abstract: we study x</p></blockquote>"))
