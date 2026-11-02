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
from textconverter.config import AppConfig
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
