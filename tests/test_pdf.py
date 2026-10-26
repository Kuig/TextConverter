"""PDF input through pymupdf4llm.

Usage: python -m unittest discover -s tests -p "test_pdf.py"
"""
from __future__ import annotations

import textconverter
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR, read


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
