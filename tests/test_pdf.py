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
from textconverter.parsers._pdf_layout import join_split_paragraphs, page_furniture, strip_furniture
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


class TestPageFurniture(BaseConverterTest):
    """Running heads, footers and page numbers: found from the geometry, removed from each page's text."""

    def test_journal_furniture(self):
        self.assertEqual(page_furniture(str(INPUT_DIR / "Journal PDF.pdf")), {
            1: ["Volume X, Issue X, Year", "LGU J. Comput. Sci. & IT"],
            2: ["SHORT PAPER TITLE", "2"], 3: ["Author1 and Author2 (Year)", "3"], 4: ["SHORT PAPER TITLE", "4"],
        })

    def test_furniture_leaves_the_text(self):
        cases = {
            "Journal PDF.pdf": ["Volume X", "SHORT PAPER TITLE", "Author1 and Author2 (Year)"],
            "Weird Journal PDF.pdf": ["Preprint 26 March", "Compiled using", "Smith et al.", "© 2026 The Authors"],
        }
        for name, gone in cases.items():
            with self.subTest(name):
                doc = parse_pdf(str(INPUT_DIR / name), write_images=False)
                paragraphs = [plain_text(p.children).strip() for p in doc.children if isinstance(p, Paragraph)]
                for text in gone:
                    self.assertFalse(any(text in p for p in paragraphs), text)
                self.assertFalse(any(re.fullmatch(r"\d", p) for p in paragraphs), "a page number is left")
                self.assertFalse(any(p.startswith("MNRAS") for p in paragraphs))

    def test_pdfs_without_furniture_are_unchanged(self):
        for name in ("Simple Pdf.pdf", "Vector Image PDF.pdf"):
            with self.subTest(name):
                path = str(INPUT_DIR / name)
                self.assertEqual(page_furniture(path), {})
                markdown = _import_pymupdf4llm().to_markdown(path, write_images=False)
                expected = parse_markdown(markdown, indented_code=False)
                promote_bold_headings(expected)
                self.assertEqual(parse_pdf(path, write_images=False), expected)

    def test_only_lines_made_of_furniture_go(self):
        page = "\n".join(["Running Head 2", "", "Body text", "Running Head mentioned here", "| 2 | x |",
                          "22", "2"])
        self.assertEqual(strip_furniture(page, ["Running Head", "2"]),
                         "\n".join(["", "Body text", "Running Head mentioned here", "| 2 | x |", "22"]))

    def test_formatting_and_spacing_do_not_matter(self):
        page = "MNRAS **000**, 1–2 (2026) Preprint 26 March 2026\n\nText"
        self.assertEqual(strip_furniture(page, ["MNRAS 000, 1–2 (2026)", "Preprint 26 March 2026"]), "\nText")

    def test_furniture_is_looked_for_only_near_the_ends_of_a_page(self):
        page = "\n".join(["a", "b", "c", "2", "d", "e", "f"])
        self.assertEqual(strip_furniture(page, ["2"]), page)


def _texts(*contents):
    return [Paragraph(children=[Text(content)]) for content in contents]


class TestSplitParagraphs(BaseConverterTest):
    """Paragraphs that pymupdf4llm ends in the middle of a sentence."""

    def _join(self, *blocks):
        doc = Document(children=list(blocks))
        join_split_paragraphs(doc)
        return [plain_text(block.children) for block in doc.children]

    def test_what_goes_on_is_joined(self):
        for second in ("[3], [4]. Consequently", "and then", ", then", "; then", ") then"):
            with self.subTest(second=second):
                self.assertEqual(self._join(*_texts("patterns", second)), [f"patterns {second}"])
        self.assertEqual(self._join(*_texts("techniques,", "AI enables")), ["techniques, AI enables"])
        self.assertEqual(self._join(*_texts("a", "b", "c")), ["a b c"])

    def test_what_ends_or_starts_a_sentence_is_not(self):
        for first, second in (("Ends here.", "and then"), ("Listed:", "[1] item"), ("(see it.)", "and"),
                              ("No punctuation", "Capital start"), ("Section", "12")):
            with self.subTest(first=first, second=second):
                self.assertEqual(self._join(*_texts(first, second)), [first, second])

    def test_titles_and_images_are_not_joined(self):
        from textconverter.ast import Image
        self.assertEqual(self._join(_bold("1. Scope"), *_texts("lowercase text")), ["1. Scope", "lowercase text"])
        picture = Paragraph(children=[Image(src="p.png", alt="")])
        self.assertEqual(len(self._join(*_texts("text"), picture)), 2)

    def test_no_double_space(self):
        self.assertEqual(self._join(*_texts("patterns ", "[3] next")), ["patterns [3] next"])

    def test_journal_sentences_are_whole(self):
        doc = parse_pdf(str(INPUT_DIR / "Journal PDF.pdf"), write_images=False)
        paragraphs = [plain_text(p.children) for p in doc.children if isinstance(p, Paragraph)]
        # Only the reference list starts with a citation mark
        self.assertFalse([p for p in paragraphs if p.startswith(("[3],", "[9].", "[12].", "AI enables"))])
        self.assertTrue(any("laundering patterns [3], [4]. Consequently" in p for p in paragraphs))
        self.assertTrue(any("analysis techniques, AI enables" in p for p in paragraphs))


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
