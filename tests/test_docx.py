"""Word (.docx) input: the real fixture Test_docx.docx and documents built with python-docx.

Usage: python -m unittest discover -s tests -p "test_docx.py"
"""
from __future__ import annotations
import io
import os
import tempfile
import zipfile
from unittest.mock import patch

import docx
from lxml import etree

import textconverter
from textconverter.ast import (
    BlockQuote, CodeBlock, CodeInline, Equation, Footnote, Heading, Image, LineBreak, Link, ListBlock,
    Paragraph, Table, Text, walk,
)
from textconverter.parsers._omml import M_NS, omml_to_latex
from textconverter.parsers.docx_parser import parse_docx
from textconverter.renderers._common import plain_text
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR

FIXTURE = INPUT_DIR / "Test_docx.docx"


def _of(doc, cls):
    return [n for n in walk(doc) if isinstance(n, cls)]


def _png() -> io.BytesIO:
    from PIL import Image as PilImage
    buffer = io.BytesIO()
    PilImage.new("RGB", (4, 3), "red").save(buffer, "PNG")
    buffer.seek(0)
    return buffer


class DocxFixtureTest(BaseConverterTest):
    """Parses Test_docx.docx once; the tests read the same AST."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        with patch("textconverter.parsers.docx_parser.log_warning") as warn:
            cls.doc = parse_docx(str(FIXTURE), output_dir=cls.tmp.name, image_dir_name="img")
        cls.warnings = [call.args[0] for call in warn.call_args_list]


class TestFixtureStructure(DocxFixtureTest):

    def test_title_and_metadata(self):
        """The Title paragraph wins over the file properties; author and date come from the properties."""
        self.assertEqual(plain_text(self.doc.title), "Documento di test")
        self.assertEqual(plain_text(self.doc.author), "Giorgio Presti")
        self.assertEqual(plain_text(self.doc.date), "2026-10-30")

    def test_subtitle_is_a_paragraph_and_headings_have_levels(self):
        first = self.doc.children[0]
        self.assertIsInstance(first, Paragraph)
        self.assertEqual(plain_text(first.children), "Questo è un sottotitolo")
        levels = [(h.level, plain_text(h.children)) for h in _of(self.doc, Heading)]
        self.assertIn((1, "Testo:"), levels)
        self.assertIn((2, "Paragrafi:"), levels)
        self.assertTrue(all(text.strip() for _, text in levels), "empty headings must be dropped")

    def test_inline_formatting_links_and_scripts(self):
        texts = _of(self.doc, Text)
        self.assertTrue(any(t.strikethrough for t in texts))
        self.assertTrue(any(t.bold and t.content.startswith("Lorem") for t in texts))
        self.assertEqual({t.script for t in texts if t.script}, {"sup", "sub"})
        link = _of(self.doc, Link)[0]
        self.assertEqual(link.url, "https://www.google.com")
        self.assertEqual(plain_text(link.content), "link")

    def test_tabs_become_spaces(self):
        self.assertFalse(any("\t" in t.content for t in _of(self.doc, Text)))

    def test_quote_and_text_box(self):
        quotes = [plain_text(q.children[0].children) if isinstance(q.children[0], Paragraph) else ""
                  for q in _of(self.doc, BlockQuote)]
        self.assertIn("Nuovo paragrafo come stile citazione", quotes)
        box = [q for q in quotes if q.startswith("Casella di testo")]
        self.assertEqual(len(box), 1, "the text box is read once, not once per AlternateContent branch")

    def test_code_block_and_inline_code(self):
        blocks = _of(self.doc, CodeBlock)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].code, "for (int i = 0; i < k; ++i)\n{\n\tobject.print(i);\n}")
        self.assertIn("inline", [c.code for c in _of(self.doc, CodeInline)])

    def test_formula_is_latex(self):
        equation = _of(self.doc, Equation)[0]
        self.assertFalse(equation.inline)
        self.assertIn(r"\sum_{n=1}^\infty", equation.code)
        self.assertIn(r"\frac{n\pi x}{L}", equation.code)

    def test_footnote(self):
        notes = _of(self.doc, Footnote)
        self.assertEqual(len(notes), 1)
        self.assertEqual(plain_text(notes[0].content), "Ecco la nota, formattata")

    def test_image_figure_and_caption(self):
        images = _of(self.doc, Image)
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].src, "img/image_1.jpeg")
        self.assertEqual(plain_text(images[0].caption), "Esempio di immagine con didascalia")
        self.assertTrue(os.path.isfile(os.path.join(self.tmp.name, "img", "image_1.jpeg")))

    def test_warning_lists_what_was_dropped(self):
        self.assertEqual(len(self.warnings), 1)
        for what in ("underlined text", "highlighted text", "shape", "header", "footer"):
            self.assertIn(what, self.warnings[0])


class TestFixtureListsAndTables(DocxFixtureTest):

    def test_mixed_nested_lists(self):
        lists = [b for b in self.doc.children if isinstance(b, ListBlock)]
        self.assertEqual([lst.ordered for lst in lists], [False, True, True])
        bullets, numbered, lettered = lists
        self.assertEqual([plain_text(i.children[0].children) for i in bullets.items][:3], ["A", "B e c e d", "EFG"])
        nested = bullets.items[2].children[-1]
        self.assertIsInstance(nested, ListBlock)
        self.assertEqual(len(nested.items), 3)
        self.assertFalse(numbered.items[1].children[-1].ordered, "bullets inside a numbered list")
        self.assertTrue(lettered.items[0].children[-1].ordered)

    def test_tables_headers_and_merged_cells(self):
        first, second = _of(self.doc, Table)
        self.assertEqual([plain_text(c.children) for c in first.headers], ["Prova 11", "12"])
        self.assertEqual(len(first.rows), 1)
        self.assertEqual([plain_text(c.children) for c in second.headers], ["celle unite", "", "Non unita"])
        self.assertEqual([plain_text(c.children) for c in second.rows[1].cells], ["DDati", "Altre celle unite", ""])
        self.assertTrue(any(isinstance(n, LineBreak) for n in walk(first.rows[0].cells[1])))

    def test_captions_lose_label_and_number(self):
        first, second = _of(self.doc, Table)
        self.assertEqual(first.caption, [])
        self.assertEqual(plain_text(second.caption),
                         "In realtà è la due perchè la 1 non ha didascalia ma va bene")


class TestGeneratedDocuments(BaseConverterTest):
    """Small documents built with python-docx."""

    def _parse(self, build, **kwargs):
        document = docx.Document()
        build(document)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "doc.docx")
            document.save(path)
            return parse_docx(path, output_dir=tmp, image_dir_name="img", **kwargs)

    def test_style_based_lists_nest_by_style_name(self):
        def build(d):
            d.add_paragraph("a", style="List Bullet")
            d.add_paragraph("b", style="List Bullet 2")
            d.add_paragraph("c", style="List Bullet")
            d.add_paragraph("one", style="List Number")
        doc = self._parse(build)
        bullets, numbered = doc.children
        self.assertEqual(len(bullets.items), 2)
        self.assertEqual(len(bullets.items[0].children), 2)
        self.assertTrue(numbered.ordered)

    def test_task_items_and_reference_macros(self):
        def build(d):
            d.add_paragraph("☑ done", style="List Bullet")
            d.add_paragraph("☐ todo", style="List Bullet")
            d.add_paragraph("As in \\cite{knuth} and \\ref{fig:a}.")
        doc = self._parse(build)
        self.assertEqual([i.checked for i in doc.children[0].items], [True, False])
        kinds = {type(n).__name__ for n in walk(doc.children[1])}
        self.assertTrue({"Citation", "Reference"} <= kinds)

    def test_caption_before_a_table_and_after_a_figure(self):
        def build(d):
            caption = d.add_paragraph("Totals", style="Caption")
            caption.add_run().add_text("")
            table = d.add_table(rows=1, cols=1)
            table.rows[0].cells[0].text = "x"
            d.add_paragraph().add_run().add_picture(_png())
            d.add_paragraph("A red square", style="Caption")
        doc = self._parse(build)
        table = _of(doc, Table)[0]
        self.assertEqual(plain_text(table.caption), "Totals")
        self.assertEqual(plain_text(_of(doc, Image)[0].caption), "A red square")

    def test_display_equation_style_and_environment(self):
        def build(d):
            d.styles.add_style("Equation", docx.enum.style.WD_STYLE_TYPE.PARAGRAPH)
            d.add_paragraph("\\begin{align}a&=b\\end{align}", style="Equation")
        equation = self._parse(build).children[0]
        self.assertEqual((equation.code, equation.env, equation.inline), ("a&=b", "align", False))

    def test_images_can_be_left_out_and_get_generated_names(self):
        def build(d):
            d.add_paragraph().add_run().add_picture(_png())
        doc = self._parse(build)
        self.assertEqual(_of(doc, Image)[0].src, "img/image_1.png")
        self.assertEqual(_of(self._parse(build, write_images=False), Image), [])

    def test_same_image_twice_is_one_file(self):
        def build(d):
            for _ in range(2):
                d.add_paragraph().add_run().add_picture(_png())
        doc = self._parse(build)
        self.assertEqual({i.src for i in _of(doc, Image)}, {"img/image_1.png"})

    def test_not_a_word_document_is_a_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.docx")
            with open(bad, "w", encoding="utf-8") as f:
                f.write("not a zip")
            with self.assertRaisesRegex(ValueError, "Not a readable Word"):
                parse_docx(bad)
            empty = os.path.join(tmp, "empty.docx")
            with zipfile.ZipFile(empty, "w") as z:
                z.writestr("hello.txt", "x")
            with self.assertRaisesRegex(ValueError, "Not a readable Word"):
                parse_docx(empty)


class TestOmml(BaseConverterTest):

    def _latex(self, body: str) -> str:
        xml = f'<m:oMath xmlns:m="{M_NS}">{body}</m:oMath>'
        return omml_to_latex(etree.fromstring(xml))

    @staticmethod
    def _r(text: str) -> str:
        return f"<m:r><m:t>{text}</m:t></m:r>"

    def test_scripts_fractions_and_radicals(self):
        r = self._r
        self.assertEqual(self._latex(f"<m:sSup><m:e>{r('x')}</m:e><m:sup>{r('2')}</m:sup></m:sSup>"), "x^2")
        self.assertEqual(self._latex(f"<m:f><m:num>{r('a')}</m:num><m:den>{r('b')}</m:den></m:f>"), r"\frac{a}{b}")
        self.assertEqual(self._latex(f"<m:rad><m:radPr><m:degHide m:val='1'/></m:radPr><m:deg/><m:e>{r('x')}</m:e></m:rad>"),
                         r"\sqrt{x}")
        self.assertEqual(self._latex(f"<m:rad><m:deg>{r('3')}</m:deg><m:e>{r('x')}</m:e></m:rad>"), r"\sqrt[3]{x}")

    def test_greek_letters_are_kept_apart_from_following_letters(self):
        self.assertEqual(self._latex(self._r("αx")), r"\alpha x")

    def test_matrix_and_delimiters(self):
        r = self._r
        row = f"<m:mr><m:e>{r('a')}</m:e><m:e>{r('b')}</m:e></m:mr>"
        self.assertEqual(self._latex(f"<m:m>{row}{row}</m:m>"),
                         r"\begin{matrix} a & b \\ a & b \end{matrix}")
        self.assertEqual(self._latex(f"<m:d><m:dPr><m:begChr m:val='['/><m:endChr m:val=']'/></m:dPr><m:e>{r('x')}</m:e></m:d>"),
                         r"\left[x\right]")

    def test_unknown_elements_contribute_their_text(self):
        self.assertEqual(self._latex(f"<m:phant><m:e>{self._r('x')}</m:e></m:phant>"), "x")


class TestDocxThroughTheApi(BaseConverterTest):

    def test_convert_to_markdown_and_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            markdown = textconverter.convert(str(FIXTURE), "markdown", output_dir=tmp, image_dir_name="images")
            self.assertIn("# Elenchi:", markdown)
            self.assertIn("![Foto](images/image_1.jpeg)", markdown)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "images", "image_1.jpeg")))
            html = textconverter.convert(str(FIXTURE), "html")
            self.assertIn("data:image/jpeg;base64,", html)

    def test_text_conversion_needs_a_file(self):
        with self.assertRaisesRegex(ValueError, "needs a file"):
            textconverter.convert_text("x", "docx", "markdown")

    def test_format_is_inferred_and_documented(self):
        from textconverter.formats import infer_input_format, infer_input_format_from_media_type
        self.assertEqual(infer_input_format("a.DOCX"), "docx")
        self.assertEqual(infer_input_format_from_media_type(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), "docx")
