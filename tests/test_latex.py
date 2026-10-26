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
        # Title extracted from \title{} preamble
        self.assertIn("# **Il Teorema di Pitagora**", content, "Missing extracted title")
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
        self.assertIn("Il Teorema di Pitagora", content)
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
        self.assertIn("\\footnote{This is a footnote}", result)

    def test_latex_to_md_to_latex_safeguards(self):
        """Verify that latex macros are preserved through a latex -> md -> latex roundtrip and inner formats are parsed."""
        tex_content = "Some text with \\footnote{inner \\textbf{bold} text} and \\cite{abc}."
        md_result = textconverter.convert_text(tex_content, "latex", "markdown")
        self.assertIn("\\footnote{inner **bold** text}", md_result)
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
