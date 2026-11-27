"""PDF input: the text layer through pymupdf4llm, and raster mode with a faked describer.

Usage: python -m unittest discover -s tests -p "test_pdf.py"
"""
from __future__ import annotations
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import textconverter
from textconverter.ast import Document, Heading, Paragraph, Text
from textconverter.config import AppConfig
from textconverter.parsers._bold_headings import promote_bold_headings
from textconverter.parsers.markdown_parser import parse_markdown
from textconverter.parsers.pdf_parser import _import_pymupdf4llm, parse_pdf
from textconverter.renderers._common import plain_text
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR, OUTPUT_DIR


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
        content = self.convert_fixture("Journal PDF.pdf", "Journal_PDF.md")
        self.assertGreater(len(content.strip()), 200, "PDF output too short")

    def test_weird_journal_pdf(self):
        """Weird Journal PDF.pdf → MD: output is non-empty, contains some text."""
        content = self.convert_fixture("Weird Journal PDF.pdf", "Weird_Journal_PDF.md")
        self.assertGreater(len(content.strip()), 200, "PDF output too short")

    def test_vector_image_pdf(self):
        """Vector Image PDF.pdf → MD: output is non-empty."""
        in_path = INPUT_DIR / "Vector Image PDF.pdf"
        out_path = self._out("Vector_Image_PDF.md")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())
        self.assertGreater(out_path.stat().st_size, 0, "Output is empty")


def _bold(text):
    return Paragraph(children=[Text(text, bold=True)])


def _prose(words=12):
    return Paragraph(children=[Text(" ".join(["Running text of the section."] * words))])


def _headings(doc):
    return [(b.level, plain_text(b.children)) for b in doc.children if isinstance(b, Heading)]


class TestBoldHeadings(BaseConverterTest):
    """Bold paragraphs read as headings when a PDF has no heading structure."""

    def _promote(self, *blocks):
        doc = Document(children=list(blocks))
        promote_bold_headings(doc)
        return doc

    def test_numbering_gives_the_level(self):
        doc = self._promote(_bold("1. Introduction"), _prose(), _bold("1.1 Scope"), _prose(),
                            _bold("2 Methods"), _bold("2.1. Data"), _prose())
        self.assertEqual(_headings(doc), [(1, "1. Introduction"), (2, "1.1 Scope"),
                                          (1, "2 Methods"), (2, "2.1. Data")])

    def test_levels_start_below_a_title(self):
        doc = self._promote(Heading(level=1, children=[Text("Paper")]), _bold("I. INTRODUCTION"),
                            _prose(), _bold("3.1. Data"), _prose())
        self.assertEqual(_headings(doc), [(1, "Paper"), (2, "I. INTRODUCTION"), (3, "3.1. Data")])

    def test_a_document_with_headings_is_left_alone(self):
        blocks = (Heading(level=1, children=[Text("A")]), _bold("1. Intro"), _prose(),
                  Heading(level=1, children=[Text("B")]))
        self.assertEqual(len(_headings(self._promote(*blocks))), 2)

    def test_a_heading_after_a_candidate_is_not_a_title(self):
        doc = self._promote(_bold("1. Intro"), _prose(), Heading(level=1, children=[Text("B")]))
        self.assertIsInstance(doc.children[0], Paragraph)

    def test_unnumbered_titles_need_running_text_after_them(self):
        doc = self._promote(_bold("ABSTRACT"), _prose(), _bold("Related Work"), _prose(),
                            _bold("Column 1 Column 2 Column 3"),
                            Paragraph(children=[Text("Entry 1 Entry 2 Entry 3")]))
        self.assertEqual(_headings(doc), [(1, "ABSTRACT"), (1, "Related Work")])

    def test_what_is_not_a_title_stays_a_paragraph(self):
        doc = self._promote(
            Paragraph(children=[Text("Table 1.", bold=True), Text(" General caption")]),
            _bold("Keywords:"), _prose(),
            _bold("A whole sentence in bold."), _prose(),
            _bold(" ".join(["Long bold text"] * 8)), _prose(),
            _bold("2026"), _prose(),
        )
        self.assertEqual(_headings(doc), [])

    def test_the_bold_goes_and_other_formatting_stays(self):
        doc = self._promote(Paragraph(children=[Text("1.", bold=True), Text(" "),
                                                Text("Scope", bold=True, italic=True), Text(" ")]),
                            _prose())
        heading = doc.children[0]
        self.assertIsInstance(heading, Heading)
        self.assertEqual([(t.content, t.bold, t.italic) for t in heading.children],
                         [("1.", False, False), (" ", False, False), ("Scope", False, True)])

    def test_journal_sections(self):
        doc = parse_pdf(str(INPUT_DIR / "Journal PDF.pdf"), write_images=False)
        self.assertEqual(_headings(doc)[1:], [
            (2, "ABSTRACT"), (2, "1. INTRODUCTION"), (2, "2. LITERATURE REVIEW"), (2, "3. METHODOLOGY"),
            (3, "3.1. Data Collection"), (3, "3.2. Data Preprocessing"), (3, "3.3. Model Design"),
            (2, "4. RESULTS"), (2, "5. DISCUSSION"), (2, "6. CONCLUSION"), (2, "7. REFERENCES"),
        ])

    def test_weird_journal_sections(self):
        doc = parse_pdf(str(INPUT_DIR / "Weird Journal PDF.pdf"), write_images=False)
        self.assertEqual(_headings(doc)[1:], [
            (2, "1 INTRODUCTION"), (2, "2 METHODS, OBSERVATIONS, SIMULATIONS ETC."), (3, "2.1 Maths"),
            (2, "3 CONCLUSIONS"), (3, "2.2 Figures and tables"), (2, "ACKNOWLEDGEMENTS"),
            (2, "DATA AVAILABILITY"), (2, "REFERENCES"), (2, "APPENDIX A: SOME EXTRA MATERIAL"),
        ])

    def test_pdfs_with_headings_are_unchanged(self):
        for name in ("Simple Pdf.pdf", "Vector Image PDF.pdf"):
            with self.subTest(name):
                path = str(INPUT_DIR / name)
                markdown = _import_pymupdf4llm().to_markdown(path, write_images=False)
                expected = parse_markdown(markdown, indented_code=False)
                self.assertEqual(_headings(parse_pdf(path, write_images=False)), _headings(expected))


class TestRasterMode(BaseConverterTest):
    """pdf_mode='raster': pages are rendered and go through the image passes, with the AI faked here."""

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)

    def _convert(self, answer=None, **options):
        """Journal PDF.pdf (four pages) as Markdown; ``answer`` gives the text of a page file."""
        config = AppConfig()
        config.ai.region_model = ""

        def fake(**kwargs):
            text = '{"category": "text"}' if kwargs.get("format_json") else answer(kwargs["file_path"])
            return MagicMock(text=text)

        with patch("unified_ai_client.call_ai", side_effect=fake), patch("unified_ai_client.preload_model"):
            return textconverter.convert(str(INPUT_DIR / "Journal PDF.pdf"), "markdown",
                                         textconverter.ConvertOptions(pdf_mode="raster", **options),
                                         output_dir=str(self.dir), image_dir_name="pages", config=config)

    def test_a_page_is_an_image_in_order(self):
        from textconverter.parsers.pdf_parser import parse_pdf
        doc = parse_pdf(str(INPUT_DIR / "Journal PDF.pdf"), pdf_mode="raster", pages_dir=str(self.dir))
        pages = [p.children[0] for p in doc.children]
        self.assertEqual([page.alt for page in pages], [f"page_{n:04d}.png" for n in range(1, 5)])
        self.assertTrue(all(os.path.isabs(page.src) and os.path.exists(page.src) for page in pages))

    def test_pages_are_transcribed_in_order(self):
        """The answers form the document, and no page is left on disk."""
        text = self._convert(lambda path: os.path.basename(path).replace("_", " "))
        self.assertEqual(re.findall(r"page \d+", text), [f"page {n:04d}" for n in range(1, 5)])
        self.assertFalse((self.dir / "pages").exists())

    def test_failed_page_is_kept_as_image(self):
        """A page that could not be transcribed stays as an image in the output folder."""
        text = self._convert(lambda path: "" if path.endswith("0002.png") else "Read.")
        self.assertEqual(text.count("Read."), 3)
        self.assertIn("(pages/image_1.png)", text)
        self.assertEqual([p.name for p in (self.dir / "pages").iterdir()], ["image_1.png"])

    def test_keep_gives_the_pages_without_any_model(self):
        with patch("textconverter.image_describer.ai_client_available", return_value=False):
            text = self._convert(image_handling="keep")
        self.assertEqual(text.count("!["), 4)
        self.assertEqual(len(list((self.dir / "pages").iterdir())), 4)

    def test_discard_is_refused(self):
        with self.assertRaisesRegex(ValueError, "replace"):
            self._convert(image_handling="discard")

    def test_auto_needs_the_client(self):
        with patch("textconverter.image_describer.ai_client_available", return_value=False):
            with self.assertRaises(ImportError):
                self._convert()

    def test_unknown_mode_is_rejected(self):
        from textconverter.parsers.pdf_parser import parse_pdf
        with self.assertRaises(ValueError):
            parse_pdf(str(INPUT_DIR / "Simple Pdf.pdf"), pdf_mode="ocr")
