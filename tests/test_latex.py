"""LaTeX parsing and rendering, HTML templates and math.

Usage: python -m unittest discover -s tests -p "test_latex.py"
"""
from __future__ import annotations

import textconverter
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR, read


class TestLatexParser(BaseConverterTest):

    def test_simple_latex_to_markdown(self):
        """SampleLatex.tex → MD: title, abstract blockquote, quotes, code preserved."""
        content = self.convert_fixture("SampleLatex.tex", "SampleLatex.md")
        # Title, author and date from the preamble, as front matter
        self.assertTrue(content.startswith('---\ntitle: "Il Teorema di Pitagora"\nauthor: "Mario Rossi"\n'), content)
        # Abstract rendered as blockquote
        self.assertIn("> [!IMPORTANT]", content, "Missing abstract callout")
        self.assertIn("> **Abstract**", content, "Missing abstract title")
        # Typographic quote normalization (``text'' → "text")
        self.assertIn("\u201cLa matematica \u00e8 la regina delle scienze\u201d", content,
                      "Missing normalized double quotes in abstract")
        self.assertIn("\u201cOgni cosa \u00e8 numero\u201d", content,
                      "Missing normalized double quotes in body")
        # Verbatim block: quotes inside code must NOT be normalized
        self.assertIn("print(f``c = {c}'')", content,
                      "Verbatim quotes were incorrectly normalized")
        # texttt inline: quotes must NOT be normalized either
        self.assertIn("math.hypot(a, b)", content, "Missing texttt content")

    def test_simple_latex_to_html(self):
        """SampleLatex.tex → HTML: title, abstract, blockquote present."""
        content = self.convert_fixture("SampleLatex.tex", "SampleLatex.html")
        self.assertIn("Il Teorema di Pitagora", content, "Missing title in HTML")
        self.assertIn("Abstract", content, "Missing Abstract heading in HTML")
        self.assertIn('<blockquote class="alert-important">', content, "Missing abstract blockquote element in HTML")

    def test_latex_to_html_with_light_template(self):
        """SampleLatex.tex → HTML with pretty (light) template: verifies CSS and MathJax script are present."""
        content = self.convert_fixture("SampleLatex.tex", "SampleLatex_pretty.html", template="pretty")
        self.assertIn("MathJax-script", content)
        self.assertIn(".math.inline", content)
        self.assertIn("Il Teorema di Pitagora", content)
        self.assertIn("font-family: -apple-system", content)

    def test_latex_to_html_with_dark_template(self):
        """SampleLatex.tex → HTML with dark-theme template: verifies dark CSS background and MathJax script."""
        content = self.convert_fixture("SampleLatex.tex", "SampleLatex_dark.html", template="dark-theme")
        self.assertIn("MathJax-script", content)
        self.assertIn('background-color: #0d1117;', content)
        self.assertIn('color: #c9d1d9;', content)

    def test_journal_latex_to_markdown(self):
        """Journal TEX.tex → MD: abstract (section-style), introduction section present."""
        content = self.convert_fixture("Journal TEX.tex", "Journal_TEX.md")
        self.assertGreater(len(content.strip()), 100, "Output is too short for a journal")
        self.assertIn("Introduction", content, "Missing Introduction section")
        self.assertIn("Methodology", content, "Missing Methodology section")

    def test_weird_journal_latex_to_markdown(self):
        """Weird Journal TEX.tex → MD: begin{abstract} environment, table, section present."""
        content = self.convert_fixture("Weird Journal TEX.tex", "Weird_Journal_TEX.md")
        self.assertGreater(len(content.strip()), 100, "Output is too short for a journal")
        # Abstract from \begin{abstract}
        self.assertIn("Abstract", content, "Missing Abstract section")
        # Body section
        self.assertIn("Introduction", content, "Missing Introduction section")
        # Table from \begin{tabular}
        self.assertIn("|", content, "Missing table (tabular) content")

    def test_simple_latex_to_latex(self):
        """SampleLatex.tex → LaTeX: structural elements roundtrip to latex code."""
        content = self.convert_fixture("SampleLatex.tex", "SampleLatex_out.tex")
        self.assertIn("\\documentclass{article}", content)
        self.assertIn("\\begin{document}", content)
        self.assertIn("\\title{Il Teorema di Pitagora}", content)
        self.assertIn("\\maketitle", content)
        self.assertIn("\\begin{verbatim}", content)
        self.assertIn("\\end{document}", content)

    def test_weird_journal_latex_to_latex(self):
        """Weird Journal TEX.tex → LaTeX: abstract, sections, and table roundtrip to latex code."""
        content = self.convert_fixture("Weird Journal TEX.tex", "Weird_Journal_TEX_out.tex")
        self.assertIn("\\documentclass{article}", content)
        self.assertIn("\\begin{document}", content)
        self.assertIn("Introduction", content)
        self.assertIn("\\begin{tabular}", content)
        self.assertIn("\\end{document}", content)

    def test_latex_safeguards(self):
        """Verify that latex macros like \\cite, \\ref, \\label, and \\footnote are preserved."""
        tex_content = "This is a cite \\cite{somekey}, a label \\label{lbl}, a ref \\ref{lbl}, and a footnote \\footnote{This is a footnote}."
        result = textconverter.convert_text(tex_content, "latex", "markdown")
        self.assertIn("\\cite{somekey}", result)
        self.assertIn("\\label{lbl}", result)
        self.assertIn("\\ref{lbl}", result)
        # Markdown has its own footnote syntax (GFM)
        self.assertIn("a footnote [^1].", result)
        self.assertIn("[^1]: This is a footnote", result)

    def test_latex_to_md_to_latex_safeguards(self):
        """Verify that latex macros are preserved through a latex -> md -> latex roundtrip and inner formats are parsed."""
        tex_content = "Some text with \\footnote{inner \\textbf{bold} text} and \\cite{abc}."
        md_result = textconverter.convert_text(tex_content, "latex", "markdown")
        self.assertIn("[^1]: inner **bold** text", md_result)
        self.assertIn("\\cite{abc}", md_result)
        
        # Now convert back to latex
        tex_result = textconverter.convert_text(md_result, "markdown", "latex")
        # Should be back to latex with proper bold
        self.assertIn("\\footnote{inner \\textbf{bold} text}", tex_result)
        self.assertIn("\\cite{abc}", tex_result)

    def test_abstract_roundtrip(self):
        """Verify that the abstract environment is preserved through latex -> md -> html -> latex."""
        tex_content = "\\begin{abstract}\nThis is the abstract text.\n\\end{abstract}"
        md_result = textconverter.convert_text(tex_content, "latex", "markdown")
        self.assertIn("> [!IMPORTANT]", md_result)
        self.assertIn("> **Abstract**", md_result)
        self.assertIn("> This is the abstract text.", md_result)
        
        html_result = textconverter.convert_text(md_result, "markdown", "html")
        self.assertIn('<blockquote class="alert-important">', html_result)
        self.assertIn('<div class="alert-title">Abstract</div>', html_result)
        self.assertIn('This is the abstract text.', html_result)
        
        final_tex = textconverter.convert_text(html_result, "html", "latex")
        self.assertIn("\\begin{abstract}", final_tex)
        self.assertIn("This is the abstract text.", final_tex)
        self.assertIn("\\end{abstract}", final_tex)

    def test_preamble_detects_image_inside_link(self):
        """An image reachable only through a link still loads graphicx."""
        md = "[![alt](pic.png)](http://x.test)"
        tex = textconverter.convert_text(md, "markdown", "latex", textconverter.ConvertOptions(image_handling="link"))
        self.assertIn("\\usepackage{graphicx}", tex)
        self.assertIn("\\usepackage{hyperref}", tex)

    def test_latex_math_to_html(self):
        """Verify that LaTeX math environments are correctly converted to HTML math elements."""
        tex_content = "Inline $x=1$ and block \\begin{equation} y=2 \\end{equation} and display \\[ z=3 \\]."
        result = textconverter.convert_text(tex_content, "latex", "html")
        self.assertIn('<span class="math inline">\\(x=1\\)</span>', result)
        self.assertIn('<div class="math block">$$\ny=2\n$$</div>', result)
        self.assertIn('<div class="math block">$$\nz=3\n$$</div>', result)


def _blocks(body: str):
    from textconverter.parsers.latex_parser import parse_latex
    return parse_latex("\\begin{document}\n" + body + "\n\\end{document}").children


def _md(body: str) -> str:
    return textconverter.convert_text("\\begin{document}\n" + body + "\n\\end{document}", "latex", "markdown")


class TestLatexFixes(BaseConverterTest):
    """LaTeX constructs that used to be lost, garbled or printed as text."""

    def test_starred_and_alignment_environments(self):
        from textconverter.ast import Equation
        self.assertEqual(_blocks(r"\begin{equation*} a=\frac{b}{c} \end{equation*}"),
                         [Equation(code=r"a=\frac{b}{c}")])
        self.assertEqual(_blocks(r"\begin{align*} a &= b \\ c &= d \end{align*}"),
                         [Equation(code=r"a &= b \\ c &= d", env="align*")])
        self.assertEqual(_blocks(r"\begin{gather} x \end{gather}")[0].env, "gather")

    def test_alignment_round_trips_through_latex(self):
        tex = textconverter.convert_text("\\begin{document}\n\\begin{align}a&=b\\\\c&=d\\end{align}\n\\end{document}",
                                         "latex", "latex")
        self.assertIn("\\begin{align}\na&=b\\\\c&=d\n\\end{align}", tex)

    def test_itemsep_and_nested_lists(self):
        md = _md("\\begin{itemize}\\itemsep0pt\n\\item a\n\\begin{itemize}\n\\item b\n\\end{itemize}\n\\item c\n\\end{itemize}")
        self.assertEqual(md.strip(), "- a\n    - b\n- c")

    def test_escaped_ampersand_in_a_table(self):
        md = _md("\\begin{tabular}{ll}\nA \\& B & C \\\\\n1 & 2 \\\\\n\\end{tabular}")
        self.assertEqual(md.splitlines()[0], "| A & B | C |")

    def test_percent_inside_verbatim_is_code(self):
        md = _md('\\begin{verbatim}\nprintf("%d", x); % not a comment\n\\end{verbatim}')
        self.assertIn('printf("%d", x); % not a comment', md)

    def test_lstlisting_language(self):
        from textconverter.ast import CodeBlock
        (block,) = _blocks("\\begin{lstlisting}[language=Python]\nx = 1\n\\end{lstlisting}")
        self.assertEqual(block, CodeBlock(code="x = 1", language="python"))

    def test_emphasis_strikethrough_accents_and_spaces(self):
        from textconverter.ast import Text
        (para,) = _blocks("\\emph{x} \\sout{y} citt\\`a perch\\'e \\c{c}a Stra\\ss e Fig.~1 caff\\`{e}")
        self.assertIn(Text(content="x", italic=True), para.children)
        self.assertIn(Text(content="y", strikethrough=True), para.children)
        text = "".join(n.content for n in para.children if isinstance(n, Text))
        self.assertIn("città perché ça Straße Fig.\u00a01 caffè", text)

    def test_source_line_breaks_are_spaces(self):
        """Wrapped source lines used to become hard breaks in Markdown and HTML."""
        self.assertEqual(_md("one line\n    wrapped here\\\\\nnext").strip(), "one line wrapped here  \nnext")

    def test_section_after_sectionmark(self):
        from textconverter.ast import Heading
        blocks = _blocks("\\sectionmark{Short}\n\\section{Real title}\nBody.")
        self.assertIsInstance(blocks[0], Heading)

    def test_citation_with_two_optional_arguments(self):
        from textconverter.ast import Citation
        (para,) = _blocks("as shown \\citep[e.g.][p. 3]{vanDijk1902}.")
        self.assertIn(Citation(keys=["vanDijk1902"], style="citep", options=["e.g.", "p. 3"]), para.children)
        for to in ("latex", "markdown", "html"):
            with self.subTest(to=to):
                out = textconverter.convert_text("\\citep[e.g.][p. 3]{vanDijk1902}", "latex", to)
                self.assertIn("\\citep[e.g.][p. 3]{vanDijk1902}", out)

    def test_literal_arguments_are_unescaped(self):
        from textconverter.ast import CodeInline, Link
        (para,) = _blocks("\\texttt{mnras\\_sample.tex}. \\href{https://x.org/a\\_b\\%20c}{link}")
        self.assertIn(CodeInline(code="mnras_sample.tex"), para.children)
        self.assertEqual([n.url for n in para.children if isinstance(n, Link)], ["https://x.org/a_b%20c"])

    def test_layout_environments_keep_their_content(self):
        """\\begin{center} used to come out as the text 'center'."""
        md = _md("\\begin{center}\nCentered text.\n\\end{center}")
        self.assertEqual(md.strip(), "Centered text.")

    def test_horizontal_rule_round_trips(self):
        from textconverter.ast import HorizontalRule
        tex = textconverter.convert_text("a\n\n---\n\nb", "markdown", "latex")
        self.assertIn(HorizontalRule(), textconverter.parsers.latex_parser.parse_latex(tex).children)

    def test_hard_break_in_text_is_a_latex_line_break(self):
        tex = textconverter.convert_text("one  \ntwo", "markdown", "latex")
        self.assertIn("one\\\\\ntwo", tex)


def _convert(text: str, frm: str, to: str) -> str:
    return textconverter.convert_text(text, frm, to, textconverter.ConvertOptions(image_handling="link"))


class TestLatexStructure(BaseConverterTest):
    """Title block, floats, numbering, groups and the other constructs LaTeX output writes back."""

    SAMPLE = "\n".join([
        "\\title{The \\textbf{Title}}", "\\author{A. Author\\textsuperscript{1}\\\\Dept}", "\\date{2026}",
        "\\begin{document}", "\\maketitle",
        "\\section*{Preface}", "Text\\footnote{A \\textbf{note}.} with \\cite{a,b}, \\citep[e.g.][p.~3]{d},",
        "\\ref{fig:x} and H\\textsubscript{2}O \\textless{}x\\textgreater{} a\\textbar{}b.",
        "\\begin{figure}[h]", "\\centering", "\\includegraphics{pic.png}", "\\caption{A \\textit{figure}}",
        "\\label{fig:x}", "\\end{figure}",
        "\\begin{table}[h]", "\\centering", "\\caption{A table}", "\\label{tab:x}",
        "\\begin{tabular}{|c|c|}", "\\hline", "a & b \\\\", "\\hline", "1 & 2 \\\\", "\\hline", "\\end{tabular}",
        "\\end{table}",
        "\\begin{enumerate}", "    \\setcounter{enumi}{2}", "    \\item three", "    \\item four", "\\end{enumerate}",
        "\\begin{itemize}", "    \\item[$\\square$] todo", "    \\item[$\\boxtimes$] done", "\\end{itemize}",
        "\\subparagraph{Deep}", "\\textbf{Keywords:} x", "\\appendix", "\\section{Extra}", "\\end{document}",
    ])

    def test_parsed_structure(self):
        from textconverter.ast import Appendix, Heading, Image, ListBlock, Table, Text
        from textconverter.parsers.latex_parser import parse_latex
        doc = parse_latex(self.SAMPLE)
        self.assertEqual(doc.title, [Text(content="The "), Text(content="Title", bold=True)])
        self.assertEqual(doc.date, [Text(content="2026")])
        self.assertIn(Text(content="1", script="sup"), doc.author)
        heading = next(n for n in doc.children if isinstance(n, Heading))
        self.assertEqual((heading.numbered, heading.children), (False, [Text(content="Preface")]))
        image = next(n for p in doc.children for n in getattr(p, "children", []) if isinstance(n, Image))
        self.assertEqual((image.src, image.label), ("pic.png", "fig:x"))
        self.assertEqual(image.caption, [Text(content="A "), Text(content="figure", italic=True)])
        table = next(n for n in doc.children if isinstance(n, Table))
        self.assertEqual((table.label, table.caption), ("tab:x", [Text(content="A table")]))
        enum, tasks = [n for n in doc.children if isinstance(n, ListBlock)]
        self.assertEqual((enum.start, [i.checked for i in tasks.items]), (3, [False, True]))
        self.assertIn(Heading(level=5, children=[Text(content="Deep")]), doc.children)
        self.assertIn(Appendix(), doc.children)

    def test_round_trips_are_identical(self):
        tex = _convert(self.SAMPLE, "latex", "latex")
        self.assertIn("\\title{The \\textbf{Title}}\n\\author{A. Author\\textsuperscript{1}\\\\\nDept}\n"
                      "\\date{2026}\n\\begin{document}\n\n\\maketitle", tex)
        for snippet in ("\\section*{Preface}", "\\citep[e.g.][p.~3]{d}", "\\textless{}x\\textgreater{} a\\textbar{}b",
                        "\\caption{A \\textit{figure}}\n\\label{fig:x}", "\\caption{A table}\n\\label{tab:x}",
                        "\\setcounter{enumi}{2}", "\\item[$\\square$] todo", "\\subparagraph{Deep}", "\\appendix"):
            self.assertIn(snippet, tex)
        self.assertEqual(_convert(tex, "latex", "latex"), tex)
        # Numbering and \appendix exist only in LaTeX; everything else survives the other formats
        expected = tex.replace("\\section*", "\\section").replace("\\appendix\n\n", "")
        for via in ("markdown", "html", "json"):
            with self.subTest(via=via):
                back = _convert(_convert(tex, "latex", via), via, "latex")
                self.assertEqual(back, tex if via == "json" else expected)

    def test_font_groups_and_declarations(self):
        from textconverter.ast import Text
        (para,) = _blocks("{\\bfseries bold {\\itshape both}} {\\em it} {\\small plain} \\{braces\\}")
        self.assertEqual(para.children, [Text(content="bold ", bold=True), Text(content="both", bold=True, italic=True),
                                         Text(content=" "), Text(content="it", italic=True),
                                         Text(content=" plain {braces}")])

    def test_escaped_braces_inside_an_argument(self):
        from textconverter.ast import Text
        (para,) = _blocks("\\textbf{a\\}b\\{c} d")
        self.assertEqual(para.children, [Text(content="a}b{c", bold=True), Text(content=" d")])

    def test_percent_in_a_url_is_not_a_comment(self):
        from textconverter.ast import Link
        (para,) = _blocks("\\url{http://a.org/x%20y} and \\href{http://b.org/?q=1\\%2}{b} % a comment")
        self.assertEqual([n.url for n in para.children if isinstance(n, Link)],
                         ["http://a.org/x%20y", "http://b.org/?q=1%2"])
        self.assertNotIn("comment", _md("\\url{http://a.org/x%20y} % a comment"))

    def test_display_math_splits_its_paragraph(self):
        from textconverter.ast import Equation, Paragraph
        blocks = _blocks("before \\[ x = 1 \\] after")
        self.assertEqual([type(b) for b in blocks], [Paragraph, Equation, Paragraph])

    def test_formatting_spaces_and_runs(self):
        from textconverter.ast import Document, LineBreak, Paragraph, Text
        from textconverter.renderers.latex_renderer import render_latex
        doc = Document(children=[Paragraph(children=[
            Text(content="Keywords: ", bold=True), Text(content="a "), Text(content="b", bold=True),
            Text(content=" c", bold=True, italic=True), Text(content="end "), LineBreak(), Text(content="[1] ref")])])
        body = render_latex(doc).split("\\begin{document}\n\n")[1]
        self.assertTrue(body.startswith("\\textbf{Keywords:} a \\textbf{b \\textit{c}}end\\\\\n{}[1] ref"), body)
