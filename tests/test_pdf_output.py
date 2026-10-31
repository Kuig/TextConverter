"""PDF output: HTML printed by a headless browser, or by PyMuPDF's Story as a fallback.

Usage: python -m unittest discover -s tests -p "test_pdf_output.py"
"""
from __future__ import annotations
import unittest
from unittest.mock import patch

import pymupdf

import textconverter
from textconverter.renderers.pdf_renderer import find_browser, render_pdf
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR, OUTPUT_DIR

IMAGE = (INPUT_DIR / "OcrTable.png").as_posix()
SOURCE_MD = f"# PDF Title\n\nSome **body** text.\n\n![table]({IMAGE})\n\nInline $x^2$ math.\n"


class TestPdfOutput(BaseConverterTest):

    def _source(self) -> str:
        path = OUTPUT_DIR / "pdf_source.md"
        path.write_text(SOURCE_MD, encoding="utf-8")
        return str(path)

    def test_story_fallback_without_browser(self):
        """No browser installed: Story writes a PDF with the text and the embedded image."""
        out = self._out("story.pdf")
        with patch("textconverter.renderers.pdf_renderer.find_browser", return_value=None):
            textconverter.save_to_file(self._source(), str(out))
        with pymupdf.open(out) as pdf:
            text = "".join(page.get_text() for page in pdf)
            images = sum(len(page.get_images()) for page in pdf)
        self.assertIn("PDF Title", text)
        self.assertIn("body", text)
        self.assertEqual(images, 1)
        self.assertFalse((OUTPUT_DIR / "story_images").exists(), "PDF output left an image folder")

    def test_browser_failure_falls_back_to_story(self):
        """A browser that produces nothing does not fail the conversion in auto mode."""
        out = self._out("fallback.pdf")
        with patch("textconverter.renderers.pdf_renderer.find_browser", return_value="missing-browser.exe"):
            render_pdf("<html><body><p>Fallback text</p></body></html>", str(out))
        with pymupdf.open(out) as pdf:
            self.assertIn("Fallback text", pdf[0].get_text())

    def _pdf_text(self, source: str, name: str) -> str:
        path = OUTPUT_DIR / f"{name}.md"
        path.write_text(source, encoding="utf-8")
        out = self._out(f"{name}.pdf")
        with patch("textconverter.renderers.pdf_renderer.find_browser", return_value=None):
            textconverter.save_to_file(str(path), str(out))
        with pymupdf.open(out) as pdf:
            return "".join(page.get_text() for page in pdf)

    def test_notes_are_numbered_and_listed_at_the_end(self):
        text = self._pdf_text("Text\\footnote{The note body} more[^1].\n\n[^1]: Another note\n", "pdf_notes")
        self.assertNotIn("\\footnote", text)
        self.assertLess(text.index("more"), text.index("The note body"))
        self.assertIn("Another note", text)

    def test_citations_are_keys_in_brackets(self):
        text = self._pdf_text("See \\cite{a,b} and \\citet*{c} and \\parencite[p. 3]{d}.\n", "pdf_cites")
        self.assertNotIn("\\cit", text)
        self.assertIn("[a, b]", text)
        self.assertIn("[c]", text)
        self.assertIn("[d]", text)

    def test_references_are_numbers_when_they_can_be_told(self):
        source = ("# First\n\n## Second \\label{sec:s}\n\nTable: T \\label{tab:t}\n\n| a |\n|---|\n| 1 |\n\n"
                  "See \\ref{sec:s}, \\ref{tab:t} and \\ref{nowhere}.\n")
        text = self._pdf_text(source, "pdf_refs")
        self.assertNotIn("\\ref", text)
        self.assertIn("See 1.1, 1 and [nowhere].", " ".join(text.split()))

    def test_html_keeps_the_macros(self):
        html = textconverter.convert_text("See \\cite{a}.\n", "markdown", "html")
        self.assertIn('<span class="tc-ref">\\cite{a}</span>', html)

    def test_unknown_engine_is_rejected(self):
        with self.assertRaises(ValueError):
            render_pdf("<p>x</p>", str(OUTPUT_DIR / "never.pdf"), engine="latex")

    @unittest.skipUnless(find_browser(), "no Edge, Chrome or Chromium installed")
    def test_browser_engine(self):
        """With a browser, the PDF holds the text and the embedded image."""
        out = self._out("browser.pdf")
        html = textconverter.convert(self._source(), "html", textconverter.ConvertOptions(
            template="light", image_handling="embed"))
        render_pdf(html, str(out), engine="browser")
        with pymupdf.open(out) as pdf:
            text = "".join(page.get_text() for page in pdf)
            images = sum(len(page.get_images()) for page in pdf)
        self.assertIn("PDF Title", text)
        self.assertGreaterEqual(images, 1)
