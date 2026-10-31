"""Markdown parsing and rendering, including tables and code detection.

Usage: python -m unittest discover -s tests -p "test_markdown.py"
"""
from __future__ import annotations

import textconverter
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR


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
        self.assertIn(Citation(keys=["knuth"], style="citet*"), children)

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
        "~edge tildes~",
        "2*3*4 and a_b_c and __init__ and ___",
        "a <b>tag</b>, <https://x.org> and <me@x.org>",
        "see https://x.org/a_b or www.x.org in plain text",
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


class TestMarkdownBlocks(BaseConverterTest):
    """Block syntax: fences, lists, setext headings, captions, front matter, footnotes, line breaks."""

    def assertStable(self, md: str):
        """Markdown → Markdown is a fixed point after one pass."""
        once = _md(md)
        self.assertEqual(_md(once), once)

    def test_tilde_fence_is_code_not_strikethrough(self):
        from textconverter.ast import CodeBlock
        self.assertEqual(_doc("~~~python\nprint(1)\n~~~").children, [CodeBlock(code="print(1)", language="python")])
        self.assertIn("<s>a</s>", _md("~~a~~ and ~~~b~~~", to="html"))
        self.assertNotIn("<s>b", _md("~~a~~ and ~~~b~~~", to="html"))

    def test_fence_at_column_zero_ends_the_list(self):
        from textconverter.ast import CodeBlock, ListBlock
        doc = _doc("1. a\n2. b\n\n```\ncode\n```\n\n1. c\n2. d\n")
        self.assertEqual([type(n) for n in doc.children], [ListBlock, CodeBlock, ListBlock])
        self.assertEqual(len(doc.children[0].items), 2)
        doc = _doc("- a\n\n    ```\n    code\n    ```\n")
        self.assertIsInstance(doc.children[0].items[0].children[-1], CodeBlock)

    def test_second_paragraph_stays_in_its_item(self):
        from textconverter.ast import ListBlock, Paragraph
        md = "- item\n\n  second para\n\n- item2\n"
        (lst,) = _doc(md).children
        self.assertIsInstance(lst, ListBlock)
        self.assertEqual([len(i.children) for i in lst.items], [2, 1])
        self.assertIsInstance(lst.items[0].children[1], Paragraph)
        self.assertStable(md)
        self.assertEqual(_doc(_md(md)), _doc(md))

    def test_setext_headings(self):
        from textconverter.ast import Paragraph
        doc = _doc("Title\n=====\n\nSub\n---\n\ntext\n\n---\n")
        self.assertEqual([(type(n).__name__, getattr(n, "level", None)) for n in doc.children],
                         [("Heading", 1), ("Heading", 2), ("Paragraph", None), ("HorizontalRule", None)])
        # Literal lines that look like underlines are escaped, so they stay text
        from textconverter.ast import Document, Text
        from textconverter.renderers.markdown_renderer import render_markdown
        doc = Document(children=[Paragraph(children=[Text(content="a\n---\nb\n===")])])
        self.assertEqual(_doc(render_markdown(doc)), doc)

    def test_list_start_and_task_items(self):
        doc = _doc("3. three\n4. four\n\n- [ ] todo\n- [x] done\n")
        self.assertEqual(doc.children[0].start, 3)
        self.assertEqual([i.checked for i in doc.children[1].items], [False, True])
        out = _md("3. three\n4. four\n\n- [ ] todo\n- [x] done\n")
        self.assertIn("3. three\n4. four", out)
        self.assertIn("- [ ] todo\n- [x] done", out)

    def test_headerless_table_round_trips(self):
        from textconverter.ast import Document, Table, TableCell, TableRow, Text
        from textconverter.renderers.markdown_renderer import render_markdown
        doc = Document(children=[Table(rows=[TableRow(cells=[TableCell(children=[Text(content="A")])])])])
        self.assertEqual(_doc(render_markdown(doc)), doc)

    def test_captions_and_labels(self):
        md = "Table: The *caption* \\label{tab:a}\n\n| A |\n|---|\n| 1 |\n\n![x](f.png)\n\nFigure: Fig \\label{fig:a}\n"
        table, para = _doc(md).children
        self.assertEqual((table.label, table.caption[-1].content), ("tab:a", "caption"))
        (image,) = para.children
        self.assertEqual((image.label, image.caption[0].content), ("fig:a", "Fig"))
        self.assertStable(md)
        self.assertIn("<caption>The <i>caption</i></caption>", _md(md, to="html"))

    def test_front_matter(self):
        md = '---\ntitle: "The **title**"\nauthor: \'A. B.\'\ndate: 2026\nlayout: post\n---\n\ntext\n'
        doc = _doc(md)
        self.assertEqual([t.content for t in doc.title], ["The ", "title"])
        self.assertEqual(doc.author[0].content, "A. B.")
        self.assertEqual(doc.date[0].content, "2026")
        self.assertEqual(_md(md).splitlines()[:5], ['---', 'title: "The **title**"', 'author: "A. B."',
                                                    'date: "2026"', '---'])
        self.assertStable(md)
        self.assertEqual(_doc("---\nnot front matter\n---\n").title, [])

    def test_gfm_footnotes(self):
        from textconverter.ast import Footnote, Text
        doc = _doc("A[^n] and B[^2].\n\n[^n]: First *note*.\n[^2]: Second\n    continued.\n")
        notes = [n for n in doc.children[0].children if isinstance(n, Footnote)]
        self.assertEqual(notes[0].content[1], Text(content="note", italic=True))
        self.assertEqual(notes[1].content, [Text(content="Second continued.")])
        out = _md("A\\footnote{x} B[^9].\n\n[^9]: y\n")
        self.assertEqual(out, "A[^1] B[^2].\n\n[^1]: x\n[^2]: y\n")
        # An undefined note stays text (escaped, so it cannot become one)
        self.assertEqual(_md("[^1] undefined"), "\\[^1\\] undefined\n")

    def test_soft_line_breaks_are_spaces(self):
        from textconverter.ast import Text
        self.assertEqual(_doc("a\nb").children[0].children, [Text(content="a b")])
        self.assertEqual(_doc("a  \nb").children[0].children, [Text(content="a\nb")])
        self.assertEqual(_doc("a\\\nb").children[0].children, [Text(content="a\nb")])

    def test_quote_paragraphs_stay_apart(self):
        md = "> first\n>\n> second\n"
        self.assertEqual(len(_doc(md).children[0].children), 2)
        self.assertStable(md)

    def test_math_environment_round_trip(self):
        from textconverter.ast import Equation
        tex = "\\begin{align}a&=b\\\\c&=d\\end{align}"
        md = textconverter.convert_text(tex, "latex", "markdown")
        self.assertEqual(_doc(md).children, [Equation(code="a&=b\\\\c&=d", env="align")])
        self.assertEqual(textconverter.convert_text(md, "markdown", "latex"),
                         textconverter.convert_text(tex, "latex", "latex"))


class TestMarkdownInline(BaseConverterTest):
    """Inline syntax: CommonMark emphasis, autolinks and bare URLs, inline HTML, sup/sub."""

    @staticmethod
    def _styles(md: str) -> list[tuple]:
        from textconverter.ast import Text
        return [(n.content, n.bold, n.italic) if isinstance(n, Text) else type(n).__name__
                for n in _doc(md).children[0].children]

    @staticmethod
    def _render(*nodes) -> str:
        from textconverter.ast import Document, Paragraph
        from textconverter.renderers.markdown_renderer import render_markdown
        return render_markdown(Document(children=[Paragraph(children=list(nodes))])).strip()

    def test_emphasis_follows_commonmark(self):
        self.assertEqual(self._styles("***x*** ___y___"), [("x", True, True), (" ", False, False), ("y", True, True)])
        self.assertEqual(self._styles("*a **b** c*"), [("a ", False, True), ("b", True, True), (" c", False, True)])
        self.assertEqual(self._styles("**bold *it* bold**"),
                         [("bold ", True, False), ("it", True, True), (" bold", True, False)])
        self.assertEqual(self._styles("***a** b*"), [("a", True, True), (" b", False, True)])
        self.assertEqual(self._styles("2*3*4"), [("2", False, False), ("3", False, True), ("4", False, False)])
        # A closer after a space closes nothing; emphasis may span other inline nodes
        self.assertEqual(self._styles("**Keywords: **kw"), [("**Keywords: **kw", False, False)])
        self.assertEqual(self._styles("**a `c` b**"), [("a ", True, False), "CodeInline", (" b", True, False)])

    def test_markers_nest_and_keep_spaces_outside(self):
        from textconverter.ast import Text
        self.assertEqual(self._render(Text(content="Keywords: ", bold=True), Text(content="kw")), "**Keywords:** kw")
        self.assertEqual(self._render(Text(content="a "), Text(content="b", bold=True), Text(content=" c")),
                         "a **b** c")
        nested = [Text(content="a ", italic=True), Text(content="b", bold=True, italic=True),
                  Text(content=" c", italic=True)]
        self.assertEqual(self._render(*nested), "_a **b** c_")
        self.assertEqual(_doc(self._render(*nested)).children[0].children, nested)
        # Inside a word italic needs "*"; where no marker can open or close, HTML does
        self.assertEqual(self._render(Text(content="foo"), Text(content="bar", italic=True)), "foo*bar*")
        self.assertEqual(self._render(Text(content="x"), Text(content="(a)", bold=True), Text(content="y")),
                         "x<strong>(a)</strong>y")

    def test_styled_text_round_trips(self):
        """Random runs of styled text come back unchanged (whitespace may change style)."""
        import random
        from textconverter.ast import Text
        rng = random.Random(4)
        pieces = ["a", "bc", "1", "x_y", "*", "_", "~", "(", ")", ":", ".", "\\", "<", "[", "`", " "]
        for _ in range(500):
            nodes = [Text(content="".join(rng.choice(pieces) for _ in range(rng.randint(1, 4))).strip() or "z",
                          bold=rng.random() < .4, italic=rng.random() < .4, strikethrough=rng.random() < .15,
                          script=rng.choice([None] * 8 + ["sup", "sub"]))
                     for _ in range(rng.randint(1, 5))]
            md = self._render(*nodes)
            flat = lambda ns: [(c, n.bold, n.italic, n.strikethrough, n.script) for n in ns
                               for c in n.content if not c.isspace()]
            with self.subTest(md=md):
                self.assertEqual(flat(_doc(md).children[0].children), flat(nodes))

    def test_autolinks_and_bare_urls(self):
        from textconverter.ast import Link
        links = lambda md: [(n.url, n.content[0].content) for n in _doc(md).children[0].children
                            if isinstance(n, Link)]
        self.assertEqual(links("<https://a.org/x> and <me@x.org>"),
                         [("https://a.org/x", "https://a.org/x"), ("mailto:me@x.org", "me@x.org")])
        self.assertEqual(links("(see https://x.org/a_(b)), www.y.org."),
                         [("https://x.org/a_(b)", "https://x.org/a_(b)"), ("http://www.y.org", "www.y.org")])
        self.assertEqual(links("[go to https://x.org](https://y.org)"), [("https://y.org", "go to https://x.org")])
        # Written back bare when spaces surround it, else as an autolink
        self.assertEqual(_md("see https://x.org/a now"), "see https://x.org/a now\n")
        self.assertEqual(_md("see <https://x.org/a>."), "see <https://x.org/a>.\n")

    def test_inline_html(self):
        from textconverter.ast import CodeInline, LineBreak, Text
        children = _doc("H<sub>2</sub>O x<sup>2</sup> <kbd>Ctrl</kbd> <em>e</em><br><span>s</span>").children[0].children
        self.assertIn(Text(content="2", script="sub"), children)
        self.assertIn(Text(content="2", script="sup"), children)
        self.assertIn(CodeInline(code="Ctrl"), children)
        self.assertIn(Text(content="e", italic=True), children)
        self.assertIn(LineBreak(), children)
        self.assertIn(Text(content="s"), children)  # any other tag keeps its text
        self.assertEqual(self._render(Text(content="x"), Text(content="2", script="sup")), "x<sup>2</sup>")


class TestFencedCode(BaseConverterTest):

    def test_indentation_of_the_code_is_kept(self):
        for code in ("    x\n        y", "\tx\n\ty", "  a\nb"):
            with self.subTest(code):
                self.assertEqual(_doc(f"```\n{code}\n```\n").children[0].code, code)

    def test_only_the_indentation_of_the_fence_is_removed(self):
        from textconverter.ast import CodeBlock, ListBlock
        (block,) = _doc("  ```\n  x\n      y\n  ```\n").children
        self.assertEqual(block.code, "x\n    y")
        (lst,) = _doc("- a\n\n    ```\n    x\n        y\n    ```\n").children
        self.assertIsInstance(lst, ListBlock)
        self.assertEqual(lst.items[0].children[-1], CodeBlock(code="x\n    y"))

    def test_the_round_trip_is_stable(self):
        source = "```python\n    x = 1\n\n\ty = 2\n```\n"
        self.assertEqual(_md(source), source)

    def test_an_unclosed_fence_is_code_up_to_the_end_with_a_warning(self):
        from unittest.mock import patch
        from textconverter.ast import CodeBlock, Paragraph
        with patch("textconverter.parsers.markdown_parser.log_warning") as warn:
            doc = _doc("Before\n\n```python\ndef f():\n    return 1\n\n# Not a title\n")
        self.assertEqual([type(n) for n in doc.children], [Paragraph, CodeBlock])
        self.assertEqual(doc.children[1], CodeBlock(code="def f():\n    return 1\n\n# Not a title", language="python"))
        warn.assert_called_once()


class TestIndentedCode(BaseConverterTest):

    def test_an_indented_block_is_code(self):
        from textconverter.ast import CodeBlock
        doc = _doc("text\n\n    code\n      more\n\n    again\n\nafter\n")
        self.assertEqual(doc.children[1], CodeBlock(code="code\n  more\n\nagain"))
        self.assertEqual(len(doc.children), 3)

    def test_a_tab_counts(self):
        from textconverter.ast import CodeBlock
        self.assertEqual(_doc("\tcode\n").children[0], CodeBlock(code="code"))

    def test_a_paragraph_cannot_be_interrupted(self):
        from textconverter.ast import Paragraph
        (para,) = _doc("text\n    still text\n").children
        self.assertIsInstance(para, Paragraph)

    def test_inside_a_list_it_is_the_item(self):
        from textconverter.ast import CodeBlock, ListBlock, walk
        doc = _doc("- a\n\n    b\n")
        self.assertIsInstance(doc.children[0], ListBlock)
        self.assertFalse(any(isinstance(n, CodeBlock) for n in walk(doc)))

    def test_machine_sources_can_turn_it_off(self):
        from textconverter.ast import Paragraph
        from textconverter.parsers.markdown_parser import parse_markdown
        (para,) = parse_markdown("    a line of a PDF\n", indented_code=False).children
        self.assertIsInstance(para, Paragraph)

    def test_transcriptions_do_not_read_indented_code(self):
        from textconverter.ast import Paragraph
        from textconverter.parsers.transcription_parser import parse_transcription
        doc = parse_transcription("    a transcribed line\n")
        self.assertIsInstance(doc.children[0], Paragraph)


class TestCommonMarkDetails(BaseConverterTest):

    def test_html_comments_are_dropped(self):
        self.assertEqual(_md("a\n\n<!-- hidden -->\n\nb\n"), "a\n\nb\n")
        self.assertEqual(_md("a <!-- hidden --> b\n"), "a b\n")
        self.assertEqual(_md("<!-- one\nline\n\ntwo -->\n\nb\n"), "b\n")

    def test_a_comment_in_code_stays(self):
        self.assertIn("<!-- x -->", _md("`<!-- x -->`\n"))
        self.assertIn("<!-- x -->", _md("```\n<!-- x -->\n```\n"))

    def test_a_shortcut_reference_is_a_link(self):
        from textconverter.ast import Link
        (link,) = _doc("[foo]\n\n[foo]: http://foo.com \"T\"\n").children[0].children
        self.assertIsInstance(link, Link)
        self.assertEqual((link.url, link.title), ("http://foo.com", "T"))

    def test_an_undefined_shortcut_stays_text(self):
        self.assertEqual(_md("see [foo] and matrix[i]\n"), "see \\[foo\\] and matrix\\[i\\]\n")

    def test_entities_are_decoded(self):
        self.assertIn("AT&amp;T ©", _md("AT&amp;T &copy;\n", to="html"))
        self.assertEqual(_doc("&#169; &#xA9;").children[0].children[0].content, "© ©")

    def test_entities_stay_literal_in_code(self):
        self.assertIn("`&amp;`", _md("`&amp;`\n"))

    def test_an_unknown_entity_stays_text(self):
        self.assertEqual(_doc("&nosuch; a & b").children[0].children[0].content, "&nosuch; a & b")

    def test_a_literal_entity_round_trips(self):
        from textconverter.ast import Document, Paragraph, Text
        from textconverter.renderers.markdown_renderer import render_markdown
        text = render_markdown(Document(children=[Paragraph(children=[Text(content="write &amp; here")])]))
        self.assertEqual(_doc(text).children[0].children[0].content, "write &amp; here")

    def test_closing_hashes_of_a_heading(self):
        for source, title in (("# Title #", "Title"), ("## Title ##  ", "Title"), ("# C#", "C#"), ("# a \\#", "a #"),
                              ("# Title #x", "Title #x")):
            with self.subTest(source):
                self.assertEqual(_doc(source).children[0].children[0].content, title)

    def test_hard_breaks_in_a_list_item(self):
        from textconverter.ast import LineBreak, Text, walk
        for source in ("- a  \n  b\n", "- a\\\n  b\n"):
            with self.subTest(source):
                nodes = list(walk(_doc(source)))
                has_break = any(isinstance(n, LineBreak) or (isinstance(n, Text) and "\n" in n.content) for n in nodes)
                self.assertTrue(has_break)
                self.assertFalse(any(isinstance(n, Text) and "\\" in n.content for n in nodes))
        self.assertEqual(_md(_md("- a  \n  b\n")), _md("- a  \n  b\n"))

    def test_footnote_indentation_does_not_grow(self):
        source = "Text[^1]\n\n[^1]: First  \n    second\n"
        once = _md(source)
        self.assertEqual(_md(once), once)
        self.assertEqual(_md(_md(once)), once)

    def test_no_private_character_in_a_title(self):
        self.assertIn('title="ti&quot;tle"', _md('[t](http://a.com "ti\\"tle")\n', to="html"))
        self.assertNotRegex(_md('![t](a.png "ti\\"tle")\n'), "[-]")


class TestHtmlInMarkdown(BaseConverterTest):
    """HTML in a Markdown file goes through the HTML parser: real nodes, or the text inside."""

    def test_inline_tags_keep_their_text(self):
        self.assertEqual(_md("a <span class='x'>b</span> <u>c</u> <foo>d</foo> e\n"), "a b c d e\n")

    def test_an_image_tag(self):
        from textconverter.ast import Image
        (image,) = _doc('<img src="a.png" alt="x">\n').children[0].children
        self.assertEqual(image, Image(src="a.png", alt="x"))

    def test_an_inline_image_tag(self):
        from textconverter.ast import Image
        children = _doc('see <img src="a.png"> here').children[0].children
        self.assertTrue(any(isinstance(n, Image) for n in children))

    def test_a_table_block(self):
        from textconverter.ast import Table
        (table,) = _doc("<table><tr><th>A</th></tr><tr><td>1</td></tr></table>\n").children
        self.assertIsInstance(table, Table)

    def test_a_block_spanning_lines(self):
        self.assertEqual(_md("<div align='center'>\n\ninside\n\n</div>\n\nafter\n"), "inside\n\nafter\n")

    def test_details(self):
        md = _md("<details><summary>More</summary>Body</details>\n")
        self.assertIn("More", md)
        self.assertIn("Body", md)
        self.assertNotIn("<", md)

    def test_what_is_not_a_tag_stays_text(self):
        from textconverter.ast import Text
        for source in ("a < b and c > d", "a <b", "x<y>", "1 <2> 3", "<3"):
            with self.subTest(source):
                self.assertEqual("".join(n.content for n in _doc(source).children[0].children if isinstance(n, Text))
                                 .replace("<y>", "").replace("<2>", ""), source.replace("<y>", "").replace("<2>", ""))

    def test_an_escaped_tag_stays_text(self):
        from textconverter.ast import Document, Paragraph, Text
        from textconverter.renderers.markdown_renderer import render_markdown
        text = render_markdown(Document(children=[Paragraph(children=[Text(content="the <span> tag")])]))
        self.assertEqual(_doc(text).children[0].children[0].content, "the <span> tag")

    def test_code_keeps_its_tags(self):
        self.assertIn("`<span>x</span>`", _md("`<span>x</span>`\n"))
        self.assertIn("<span>x</span>", _md("```html\n<span>x</span>\n```\n"))


class TestAdjacentLists(BaseConverterTest):

    def _starts(self, source: str) -> list[tuple[int, int]]:
        from textconverter.ast import ListBlock
        return [(n.start, len(n.items)) for n in _doc(source).children if isinstance(n, ListBlock)]

    def test_a_number_that_does_not_follow_starts_a_list(self):
        self.assertEqual(self._starts("1. a\n2. b\n\n1. c\n"), [(1, 2), (1, 1)])
        self.assertEqual(self._starts("1. a\n\n3. b\n"), [(1, 1), (3, 1)])

    def test_a_number_that_follows_continues(self):
        self.assertEqual(self._starts("1. a\n\n2. b\n\n3. c\n"), [(1, 3)])

    def test_two_lists_round_trip(self):
        from textconverter.ast import Document, ListBlock, ListItem, Paragraph, Text
        from textconverter.renderers.markdown_renderer import render_markdown
        item = lambda t: ListItem(children=[Paragraph(children=[Text(content=t)])])
        doc = Document(children=[ListBlock(ordered=True, items=[item("a"), item("b")]),
                                 ListBlock(ordered=True, items=[item("c")], start=1)])
        self.assertEqual(self._starts(render_markdown(doc)), [(1, 2), (1, 1)])


class TestCodeDetection(BaseConverterTest):

    def test_detected_code_is_not_altered(self):
        """Emphasis removal used to turn __init__ into init and a * b * c into a  b  c."""
        code = "def __init__(self, my_var):\n    self.my_var = a * b * c\n    return self.my_var"
        md = _md("Some intro text here.\n\n" + code, code_parsing=True)
        self.assertIn(code, md)

    def test_prose_is_not_fenced(self):
        """Labels, quotes, references, links and emphasis used to be fenced as code."""
        prose = [
            "List:",
            "Reference in `requirements.txt`:",
            "> - [![T](Foto.jpg)](https://e.org/a_b) and a [hobbit-hole][1].\n\n[1]: https://x.org",
            "Formatting **bold** *italic **both*** ~~struck~~, [link](https://www.google.it/?&hl=it)",
            "[4] E. Akartuna, “Ai-based detection,” _Computational_ _Economics_, vol. 59, pp. 987–1005.",
            "Keith T. Smith, [1] _[★]_ A. N. Other, [2] Third Author [2] _[,]_ [3]",
            "_★_ E-mail: publications@ras.ac.uk (KTS)",
            "van Dijk T., 1902, QJRAS, 2, 202\nFournier P., 1901, ApJ, 1, 101",
            "MNRAS **000**, 1–2 (2026)",
            "``Use `code` in your Markdown file.``",
        ]
        for text in prose:
            with self.subTest(text=text):
                self.assertNotIn("```", _md("Intro text.\n\n" + text, code_parsing=True))

    def test_unfenced_code_is_still_fenced(self):
        md = textconverter.convert(str(INPUT_DIR / "CodeTest.md"), "markdown",
                                   textconverter.ConvertOptions(code_parsing=True))
        self.assertIn('```python\ndef fibonacci(n):\n    """Calcola', md.split("# Unfenced")[1])
