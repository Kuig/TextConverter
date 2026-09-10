from __future__ import annotations
import os
import sys
import unittest
import shutil
import socket
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent directory to sys.path to run textconverter locally
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import textconverter

# Mock unified_ai_client if not installed to prevent import errors during tests
try:
    import unified_ai_client
except ImportError:
    mock_client = MagicMock()
    sys.modules['unified_ai_client'] = mock_client

TEST_DIR = Path(__file__).resolve().parent
INPUT_DIR = TEST_DIR / "Input"
OUTPUT_DIR = TEST_DIR / "Output"


def is_connected() -> bool:
    """Check if internet connection is available."""
    try:
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return True
    except socket.error:
        return False


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Base class to avoid repeating setUpClass in every test class
# ---------------------------------------------------------------------------

class BaseConverterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    def _out(self, filename: str) -> Path:
        """Return output path, deleting any existing file first."""
        p = OUTPUT_DIR / filename
        if p.exists():
            p.unlink()
        return p


# ---------------------------------------------------------------------------
# Markdown Parser Tests
# ---------------------------------------------------------------------------

class TestMarkdownParser(BaseConverterTest):

    def test_md_to_html_structure(self):
        """SampleMD.md → HTML: headings, paragraphs, table, code, blockquote, list."""
        in_path = INPUT_DIR / "SampleMD.md"
        out_path = self._out("SampleMD.html")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())

        content = _read(out_path)
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
        in_path = INPUT_DIR / "SampleMD.md"
        out_path = self._out("SampleMD_out.md")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())

        content = _read(out_path)
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
        in_path = INPUT_DIR / "CodeTest.md"
        out_path = self._out("CodeTest.html")

        textconverter.save_to_file(str(in_path), str(out_path), code_parsing=True)
        self.assertTrue(out_path.exists())

        content = _read(out_path)
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
        result = textconverter.convert(html_content, to_format="markdown", from_format="html")
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
        ast = _json.loads(textconverter.convert(md, to_format="json", from_format="markdown"))
        row = ast["children"][0]["rows"][0]
        self.assertEqual(len(row["cells"]), 3, "escaped/code-span pipes split the row into extra cells")
        type_cell = row["cells"][1]["children"]
        self.assertEqual([n["type"] for n in type_cell], ["CodeInline"])
        self.assertEqual(type_cell[0]["code"], "str | list[str] | None")

        html = textconverter.convert(md, to_format="html", from_format="markdown")
        self.assertIn("<td><code>str | list[str] | None</code></td>", html)
        self.assertNotIn("\\|", html)

        # MD round-trip: literal pipe re-emitted escaped and still parses to 3 cells.
        md2 = textconverter.convert(md, to_format="markdown", from_format="markdown")
        self.assertIn(r"`str \| list[str] \| None`", md2)
        ast2 = _json.loads(textconverter.convert(md2, to_format="json", from_format="markdown"))
        self.assertEqual(len(ast2["children"][0]["rows"][0]["cells"]), 3)


# ---------------------------------------------------------------------------
# HTML Parser Tests
# ---------------------------------------------------------------------------

class TestHtmlParser(BaseConverterTest):

    def test_sample_html_to_markdown(self):
        """SampleHtml.htm → MD: text content, lists, table, links survive parsing."""
        in_path = INPUT_DIR / "SampleHtml.htm"
        out_path = self._out("SampleHtml.md")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())

        content = _read(out_path)
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

        md = textconverter.convert(html, to_format="markdown", from_format="html")
        rows = _data_rows(md)
        self.assertEqual(len({l.count("|") for l in rows}), 1, f"ragged markdown table: {rows}")
        self.assertIn("Left Right", md, "adjacent <div> cell text glued together")
        self.assertNotIn("LeftRight", md)

        # extract_html path strips unknown attrs — colspan/rowspan must survive it too.
        md_x = textconverter.convert(html, to_format="markdown", from_format="html", extract_html=True)
        self.assertEqual(len({l.count("|") for l in _data_rows(md_x)}), 1, "ragged table after extract_html")

        tex = textconverter.convert(html, to_format="latex", from_format="html")
        body = [l for l in tex.splitlines() if l.rstrip().endswith("\\\\") and "&" in l]
        self.assertTrue(body)
        self.assertEqual(len({l.count("&") for l in body}), 1, f"ragged latex table: {body}")

        ast = textconverter.convert(html, to_format="json", from_format="html")
        self.assertNotIn("_colspan", ast)
        self.assertNotIn("_rowspan", ast)
        table = _json.loads(ast)["children"][0]
        self.assertEqual({len(r["cells"]) for r in table["rows"]}, {4})

    def test_main_content_extraction(self):
        """MainContentTest.html → MD with extract_html=True: only main block, no nav/footer."""
        in_path = INPUT_DIR / "MainContentTest.html"
        out_path = self._out("MainContentTest.md")

        textconverter.save_to_file(str(in_path), str(out_path), extract_html=True)
        self.assertTrue(out_path.exists())

        content = _read(out_path)
        self.assertIn("Main Title", content, "Missing main content title")
        self.assertIn("This is the main content.", content, "Missing main content paragraph")
        self.assertNotIn("Footer info", content, "Footer should be stripped")
        self.assertNotIn("Home", content, "Nav should be stripped")


# ---------------------------------------------------------------------------
# LaTeX Parser Tests
# ---------------------------------------------------------------------------

class TestLatexParser(BaseConverterTest):

    def test_simple_latex_to_markdown(self):
        """SampleLatex.tex → MD: title, abstract blockquote, quotes, code preserved."""
        in_path = INPUT_DIR / "SampleLatex.tex"
        out_path = self._out("SampleLatex.md")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())

        content = _read(out_path)
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
        in_path = INPUT_DIR / "SampleLatex.tex"
        out_path = self._out("SampleLatex.html")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())

        content = _read(out_path)
        self.assertIn("Il Teorema di Pitagora", content, "Missing title in HTML")
        self.assertIn("Abstract", content, "Missing Abstract heading in HTML")
        self.assertIn('<blockquote class="alert-important">', content, "Missing abstract blockquote element in HTML")

    def test_latex_to_html_with_light_template(self):
        """SampleLatex.tex → HTML with pretty (light) template: verifies CSS and MathJax script are present."""
        in_path = INPUT_DIR / "SampleLatex.tex"
        out_path = self._out("SampleLatex_pretty.html")

        textconverter.save_to_file(str(in_path), str(out_path), template="pretty")
        self.assertTrue(out_path.exists())

        content = _read(out_path)
        self.assertIn("MathJax-script", content)
        self.assertIn(".math.inline", content)
        self.assertIn("Il Teorema di Pitagora", content)
        self.assertIn("font-family: -apple-system", content)

    def test_latex_to_html_with_dark_template(self):
        """SampleLatex.tex → HTML with dark-theme template: verifies dark CSS background and MathJax script."""
        in_path = INPUT_DIR / "SampleLatex.tex"
        out_path = self._out("SampleLatex_dark.html")

        textconverter.save_to_file(str(in_path), str(out_path), template="dark-theme")
        self.assertTrue(out_path.exists())

        content = _read(out_path)
        self.assertIn("MathJax-script", content)
        self.assertIn('background-color: #0d1117;', content)
        self.assertIn('color: #c9d1d9;', content)

    def test_journal_latex_to_markdown(self):
        """Journal TEX.tex → MD: abstract (section-style), introduction section present."""
        in_path = INPUT_DIR / "Journal TEX.tex"
        out_path = self._out("Journal_TEX.md")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())

        content = _read(out_path)
        self.assertGreater(len(content.strip()), 100, "Output is too short for a journal")
        self.assertIn("Introduction", content, "Missing Introduction section")
        self.assertIn("Methodology", content, "Missing Methodology section")

    def test_weird_journal_latex_to_markdown(self):
        """Weird Journal TEX.tex → MD: begin{abstract} environment, table, section present."""
        in_path = INPUT_DIR / "Weird Journal TEX.tex"
        out_path = self._out("Weird_Journal_TEX.md")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())

        content = _read(out_path)
        self.assertGreater(len(content.strip()), 100, "Output is too short for a journal")
        # Abstract from \begin{abstract}
        self.assertIn("Abstract", content, "Missing Abstract section")
        # Body section
        self.assertIn("Introduction", content, "Missing Introduction section")
        # Table from \begin{tabular}
        self.assertIn("|", content, "Missing table (tabular) content")

    def test_simple_latex_to_latex(self):
        """SampleLatex.tex → LaTeX: structural elements roundtrip to latex code."""
        in_path = INPUT_DIR / "SampleLatex.tex"
        out_path = self._out("SampleLatex_out.tex")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())

        content = _read(out_path)
        self.assertIn("\\documentclass{article}", content)
        self.assertIn("\\begin{document}", content)
        self.assertIn("Il Teorema di Pitagora", content)
        self.assertIn("\\begin{verbatim}", content)
        self.assertIn("\\end{document}", content)

    def test_weird_journal_latex_to_latex(self):
        """Weird Journal TEX.tex → LaTeX: abstract, sections, and table roundtrip to latex code."""
        in_path = INPUT_DIR / "Weird Journal TEX.tex"
        out_path = self._out("Weird_Journal_TEX_out.tex")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())

        content = _read(out_path)
        self.assertIn("\\documentclass{article}", content)
        self.assertIn("\\begin{document}", content)
        self.assertIn("Introduction", content)
        self.assertIn("\\begin{tabular}", content)
        self.assertIn("\\end{document}", content)

    def test_latex_safeguards(self):
        """Verify that latex macros like \\cite, \\ref, \\label, and \\footnote are preserved."""
        tex_content = "This is a cite \\cite{somekey}, a label \\label{lbl}, a ref \\ref{lbl}, and a footnote \\footnote{This is a footnote}."
        result = textconverter.convert(tex_content, to_format="markdown", from_format="latex")
        self.assertIn("\\cite{somekey}", result)
        self.assertIn("\\label{lbl}", result)
        self.assertIn("\\ref{lbl}", result)
        self.assertIn("\\footnote{This is a footnote}", result)

    def test_latex_to_md_to_latex_safeguards(self):
        """Verify that latex macros are preserved through a latex -> md -> latex roundtrip and inner formats are parsed."""
        tex_content = "Some text with \\footnote{inner \\textbf{bold} text} and \\cite{abc}."
        md_result = textconverter.convert(tex_content, to_format="markdown", from_format="latex")
        self.assertIn("\\footnote{inner **bold** text}", md_result)
        self.assertIn("\\cite{abc}", md_result)
        
        # Now convert back to latex
        tex_result = textconverter.convert(md_result, to_format="latex", from_format="markdown")
        # Should be back to latex with proper bold
        self.assertIn("\\footnote{inner \\textbf{bold} text}", tex_result)
        self.assertIn("\\cite{abc}", tex_result)

    def test_abstract_roundtrip(self):
        """Verify that the abstract environment is preserved through latex -> md -> html -> latex."""
        tex_content = "\\begin{abstract}\nThis is the abstract text.\n\\end{abstract}"
        md_result = textconverter.convert(tex_content, to_format="markdown", from_format="latex")
        self.assertIn("> [!IMPORTANT]", md_result)
        self.assertIn("> **Abstract**", md_result)
        self.assertIn("> This is the abstract text.", md_result)
        
        html_result = textconverter.convert(md_result, to_format="html", from_format="markdown")
        self.assertIn('<blockquote class="alert-important">', html_result)
        self.assertIn('<div class="alert-title">Abstract</div>', html_result)
        self.assertIn('This is the abstract text.', html_result)
        
        final_tex = textconverter.convert(html_result, to_format="latex", from_format="html")
        self.assertIn("\\begin{abstract}", final_tex)
        self.assertIn("This is the abstract text.", final_tex)
        self.assertIn("\\end{abstract}", final_tex)

    def test_latex_math_to_html(self):
        """Verify that LaTeX math environments are correctly converted to HTML math elements."""
        tex_content = "Inline $x=1$ and block \\begin{equation} y=2 \\end{equation} and display \\[ z=3 \\]."
        result = textconverter.convert(tex_content, to_format="html", from_format="latex")
        self.assertIn('<span class="math inline">\\(x=1\\)</span>', result)
        self.assertIn('<div class="math block">$$\ny=2\n$$</div>', result)
        self.assertIn('<div class="math block">$$\nz=3\n$$</div>', result)




# ---------------------------------------------------------------------------
# PDF Parser Tests
# ---------------------------------------------------------------------------

class TestPdfParser(BaseConverterTest):

    def test_simple_pdf(self):
        """Simple Pdf.pdf → MD: output is non-empty."""
        in_path = INPUT_DIR / "Simple Pdf.pdf"
        out_path = self._out("Simple_Pdf.md")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())
        self.assertGreater(out_path.stat().st_size, 0, "Output is empty")

    def test_journal_pdf(self):
        """Journal PDF.pdf → MD: output is non-empty, contains some text."""
        in_path = INPUT_DIR / "Journal PDF.pdf"
        out_path = self._out("Journal_PDF.md")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())
        content = _read(out_path)
        self.assertGreater(len(content.strip()), 200, "PDF output too short")

    def test_weird_journal_pdf(self):
        """Weird Journal PDF.pdf → MD: output is non-empty, contains some text."""
        in_path = INPUT_DIR / "Weird Journal PDF.pdf"
        out_path = self._out("Weird_Journal_PDF.md")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())
        content = _read(out_path)
        self.assertGreater(len(content.strip()), 200, "PDF output too short")

    def test_vector_image_pdf(self):
        """Vector Image PDF.pdf → MD: output is non-empty."""
        in_path = INPUT_DIR / "Vector Image PDF.pdf"
        out_path = self._out("Vector_Image_PDF.md")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())
        self.assertGreater(out_path.stat().st_size, 0, "Output is empty")


# ---------------------------------------------------------------------------
# Image Describer Tests (mocked)
# ---------------------------------------------------------------------------

class TestImageDescriber(BaseConverterTest):

    @patch("unified_ai_client.preload_model")
    @patch("unified_ai_client.call_ai")
    def test_image_description_mocked(self, mock_call, mock_preload):
        """Foto.jpg with describe mode: mocked AI calls produce description in output."""
        mock_class_resp = MagicMock()
        mock_class_resp.text = '{"category": "diagram"}'
        mock_desc_resp = MagicMock()
        mock_desc_resp.text = "This is a detailed mock description of the diagram."
        mock_call.side_effect = [mock_class_resp, mock_desc_resp]

        in_path = INPUT_DIR / "Foto.jpg"
        out_path = self._out("Foto_described.md")

        textconverter.save_to_file(str(in_path), str(out_path), image_handling="describe")
        self.assertTrue(out_path.exists())

        content = _read(out_path)
        self.assertIn("This is a detailed mock description of the diagram.", content,
                      "Description text not found in output")
        # Verify both calls were made (classification + description)
        self.assertEqual(mock_call.call_count, 2, "Expected 2 AI calls (classify + describe)")
        mock_preload.assert_called()


# ---------------------------------------------------------------------------
# Remote Integration Tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(is_connected(), "No internet connection available")
class TestRemoteIntegration(BaseConverterTest):

    def test_remote_bread_link(self):
        """Remote URL → MD with image_handling=link: output and image folder created."""
        out_path = self._out("Pane.md")
        img_dir = OUTPUT_DIR / "Pane_images"
        if img_dir.exists():
            shutil.rmtree(img_dir)

        textconverter.save_to_file(
            "https://daginoilbonaparte.it/blog-di-cucina/ricetta-pane-impasta/",
            str(out_path),
            image_handling="link",
            code_parsing=True,
            extract_html=False
        )
        self.assertTrue(out_path.exists(), "Output markdown file not created")
        self.assertTrue(img_dir.exists(), "Image directory was not created")
        self.assertGreater(len(os.listdir(img_dir)), 0, "Image directory is empty")

    def test_remote_bread_discard(self):
        """Remote URL → MD with image_handling=discard: output created, no image folder."""
        out_path = self._out("Pane_discard.md")
        img_dir = OUTPUT_DIR / "Pane_discard_images"
        if img_dir.exists():
            shutil.rmtree(img_dir)

        textconverter.save_to_file(
            "https://daginoilbonaparte.it/blog-di-cucina/ricetta-pane-impasta/",
            str(out_path),
            image_handling="discard",
            code_parsing=True,
            extract_html=True
        )
        self.assertTrue(out_path.exists(), "Output markdown file not created")
        self.assertFalse(img_dir.exists(), "Image directory should NOT be created with discard")

    def test_remote_wikipedia_swish(self):
        """Wikipedia Swish function → HTML: output created, contains expected content."""
        out_path = self._out("Swish.html")

        textconverter.save_to_file(
            "https://en.wikipedia.org/wiki/Swish_function",
            str(out_path),
            image_handling="discard",
            code_parsing=True,
            extract_html=True,
            template="light"
        )
        self.assertTrue(out_path.exists(), "Output HTML file not created")
        content = _read(out_path)
        self.assertIn("Swish", content, "Expected 'Swish' keyword not found in output")


if __name__ == "__main__":
    unittest.main()