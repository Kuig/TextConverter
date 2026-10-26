"""PDF input: the text layer through pymupdf4llm, and raster mode with a faked describer.

Usage: python -m unittest discover -s tests -p "test_pdf.py"
"""
from __future__ import annotations
import os
import shutil
from unittest.mock import patch

import textconverter
from textconverter.ast import Document, Image, Paragraph, Text
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR, OUTPUT_DIR, read


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
        content = read(out_path)
        self.assertGreater(len(content.strip()), 200, "PDF output too short")

    def test_weird_journal_pdf(self):
        """Weird Journal PDF.pdf → MD: output is non-empty, contains some text."""
        in_path = INPUT_DIR / "Weird Journal PDF.pdf"
        out_path = self._out("Weird_Journal_PDF.md")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())
        content = read(out_path)
        self.assertGreater(len(content.strip()), 200, "PDF output too short")

    def test_vector_image_pdf(self):
        """Vector Image PDF.pdf → MD: output is non-empty."""
        in_path = INPUT_DIR / "Vector Image PDF.pdf"
        out_path = self._out("Vector_Image_PDF.md")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())
        self.assertGreater(out_path.stat().st_size, 0, "Output is empty")


class TestRasterMode(BaseConverterTest):
    """pdf_mode='raster': pages are rendered and handed to the describer, which is faked here."""

    def _parse(self, fake):
        from textconverter.parsers.pdf_parser import parse_pdf
        img_dir = OUTPUT_DIR / "raster_images"
        if img_dir.exists():
            shutil.rmtree(img_dir)
        with patch("textconverter.image_describer.transcribe_images", side_effect=fake), \
             patch("textconverter.image_describer.ai_client_available", return_value=True):
            doc = parse_pdf(str(INPUT_DIR / "Journal PDF.pdf"), str(OUTPUT_DIR), "raster_images", mode="raster")
        return doc, img_dir

    def test_pages_are_transcribed_in_order(self):
        """One rendered page per PDF page, passed in order; the answers form the document."""
        seen = []

        def fake(paths, config=None):
            seen.extend(paths)
            self.assertTrue(all(os.path.exists(p) for p in paths))
            return Document(children=[Paragraph(children=[Text(content=os.path.basename(p))]) for p in paths])

        doc, img_dir = self._parse(fake)
        names = [p.children[0].content for p in doc.children]
        self.assertEqual(names, [f"page_{n:04d}.png" for n in range(1, 5)])
        self.assertFalse(any(os.path.exists(p) for p in seen), "temporary page images not removed")
        self.assertFalse(img_dir.exists(), "no page should be kept when all are transcribed")

    def test_failed_page_is_kept_as_image(self):
        """A page the describer could not transcribe stays as an image in the output folder."""
        def fake(paths, config=None):
            return Document(children=[Paragraph(children=[Image(src=paths[1])])])

        doc, img_dir = self._parse(fake)
        self.assertEqual(doc.children[0].children[0].src, "raster_images/page_0002.png")
        self.assertTrue((img_dir / "page_0002.png").exists())

    def test_unknown_mode_is_rejected(self):
        from textconverter.parsers.pdf_parser import parse_pdf
        with self.assertRaises(ValueError):
            parse_pdf(str(INPUT_DIR / "Simple Pdf.pdf"), mode="ocr")
