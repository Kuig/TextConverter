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
        self.assertIn('<div class="math block">\\begin{equation}\ny=2\n\\end{equation}</div>', result)
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
                         [Equation(code=r"a=\frac{b}{c}", env="equation*")])
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

    def _table(self, body: str) -> list[list[str]]:
        from textconverter.ast import Table
        from textconverter.renderers.csv_renderer import table_rows
        (table,) = [node for node in _blocks(body) if isinstance(node, Table)]
        return table_rows(table)

    def test_every_table_environment_is_a_table(self):
        for begin, end in (("\\begin{tabular}{ll}", "\\end{tabular}"),
                           ("\\begin{tabular*}{\\textwidth}{ll}", "\\end{tabular*}"),
                           ("\\begin{tabularx}{\\textwidth}{lX}", "\\end{tabularx}"),
                           ("\\begin{tabulary}{\\textwidth}{LL}", "\\end{tabulary}"),
                           ("\\begin{longtable}[c]{ll}", "\\end{longtable}"),
                           ("\\begin{xltabular}{\\textwidth}{lX}", "\\end{xltabular}")):
            with self.subTest(begin):
                self.assertEqual(self._table(f"{begin}\nA & B \\\\\n1 & 2 \\\\\n{end}"), [["A", "B"], ["1", "2"]])
                self.assertEqual(self._table(f"\\begin{{table}}\n{begin}\nA \\\\\n{end}\n\\end{{table}}"), [["A"]])

    def test_rules_and_colors_leave_no_trace_in_the_cells(self):
        rows = self._table("\\begin{tabular}{ll}\n\\toprule[1pt]\nA & B \\\\\n\\cmidrule(lr){1-2}\n"
                           "\\rowcolor{gray!20} 1 & \\cellcolor[HTML]{EEEEEE}2 \\\\\n\\addlinespace[2pt]\n"
                           "3 & 4 \\\\\n\\cline{1-2}\n\\specialrule{1pt}{2pt}{2pt}\n{\\bfseries 5} & 6 \\\\*\n"
                           "\\hhline{|=|=|}\n7 & 8 \\tabularnewline\n\\bottomrule\n\\end{tabular}")
        self.assertEqual(rows, [["A", "B"], ["1", "2"], ["3", "4"], ["5", "6"], ["7", "8"]])

    def test_a_rule_keeps_the_group_that_follows_it(self):
        self.assertEqual(self._table("\\begin{tabular}{l}\n\\hline {\\bfseries A} \\\\\n\\end{tabular}"), [["A"]])

    def test_multicolumn_and_multirow_keep_their_text(self):
        rows = self._table("\\begin{tabular}{lll}\n\\multicolumn{2}{c}{Span} & Z \\\\\n"
                           "\\multirow{2}{*}{R} & 1 & 2 \\\\\n & 3 & 4 \\\\\n"
                           "\\multirow[t]{2}{3cm}[1mm]{S} & 5 & 6 \\\\\n"
                           "\\multicolumn{3}{l}{\\multirow{2}{*}{T}} \\\\\n\\end{tabular}")
        self.assertEqual(rows, [["Span", "", "Z"], ["R", "1", "2"], ["", "3", "4"], ["S", "5", "6"], ["T", "", ""]])

    def test_a_group_or_a_nested_table_does_not_end_a_cell(self):
        rows = self._table("\\begin{tabular}{ll}\n\\multicolumn{1}{c}{a\\\\b} & c \\\\\n"
                           "\\begin{tabular}{c}d\\\\e\\end{tabular} & f \\\\\n\\end{tabular}")
        self.assertEqual(rows[0], ["a\nb", "c"])
        self.assertEqual((len(rows), rows[1][1]), (2, "f"))

    def test_every_table_of_a_float_is_kept_and_the_first_gets_the_caption(self):
        from textconverter.ast import Table
        from textconverter.renderers._common import plain_text
        tables = [node for node in _blocks(
            "\\begin{table}\\caption{Cap}\n\\begin{subtable}{.5\\textwidth}\\begin{tabular}{l}A \\\\\\end{tabular}"
            "\\end{subtable}\n\\resizebox{\\textwidth}{!}{\\begin{tabular}{l}B \\\\\\end{tabular}}\n\\end{table}")
            if isinstance(node, Table)]
        self.assertEqual([plain_text(t.headers[0].children) for t in tables], ["A", "B"])
        self.assertEqual((plain_text(tables[0].caption), tables[1].caption), ("Cap", []))

    def test_sideways_float_gets_its_caption(self):
        from textconverter.renderers._common import plain_text
        (table,) = _blocks("\\begin{sidewaystable}\\caption{Cap}\\begin{tabular}{l}A \\\\\\end{tabular}\\end{sidewaystable}")
        self.assertEqual(plain_text(table.caption), "Cap")

    def test_longtable_repeated_head_and_feet_are_not_rows(self):
        from textconverter.renderers._common import plain_text
        (table,) = _blocks(
            "\\begin{longtable}{ll}\n\\caption{Cap}\\label{t} \\\\\n\\hline A & B \\\\\n\\endfirsthead\n"
            "\\caption[]{Cap, continued} \\\\\nA & B \\\\\n\\endhead\nnext page \\\\\n\\endfoot\nend \\\\\n"
            "\\endlastfoot\n1 & 2 \\\\\n3 & 4 \\\\\n\\end{longtable}")
        self.assertEqual((plain_text(table.caption), table.label), ("Cap", "t"))
        self.assertEqual(self._table("\\begin{longtable}{ll}\nA & B \\\\\n\\endhead\nfoot \\\\\n\\endfoot\n"
                                     "1 & 2 \\\\\n\\end{longtable}"), [["A", "B"], ["1", "2"]])
        self.assertEqual(len(table.rows), 2)

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


def _wrap(body: str) -> str:
    return "\\begin{document}\n" + body + "\n\\end{document}\n"


def _tex(body: str) -> str:
    """A LaTeX body converted to LaTeX, without the preamble."""
    return _convert(_wrap(body), "latex", "latex").split("\\begin{document}\n\n")[1].rsplit("\\end{document}", 1)[0].strip()


def _rows(tabular: str) -> list[list[str]]:
    from textconverter.ast import Table
    from textconverter.renderers.csv_renderer import table_rows
    (table,) = [n for n in _blocks(tabular) if isinstance(n, Table)]
    return table_rows(table)


class TestTableLayoutCommands(BaseConverterTest):
    """A rule command takes its own optional arguments, never the cell text that follows it."""

    def test_a_cell_after_a_rule_keeps_its_parentheses_and_brackets(self):
        for name, rows, expected in (
            ("hline", "\\hline\n(a) first & b \\\\\n\\hline\n(c) second & d \\\\", [["(a) first", "b"], ["(c) second", "d"]]),
            ("hline bracket", "\\hline\n[1] ref & b \\\\\n\\hline\n[2] ref & d \\\\", [["[1] ref", "b"], ["[2] ref", "d"]]),
            ("booktabs", "\\toprule\n(mm) & (kg) \\\\\n\\midrule\n(1) & 2 \\\\\n\\bottomrule", [["(mm)", "(kg)"], ["(1)", "2"]]),
            ("same line", "\\hline (x) & y \\\\ \\hline", [["(x)", "y"]]),
            ("space", "a & b \\\\\n\\addlinespace\n(c) & d \\\\", [["a", "b"], ["(c)", "d"]]),
        ):
            with self.subTest(name):
                self.assertEqual(_rows(f"\\begin{{tabular}}{{ll}}\n{rows}\n\\end{{tabular}}"), expected)

    def test_a_rule_keeps_reading_its_own_arguments(self):
        for rule in ("\\cmidrule(lr){1-2}", "\\cmidrule[1pt](lr){1-2}", "\\toprule[1pt]", "\\midrule[0.5pt]",
                     "\\bottomrule[2pt]", "\\addlinespace[2pt]", "\\cline{1-2}", "\\specialrule{1pt}{2pt}{3pt}"):
            with self.subTest(rule):
                rows = _rows(f"\\begin{{tabular}}{{ll}}\na & b \\\\\n{rule}\n(c) & d \\\\\n\\end{{tabular}}")
                self.assertEqual(rows, [["a", "b"], ["(c)", "d"]])

    def test_a_brace_in_verb_does_not_join_the_rows(self):
        rows = _rows("\\begin{tabular}{ll}\n\\verb|{| & a \\\\\nb & c \\\\\n\\end{tabular}")
        self.assertEqual(rows, [["{", "a"], ["b", "c"]])

    def test_unbalanced_braces_do_not_join_the_rows(self):
        rows = _rows("\\begin{tabular}{ll}\nx{ & a \\\\\nb & c \\\\\n\\end{tabular}")
        self.assertEqual(len(rows), 2)


class TestMathEnvironments(BaseConverterTest):
    """Math keeps its environments and its numbering."""

    def test_environments_inside_math_delimiters_stay_formulas(self):
        from textconverter.ast import Equation
        for source, inline in (("\\[ \\begin{pmatrix} a \\\\ b \\end{pmatrix} \\]", False),
                               ("$$\\begin{bmatrix} a \\\\ b \\end{bmatrix}$$", False),
                               ("$\\begin{cases} a \\\\ b \\end{cases}$", True),
                               ("\\( \\begin{matrix} a \\end{matrix} \\)", True)):
            with self.subTest(source):
                (block,) = _blocks(source)
                equation = block if isinstance(block, Equation) else block.children[0]
                self.assertIsInstance(equation, Equation)
                self.assertEqual(equation.inline, inline)
                self.assertIn("\\begin{", equation.code)

    def test_text_around_an_inline_environment_stays(self):
        self.assertEqual(_md("a $\\begin{cases} x \\end{cases}$ b").strip(), "a $\\begin{cases} x \\end{cases}$ b")

    def test_a_stray_dollar_does_not_hide_the_blocks_after_it(self):
        from textconverter.ast import ListBlock
        self.assertTrue(any(isinstance(n, ListBlock) for n in
                            _blocks("It costs \\$5 and $ more\n\n\\begin{itemize}\\item x\\end{itemize}")))

    def test_numbering_is_kept(self):
        for source, expected in (
            ("\\[ a \\]", "\\[\na\n\\]"),
            ("\\begin{equation} a \\end{equation}", "\\begin{equation}\na\n\\end{equation}"),
            ("\\begin{equation*} a \\end{equation*}", "\\begin{equation*}\na\n\\end{equation*}"),
            ("\\begin{displaymath} a \\end{displaymath}", "\\begin{displaymath}\na\n\\end{displaymath}"),
        ):
            with self.subTest(source):
                self.assertEqual(_tex(source), expected)
                for via in ("markdown", "html", "json"):
                    back = _convert(_convert(_wrap(source), "latex", via), via, "latex")
                    self.assertIn(expected, back, via)

    def test_a_labelled_plain_formula_stays_numbered(self):
        self.assertIn("\\begin{equation}", _convert("$$\n\\label{e} a\n$$\n", "markdown", "latex"))
        self.assertIn("\\[\na\n\\]", _convert("$$\na\n$$\n", "markdown", "latex"))

    def test_aligned_is_not_wrapped_again(self):
        source = "$$\n\\begin{aligned}\na &= b\n\\end{aligned}\n$$\n"
        once = _convert(source, "markdown", "latex")
        self.assertEqual(once.count("\\begin{aligned}"), 1, once)
        twice = _convert(_convert(once, "latex", "markdown"), "markdown", "latex")
        self.assertEqual(twice, once)

    def test_an_environment_formula_is_not_wrapped(self):
        self.assertNotIn("aligned", _convert("$$\n\\begin{cases} a \\\\ b \\end{cases}\n$$\n", "markdown", "latex"))

    def test_loose_alignment_still_gets_aligned(self):
        self.assertIn("\\begin{aligned}\na &= b \\\\ c &= d\n\\end{aligned}",
                      _convert("$$\na &= b \\\\ c &= d\n$$\n", "markdown", "latex"))

    def test_line_breaks_of_a_formula_survive_cells_titles_and_captions(self):
        matrix = "$\\begin{matrix} 1 & 2 \\\\ 3 & 4 \\end{matrix}$"
        for source in (f"\\begin{{tabular}}{{l}}\n{matrix} \\\\\n\\end{{tabular}}", f"\\section{{{matrix}}}",
                       f"\\begin{{table}}\n\\caption{{{matrix}}}\n\\begin{{tabular}}{{l}}\na\n\\end{{tabular}}\n\\end{{table}}"):
            with self.subTest(source):
                self.assertIn("1 & 2 \\\\ 3 & 4", _tex(source))

    def test_a_math_environment_written_as_text(self):
        from textconverter.ast import Equation
        (para,) = _blocks("a \\begin{math}x^2\\end{math} b")
        self.assertIn(Equation(code="x^2", inline=True), para.children)


class TestReferenceFamilies(BaseConverterTest):
    """Every citation and cross-reference macro comes back as written, whatever it went through."""

    MACROS = ("\\eqref{e}", "\\autoref{a}", "\\cref{a,b}", "\\Cref{a}", "\\nameref{a}", "\\vref{a}", "\\pageref{a}",
              "\\hyperref[target]{the text}", "\\parencite{k}", "\\autocite{k}", "\\textcite{k}", "\\footcite{k}",
              "\\citeauthor{k}", "\\citeyear{k}", "\\citetitle{k}", "\\nocite{k}", "\\Cite{k}", "\\Citet{k}",
              "\\Citep{k}", "\\citealt{k}", "\\citealp{k}", "\\cites{a}{b}", "\\citet*{k}", "\\citep*[p.~3]{k}",
              "\\parencite[see][12]{k}")

    def test_macros_stay_in_latex(self):
        for macro in self.MACROS:
            with self.subTest(macro):
                self.assertEqual(_tex(f"See {macro} here."), f"See {macro} here.")

    def test_macros_survive_every_text_format(self):
        for macro in self.MACROS:
            for via in ("markdown", "html", "json"):
                with self.subTest(macro, via=via):
                    back = _convert(_convert(_wrap(f"See {macro} here."), "latex", via), via, "latex")
                    self.assertIn(f"See {macro} here.", back)

    def test_macros_written_in_markdown_and_html_are_read(self):
        for macro in self.MACROS:
            with self.subTest(macro):
                self.assertIn(macro, _convert(f"See {macro} here.\n", "markdown", "latex"))

    def test_they_are_nodes_not_text(self):
        from textconverter.ast import Citation, Reference
        (para,) = _blocks("\\eqref{e} and \\citet*{k}")
        self.assertIn(Reference(label="e", style="eqref"), para.children)
        self.assertIn(Citation(keys=["k"], style="citet*"), para.children)

    def test_the_preamble_loads_their_packages(self):
        for macro, package in (("\\cref{a}", "cleveref"), ("\\vref{a}", "varioref"), ("\\autoref{a}", "hyperref"),
                               ("\\eqref{a}", "amsmath"), ("\\parencite{a}", "biblatex"), ("\\citealt{a}", "natbib"),
                               ("\\citet*{a}", "natbib")):
            with self.subTest(macro):
                self.assertIn(f"\\usepackage{{{package}}}", _convert(_wrap(macro), "latex", "latex"))

    def test_cleveref_comes_after_hyperref(self):
        tex = _convert(_wrap("\\href{http://a.b}{x} \\cref{a}"), "latex", "latex")
        self.assertLess(tex.index("{hyperref}"), tex.index("{cleveref}"))

    def test_biblatex_wins_over_natbib(self):
        tex = _convert(_wrap("\\parencite{a} \\citet{b}"), "latex", "latex")
        self.assertIn("\\usepackage{biblatex}", tex)
        self.assertNotIn("natbib", tex)


class TestUnknownMacros(BaseConverterTest):
    """A macro's content survives whichever argument holds it."""

    def test_known_commands_give_their_content(self):
        for source, expected in (
            ("\\textcolor{red}{word}", "word"), ("\\textcolor[rgb]{1,0,0}{word}", "word"),
            ("\\colorbox{yellow}{word}", "word"), ("\\foreignlanguage{italian}{word}", "word"),
            ("\\parbox{3cm}{word}", "word"), ("\\raisebox{1pt}{word}", "word"), ("\\resizebox{1cm}{!}{word}", "word"),
            ("\\scalebox{2}{word}", "word"), ("\\rotatebox{90}{word}", "word"), ("\\SI{5}{km}", "5 km"),
        ):
            with self.subTest(source):
                self.assertEqual(_md(source).strip(), expected)

    def test_formatting_inside_them_is_kept(self):
        self.assertEqual(_md("\\textcolor{red}{\\textbf{word}}").strip(), "**word**")

    def test_an_unknown_macro_keeps_all_its_arguments_and_is_reported(self):
        from unittest.mock import patch
        with patch("textconverter.parsers.latex_parser.log_warning") as warn:
            self.assertEqual(_md("\\foo{a}{b} and \\foo{c} and \\bar{d}").strip(), "a b and c and d")
        warn.assert_called_once()
        self.assertIn("\\bar", warn.call_args.args[0])
        self.assertIn("\\foo", warn.call_args.args[0])

    def test_common_wrappers_are_not_reported(self):
        from unittest.mock import patch
        with patch("textconverter.parsers.latex_parser.log_warning") as warn:
            self.assertEqual(_md("\\textsc{a} \\underline{b} \\mbox{c}").strip(), "a b c")
        warn.assert_not_called()


class TestBibliography(BaseConverterTest):
    """The bibliography comes back with the citations that need it."""

    COMMANDS = "\\bibliographystyle{plain}\n\\bibliography{refs}"
    ITEMS = ("\\begin{thebibliography}{9}\n\\bibitem{a} A. Author, \\textit{Title}, 2020.\n\n"
             "\\bibitem{b} B. Author.\n\\end{thebibliography}")

    def test_commands_survive_every_text_format(self):
        source = _wrap(f"Text \\cite{{a}}.\n\n{self.COMMANDS}")
        self.assertIn(self.COMMANDS, _convert(source, "latex", "latex"))
        for via in ("markdown", "html", "json"):
            with self.subTest(via=via):
                self.assertIn(self.COMMANDS, _convert(_convert(source, "latex", via), via, "latex"))

    def test_biblatex_commands_survive(self):
        source = "\\addbibresource{refs.bib}\n" + _wrap("Text \\parencite{a}.\n\n\\printbibliography")
        back = _convert(_convert(source, "latex", "markdown"), "markdown", "latex")
        self.assertIn("\\addbibresource{refs.bib}", back)
        self.assertIn("\\printbibliography", back)

    def test_they_show_in_markdown_as_macros(self):
        self.assertIn("\\bibliography{refs}", _md(self.COMMANDS))

    def test_entries_stay_apart_and_keys_stay_out_of_the_text(self):
        from textconverter.ast import Bibliography
        (bib,) = _blocks(self.ITEMS)
        self.assertIsInstance(bib, Bibliography)
        self.assertEqual([e.key for e in bib.entries], ["a", "b"])
        self.assertEqual(bib.entries[1].children[0].content, "B. Author.")

    def test_entries_come_back_identical(self):
        tex = _convert(_wrap(self.ITEMS), "latex", "latex")
        self.assertIn(self.ITEMS.replace("\n\n", "\n"), tex)
        for via in ("markdown", "html", "json"):
            with self.subTest(via=via):
                self.assertEqual(_convert(_convert(tex, "latex", via), via, "latex"), tex)

    def test_markdown_shows_one_entry_per_paragraph(self):
        self.assertIn("\\bibitem{a} A. Author, _Title_, 2020.\n\n\\bibitem{b} B. Author.", _md(self.ITEMS))


class TestSectionLevels(BaseConverterTest):
    """``\\part`` and ``\\chapter`` are headings, relative to the highest command used."""

    def _levels(self, body: str) -> list[int]:
        from textconverter.ast import Heading
        return [n.level for n in _blocks(body) if isinstance(n, Heading)]

    def test_levels_start_at_the_highest_command(self):
        self.assertEqual(self._levels("\\section{a}\\subsection{b}"), [1, 2])
        self.assertEqual(self._levels("\\chapter{a}\\section{b}\\subsection{c}"), [1, 2, 3])
        self.assertEqual(self._levels("\\part{a}\\chapter{b}\\section{c}"), [1, 2, 3])
        self.assertEqual(self._levels("\\part{a}\\section{b}"), [1, 3])

    def test_the_title_is_not_in_the_text(self):
        self.assertEqual(_md("\\chapter{One}\nText.").strip(), "# One\n\nText.")

    def test_the_starred_form_is_read(self):
        self.assertEqual(_tex("\\chapter*{One}\n\n\\section{Two}"), "\\chapter*{One}\n\n\\section{Two}")

    def test_latex_output_writes_them_back(self):
        source = _wrap("\\part{P}\n\n\\chapter{C}\n\n\\section{S}")
        tex = _convert(source, "latex", "latex")
        self.assertIn("\\documentclass{report}", tex)
        self.assertIn("\\part{P}\n\n\\chapter{C}\n\n\\section{S}", tex)
        self.assertEqual(_convert(_convert(tex, "latex", "json"), "json", "latex"), tex)

    def test_a_document_of_sections_stays_an_article(self):
        self.assertIn("\\documentclass{article}", _convert(_wrap("\\section{S}"), "latex", "latex"))

    def test_through_markdown_they_are_sections(self):
        source = _wrap("\\chapter{C}\n\n\\section{S}")
        self.assertIn("\\section{C}\n\n\\subsection{S}", _convert(_convert(source, "latex", "markdown"), "markdown", "latex"))


class TestLatexBlocksInOutput(BaseConverterTest):

    def test_paragraphs_of_a_quote_stay_apart(self):
        self.assertIn("A\n\nB", _tex("\\begin{quote}\nA\n\nB\n\\end{quote}"))
        self.assertEqual(_tex(_tex("\\begin{quote}\nA\n\nB\n\\end{quote}")), _tex("\\begin{quote}\nA\n\nB\n\\end{quote}"))

    def test_paragraphs_of_an_item_stay_apart(self):
        tex = _tex("\\begin{itemize}\n\\item A\n\nB\n\\end{itemize}")
        self.assertRegex(tex, r"\\item A\s*\n\s*\n\s*B")

    def test_paragraphs_of_an_abstract_stay_apart(self):
        self.assertIn("A\n\nB", _tex("\\begin{abstract}\nA\n\nB\n\\end{abstract}"))

    def test_a_text_box_frame_stays_on_its_own(self):
        source = "> Text box (x 25%, y 10%, w 30%, h 20%)\n>\n> **Title**\n>\n> Body\n"
        back = _convert(_convert(source, "markdown", "latex"), "latex", "markdown")
        self.assertEqual(back, source.replace("**Title**", "**Title**"))

    def test_an_apostrophe_is_kept(self):
        source = "L\u2019uomo\n"
        self.assertEqual(_convert(_convert(source, "markdown", "latex"), "latex", "markdown"), source)

    def test_alert_quote_comes_back(self):
        source = "> [!NOTE]\n> careful\n"
        self.assertEqual(_convert(_convert(source, "markdown", "latex"), "latex", "markdown"), source)

    def test_a_bold_opening_word_of_a_quote_is_not_an_alert(self):
        from textconverter.ast import BlockQuote
        (quote,) = _blocks("\\begin{quote}\n\\textbf{Note}\\\\\ntext\n\\end{quote}")
        self.assertIsInstance(quote, BlockQuote)
        self.assertIsNone(quote.alert_type)

    def test_a_line_break_in_a_cell_comes_back(self):
        source = "| a |\n|---|\n| x<br>y |\n"
        tex = _convert(source, "markdown", "latex")
        self.assertEqual(_convert(tex, "latex", "markdown"), source)
        self.assertIn("\\begin{tabular}{@{}c@{}}x\\\\y\\end{tabular}", tex)

    def test_code_language_comes_back(self):
        for source in ("```python\nx = 1\n```\n", "```excel\nD2:D5 = B2*C2\n```\n"):
            with self.subTest(source):
                tex = _convert(source, "markdown", "latex")
                self.assertNotIn("lstlisting", tex)
                self.assertEqual(_convert(tex, "latex", "markdown"), source)

    def test_code_without_language_has_no_comment(self):
        self.assertNotIn("language", _convert("```\nx = 1\n```\n", "markdown", "latex"))


class TestHiddenText(BaseConverterTest):

    def test_comment_environment_is_dropped(self):
        self.assertEqual(_md("a\n\n\\begin{comment}\nSECRET\n\\end{comment}\n\nb").strip(), "a\n\nb")

    def test_iffalse_is_dropped(self):
        self.assertEqual(_md("a \\iffalse HIDDEN \\fi b").strip(), "a b")

    def test_nested_conditionals_end_at_their_own_fi(self):
        self.assertEqual(_md("a \\iffalse x \\ifdefined\\foo y \\fi z \\fi b").strip(), "a b")

    def test_verbatim_keeps_them(self):
        self.assertIn("\\iffalse", _md("\\begin{verbatim}\n\\iffalse\n\\end{verbatim}"))


class TestLatexCode(BaseConverterTest):
    """Every code macro and environment reads its body as it stands."""

    def test_inline_code(self):
        for source, code in (("\\verb|x_y|", "x_y"), ("\\verb+a%b+", "a%b"), ("\\verb*|a b|", "a b"),
                             ("\\lstinline|x_y|", "x_y"), ("\\lstinline{x_y}", "x_y"),
                             ("\\lstinline[language=C]|x_y|", "x_y"), ("\\mintinline{python}{x_y}", "x_y"),
                             ("\\mintinline{python}|x_y|", "x_y"), ("{\\tt x\\_y}", "x_y"), ("{\\ttfamily x}", "x")):
            with self.subTest(source):
                self.assertEqual(_md(source).strip(), f"`{code}`")

    def test_code_environments(self):
        from textconverter.ast import CodeBlock
        for source, block in (
            ("\\begin{minted}{python}\nx = 1 % 2\n    y\n\\end{minted}", CodeBlock(code="x = 1 % 2\n    y", language="python")),
            ("\\begin{minted}[linenos]{c}\nx;\n\\end{minted}", CodeBlock(code="x;", language="c")),
            ("\\begin{Verbatim}\nx = 1 % 2\n\\end{Verbatim}", CodeBlock(code="x = 1 % 2")),
            ("\\begin{Verbatim}[numbers=left]\nx\n\\end{Verbatim}", CodeBlock(code="x")),
            ("\\begin{BVerbatim}\nx\n\\end{BVerbatim}", CodeBlock(code="x")),
        ):
            with self.subTest(source):
                self.assertEqual(_blocks(source), [block])

    def test_a_listing_caption_is_kept(self):
        from textconverter.ast import CodeBlock, Paragraph
        source = "\\begin{lstlisting}[caption={A caption},language=C]\nx;\n\\end{lstlisting}"
        caption, code = _blocks(source)
        self.assertIsInstance(caption, Paragraph)
        self.assertEqual(caption.children[0].content, "Listing: A caption")
        self.assertEqual(code, CodeBlock(code="x;", language="c"))
        self.assertEqual(_md(source), "Listing: A caption\n\n```c\nx;\n```\n")


class TestLatexInput(BaseConverterTest):
    """``\\input`` reads the files next to the source, and nothing outside its folder."""

    def _tree(self, tmp: str, **files) -> str:
        from pathlib import Path
        for name, text in files.items():
            path = Path(tmp) / (name.replace("__", "/") + ".tex")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return str(Path(tmp) / "main.tex")

    def _convert(self, main: str) -> str:
        return textconverter.convert(main, "markdown", textconverter.ConvertOptions(image_handling="link"))

    def test_a_file_is_included(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            main = self._tree(tmp, main=_wrap("Before\n\n\\input{sub/part}\n\n\\include{other.tex}\n\nAfter"),
                              sub__part="\\section{Part}\nIn part.", other="Other % comment\n")
            self.assertEqual(self._convert(main), "Before\n\n# Part\n\nIn part.\n\nOther\n\nAfter\n")

    def test_nested_paths_resolve_from_the_main_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            main = self._tree(tmp, main=_wrap("\\input{a/one}"), a__one="\\input{a/two}", a__two="Deep")
            self.assertEqual(self._convert(main).strip(), "Deep")

    def test_a_missing_file_is_reported(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp, patch("textconverter.parsers._latex_source.log_warning") as warn:
            main = self._tree(tmp, main=_wrap("a \\input{nope} b"))
            self.assertEqual(self._convert(main).strip(), "a b")
        self.assertIn("nope", warn.call_args.args[0])

    def test_a_path_outside_the_folder_is_not_read(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp, patch("textconverter.parsers._latex_source.log_warning") as warn:
            (Path(tmp) / "secret.tex").write_text("SECRET", encoding="utf-8")
            (Path(tmp) / "doc").mkdir()
            main = self._tree(str(Path(tmp) / "doc"), main=_wrap(f"a \\input{{../secret}} \\input{{{tmp}/secret}} b"))
            self.assertNotIn("SECRET", self._convert(main))
        self.assertIn("secret", warn.call_args.args[0])

    def test_only_tex_files_are_read(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data.txt").write_text("SECRET", encoding="utf-8")
            main = self._tree(tmp, main=_wrap("a \\input{data.txt} b"))
            self.assertNotIn("SECRET", self._convert(main))

    def test_a_cycle_ends(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            main = self._tree(tmp, main=_wrap("A \\input{one}"), one="B \\input{main}")
            self.assertEqual(self._convert(main).count("B"), 1)

    def test_text_without_a_folder_reads_nothing(self):
        from unittest.mock import patch
        with patch("textconverter.parsers._latex_source.log_warning") as warn:
            self.assertEqual(_md("a \\input{main} b").strip(), "a b")
        warn.assert_called_once()

    def test_a_commented_input_is_not_read(self):
        from unittest.mock import patch
        with patch("textconverter.parsers._latex_source.log_warning") as warn:
            self.assertEqual(_md("a % \\input{main}\nb").strip(), "a b")
        warn.assert_not_called()


class TestLatexDefinitions(BaseConverterTest):
    """The author's macros expand in the text and in formulas."""

    def test_plain_macro(self):
        self.assertEqual(textconverter.convert_text("\\newcommand{\\name}{value}\n" + _wrap("A \\name{} b \\name."),
                                                    "latex", "markdown").strip(), "A value b value.")

    def test_macro_in_a_formula(self):
        from textconverter.ast import Equation
        from textconverter.parsers.latex_parser import parse_latex
        doc = parse_latex("\\newcommand{\\R}{\\mathbb{R}}\n" + _wrap("$x \\in \\R$"))
        self.assertEqual(doc.children[0].children[0], Equation(code="x \\in \\mathbb{R}", inline=True))

    def test_arguments(self):
        source = "\\newcommand{\\pair}[2]{(#1, #2)}\n\\newcommand{\\dflt}[2][x]{#1-#2}\n" + _wrap("\\pair{a}{b} \\dflt{c} \\dflt[d]{e}")
        self.assertEqual(textconverter.convert_text(source, "latex", "markdown").strip(), "(a, b) x-c d-e")

    def test_def_and_renew(self):
        source = "\\def\\foo{one}\n\\newcommand{\\bar}{two}\n\\renewcommand{\\bar}{three}\n\\providecommand{\\baz}{four}\n" + _wrap("\\foo{} \\bar{} \\baz")
        self.assertEqual(textconverter.convert_text(source, "latex", "markdown").strip(), "one three four")

    def test_a_longer_name_is_not_expanded(self):
        source = "\\newcommand{\\x}{y}\n" + _wrap("\\x{} \\xx{z}")
        self.assertEqual(textconverter.convert_text(source, "latex", "markdown").strip(), "y z")

    def test_a_recursive_definition_ends(self):
        source = "\\newcommand{\\a}{\\a}\n" + _wrap("x \\a y")
        self.assertIn("x", textconverter.convert_text(source, "latex", "markdown"))

    def test_verbatim_is_not_expanded(self):
        source = "\\newcommand{\\x}{y}\n" + _wrap("\\begin{verbatim}\n\\x\n\\end{verbatim}")
        self.assertIn("\\x", textconverter.convert_text(source, "latex", "markdown"))

    def test_definitions_it_cannot_expand_are_reported(self):
        from unittest.mock import patch
        with patch("textconverter.parsers._latex_source.log_warning") as warn:
            textconverter.convert_text("\\def\\foo#1.{x}\n" + _wrap("a"), "latex", "markdown")
        self.assertIn("\\foo", warn.call_args.args[0])


class TestLatexMetadata(BaseConverterTest):

    SOURCE = "\\title{A title\\thanks{Funded by X}}\n\\author{Alice\\thanks{a@x} \\and Bob}\n" + _wrap("\\maketitle\n\nBody")

    def test_notes_and_authors_are_kept_apart(self):
        from textconverter.ast import Footnote, LineBreak
        from textconverter.parsers.latex_parser import parse_latex
        doc = parse_latex(self.SOURCE)
        self.assertEqual(doc.title[0].content, "A title")
        self.assertIsInstance(doc.title[1], Footnote)
        self.assertEqual([type(n) for n in doc.author], [type(doc.title[0]), Footnote, LineBreak, type(doc.title[0])])

    def test_latex_writes_them_back(self):
        tex = _convert(self.SOURCE, "latex", "latex")
        self.assertIn("\\title{A title\\thanks{Funded by X}}", tex)
        self.assertIn("\\author{Alice\\thanks{a@x} \\and Bob}", tex)
        for via in ("markdown", "html", "json"):
            with self.subTest(via=via):
                self.assertEqual(_convert(_convert(tex, "latex", via), via, "latex"), tex)


class TestLatexFloats(BaseConverterTest):

    SOURCE = ("\\begin{figure}\n\\begin{subfigure}{0.5\\textwidth}\n\\includegraphics{a.png}\n\\caption{First}\n\\end{subfigure}\n"
              "\\begin{subfigure}{0.5\\textwidth}\n\\includegraphics{b.png}\n\\caption{Second}\n\\end{subfigure}\n"
              "\\caption{Both}\n\\label{fig:both}\n\\end{figure}")

    def test_each_subfigure_keeps_its_caption_and_the_main_one_follows(self):
        from textconverter.ast import Image, Paragraph, walk
        from textconverter.renderers._common import plain_text
        blocks = _blocks(self.SOURCE)
        images = [n for block in blocks for n in walk(block) if isinstance(n, Image)]
        self.assertEqual([plain_text(i.caption) for i in images], ["First", "Second"])
        self.assertIsInstance(blocks[-1], Paragraph)
        self.assertIn("Figure: Both", plain_text(blocks[-1].children))

    def test_a_plain_figure_is_unchanged(self):
        from textconverter.ast import Image
        (para,) = _blocks("\\begin{figure}\n\\includegraphics{a.png}\n\\caption{Only}\n\\end{figure}")
        self.assertIsInstance(para.children[0], Image)
        self.assertEqual(len(para.children), 1)


class TestLatexMinor(BaseConverterTest):

    def test_footnotemark_and_footnotetext_are_one_note(self):
        from textconverter.ast import Footnote
        (para,) = _blocks("Text\\footnotemark{} more.\\footnotetext{The note}")
        self.assertEqual([type(n).__name__ for n in para.children], ["Text", "Footnote", "Text"])
        self.assertEqual(para.children[1], Footnote(content=[textconverter.ast.Text(content="The note")]))

    def test_footnotemarks_pair_in_order(self):
        md = _md("a\\footnotemark{} b\\footnotemark{}\n\n\\footnotetext{one}\\footnotetext{two}")
        self.assertIn("[^1]: one", md)
        self.assertIn("[^2]: two", md)

    def test_a_theorem_keeps_its_title(self):
        self.assertEqual(_md("\\begin{theorem}[Pythagoras]\nStatement.\n\\end{theorem}").strip(), "**Pythagoras** Statement.")
