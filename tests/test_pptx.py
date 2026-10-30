"""PowerPoint (.pptx) input: the real fixture Test_slides.pptx and presentations built with python-pptx.

Usage: python -m unittest discover -s tests -p "test_pptx.py"
"""
from __future__ import annotations
import io
import os
import tempfile
from unittest.mock import patch

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.opc.package import Part
from pptx.opc.packuri import PackURI
from pptx.util import Inches

from textconverter.api import convert
from textconverter.ast import (
    BlockQuote, CodeBlock, Equation, Footnote, Heading, Image, Link, ListBlock, Paragraph, Table, Text, walk,
)
from textconverter.formats import infer_input_format, infer_input_format_from_media_type
from textconverter.parsers._pptx_xml import box_preamble, parse_box_preamble, Rect
from textconverter.parsers.pptx_parser import parse_pptx
from textconverter.renderers._common import plain_text
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR

FIXTURE = INPUT_DIR / "Test_slides.pptx"
_NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
       'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
       'xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main" '
       'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
       'xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" '
       'xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram"')


def _of(doc, cls):
    return [n for n in walk(doc) if isinstance(n, cls)]


def _headings(doc) -> list[tuple[int, str]]:
    return [(h.level, plain_text(h.children)) for h in _of(doc, Heading)]


def _png() -> io.BytesIO:
    from PIL import Image as PilImage
    buffer = io.BytesIO()
    PilImage.new("RGB", (4, 3), "red").save(buffer, "PNG")
    buffer.seek(0)
    return buffer


class PptxFixtureTest(BaseConverterTest):
    """Parses Test_slides.pptx once; the tests read the same AST."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        with patch("textconverter.parsers.pptx_parser.log_warning") as warn:
            cls.doc = parse_pptx(str(FIXTURE), output_dir=cls.tmp.name, image_dir_name="img")
        cls.warnings = [call.args[0] for call in warn.call_args_list]


class TestFixtureStructure(PptxFixtureTest):

    def test_metadata_comes_from_the_file_properties(self):
        self.assertEqual(plain_text(self.doc.title), "Titolo dai metadati")
        self.assertEqual(plain_text(self.doc.author), "Giorgio")

    def test_sections_are_level_one_and_slides_level_two(self):
        headings = _headings(self.doc)
        self.assertEqual([t for level, t in headings if level == 1],
                         ["Sezione predefinita", "Sezione 1", "Sezione 2"])
        self.assertEqual(sum(1 for level, _ in headings if level == 2), 37)
        self.assertEqual({level for level, _ in headings}, {1, 2})

    def test_slide_titles_are_one_line_and_not_bold(self):
        for heading in _of(self.doc, Heading):
            for node in heading.children:
                if isinstance(node, Text):
                    self.assertFalse(node.bold)
                    self.assertNotIn("\n", node.content)
        self.assertIn((2, "Giorgio Presti Researcher @ LIM"), _headings(self.doc))

    def test_speaker_notes_are_footnotes_on_the_heading(self):
        notes = [h for h in _of(self.doc, Heading) if any(isinstance(n, Footnote) for n in h.children)]
        self.assertEqual(len(notes), 2)
        self.assertIn("ambiente (environment)", plain_text(next(
            n for n in notes[0].children if isinstance(n, Footnote)).content))

    def test_secondary_text_boxes_are_quotes_with_their_frame(self):
        code = next(q for q in _of(self.doc, BlockQuote) if _of(q, CodeBlock))
        self.assertEqual(parse_box_preamble(plain_text(code.children[0].children)), (20, 62, 41, 15))
        self.assertIn("export LAVORO", _of(code, CodeBlock)[0].code)

    def test_lists_nest_and_tables_have_headers(self):
        self.assertTrue(any(_of(item, ListBlock) for lst in _of(self.doc, ListBlock) for item in lst.items))
        tables = _of(self.doc, Table)
        self.assertEqual(len(tables), 2)
        self.assertTrue(all(t.headers for t in tables))

    def test_pictures_are_written_once_per_content(self):
        sources = {i.src for i in _of(self.doc, Image)}
        self.assertTrue(sources)
        for src in sources:
            self.assertTrue(os.path.exists(os.path.join(self.tmp.name, src)), src)

    def test_one_warning_lists_what_was_dropped(self):
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("shape", self.warnings[0])


class TestGeneratedPresentations(BaseConverterTest):

    def setUp(self):
        super().setUp()
        self.prs = Presentation()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _parse(self, **kwargs):
        path = os.path.join(self.tmp.name, "deck.pptx")
        self.prs.save(path)
        with patch("textconverter.parsers.pptx_parser.log_warning") as warn:
            doc = parse_pptx(path, output_dir=self.tmp.name, image_dir_name="img", **kwargs)
        self.warnings = [call.args[0] for call in warn.call_args_list]
        return doc

    def _content_slide(self, title: str):
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[1])
        slide.shapes.title.text = title
        return slide

    def test_hashes_in_a_title_make_a_deeper_slide(self):
        self._content_slide("Plain")
        self._content_slide("# Deeper")
        self._content_slide("## Deepest")
        self.assertEqual(_headings(self._parse()), [(2, "Plain"), (3, "Deeper"), (4, "Deepest")])

    def test_bullets_levels_and_links(self):
        slide = self._content_slide("Lists")
        frame = slide.placeholders[1].text_frame
        frame.text = "first"
        frame.add_paragraph().text = "nested"
        frame.paragraphs[1].level = 1
        run = frame.add_paragraph().add_run()
        run.text = "site"
        run.hyperlink.address = "https://example.com"
        doc = self._parse()
        outer = _of(doc, ListBlock)[0]
        self.assertEqual(len(outer.items), 2)
        self.assertEqual(len(_of(outer.items[0], ListBlock)), 1)
        self.assertEqual(_of(doc, Link)[0].url, "https://example.com")

    def test_text_boxes_outside_a_placeholder_slide(self):
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        title = slide.shapes.add_textbox(Inches(1), Inches(0.2), Inches(8), Inches(0.8))
        title.text_frame.text = "Guessed title"
        body = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(2))
        body.text_frame.text = "The long main text of the slide"
        slide.shapes.add_textbox(Inches(8), Inches(5), Inches(1), Inches(1)).text_frame.text = "side"
        doc = self._parse()
        self.assertEqual(_headings(doc), [(2, "Guessed title")])
        quotes = _of(doc, BlockQuote)
        self.assertEqual(len(quotes), 1)
        self.assertIsNotNone(parse_box_preamble(plain_text(quotes[0].children[0].children)))
        self.assertIn("side", plain_text(quotes[0].children[1].children))

    def test_slide_without_a_title_has_an_empty_heading(self):
        self.prs.slides.add_slide(self.prs.slide_layouts[6]).shapes.add_textbox(
            Inches(1), Inches(4), Inches(2), Inches(1)).text_frame.text = "low"
        self.assertEqual(_headings(self._parse()), [(2, "")])

    def test_chart_becomes_a_table(self):
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[5])
        slide.shapes.title.text = "Data"
        data = CategoryChartData()
        data.categories = ["A", "B"]
        data.add_series("S1", (1, 2.5))
        chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, 0, 0, Inches(4), Inches(3), data).chart
        chart.has_title = True
        chart.chart_title.text_frame.text = "Sales"
        table = _of(self._parse(), Table)[0]
        self.assertEqual(plain_text(table.caption), "Sales")
        self.assertEqual([plain_text(c.children) for c in table.headers], ["", "S1"])
        self.assertEqual([[plain_text(c.children) for c in r.cells] for r in table.rows],
                         [["A", "1"], ["B", "2.5"]])

    def test_hidden_slides_are_kept(self):
        slide = self._content_slide("Hidden")
        slide.element.set("show", "0")
        self.assertEqual(_headings(self._parse()), [(2, "Hidden")])

    def test_slide_titled_like_its_section_merges_into_the_section(self):
        first = self._content_slide("Intro")
        first.placeholders[1].text_frame.text = "welcome"
        self._content_slide("Next")
        ids = [s.slide_id for s in self.prs.slides]
        sections = "".join(
            f'<p14:section name="{name}" id="{{00000000-0000-0000-0000-00000000000{i}}}"><p14:sldIdLst>'
            f'<p14:sldId id="{sid}"/></p14:sldIdLst></p14:section>'
            for i, (name, sid) in enumerate(zip(("Intro", "Part two"), ids)))
        ext = etree.fromstring(
            f'<p:extLst {_NS}><p:ext uri="{{521415D9-36F7-43E2-AB2F-B90AF26B5E84}}"><p14:sectionLst>'
            f'{sections}</p14:sectionLst></p:ext></p:extLst>')
        self.prs.element.append(ext)
        doc = self._parse()
        self.assertEqual(_headings(doc), [(1, "Intro"), (1, "Part two"), (2, "Next")])
        self.assertIsInstance(doc.children[1], ListBlock)

    def test_smartart_text_becomes_a_nested_list(self):
        slide = self._content_slide("Diagram")
        model = (f'<dgm:dataModel {_NS}><dgm:ptLst>'
                 '<dgm:pt modelId="0" type="doc"/>'
                 '<dgm:pt modelId="1"><dgm:t><a:p><a:r><a:t>Root</a:t></a:r></a:p></dgm:t></dgm:pt>'
                 '<dgm:pt modelId="2"><dgm:t><a:p><a:r><a:t>Leaf</a:t></a:r></a:p></dgm:t></dgm:pt>'
                 '</dgm:ptLst><dgm:cxnLst>'
                 '<dgm:cxn modelId="10" srcId="0" destId="1" srcOrd="0"/>'
                 '<dgm:cxn modelId="11" srcId="1" destId="2" srcOrd="0"/>'
                 '</dgm:cxnLst></dgm:dataModel>')
        part = Part(PackURI("/ppt/diagrams/data1.xml"),
                    "application/vnd.openxmlformats-officedocument.drawingml.diagramData+xml",
                    self.prs.part.package, model.encode())
        rel_id = slide.part.relate_to(part, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramData")
        frame = etree.fromstring(
            f'<p:graphicFrame {_NS}><p:nvGraphicFramePr><p:cNvPr id="9" name="Diagram"/><p:cNvGraphicFramePr/>'
            '<p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></p:xfrm>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/diagram">'
            f'<dgm:relIds r:dm="{rel_id}" r:lo="rId1" r:qs="rId1" r:cs="rId1"/></a:graphicData></a:graphic>'
            '</p:graphicFrame>')
        slide.shapes._spTree.append(frame)
        lists = _of(self._parse(), ListBlock)
        self.assertEqual(plain_text(lists[0].items[0].children[0].children), "Root")
        self.assertEqual(plain_text(lists[0].items[0].children[1].items[0].children[0].children), "Leaf")

    def test_equation_and_media_and_missing_pictures(self):
        slide = self._content_slide("Math")
        paragraph = slide.placeholders[1].text_frame.paragraphs[0]._p
        paragraph.append(etree.fromstring(
            f'<mc:AlternateContent {_NS}><mc:Choice Requires="a14"><a14:m><m:oMathPara><m:oMath>'
            '<m:r><m:t>x</m:t></m:r></m:oMath></m:oMathPara></a14:m></mc:Choice></mc:AlternateContent>'))
        picture = slide.shapes.add_picture(_png(), 0, 0)
        picture._element.nvPicPr.nvPr.append(etree.fromstring(
            f'<a:videoFile {_NS} r:link="rId99"/>'))
        doc = self._parse()
        self.assertEqual(_of(doc, Equation)[0].code, "x")
        self.assertEqual(len(_of(doc, Image)), 1)
        self.assertIn("video or audio", self.warnings[0])

    def test_images_can_be_left_out(self):
        self._content_slide("Pic").shapes.add_picture(_png(), 0, 0)
        self.assertEqual(_of(self._parse(write_images=False), Image), [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "img")))

    def test_not_a_presentation_is_a_value_error(self):
        path = os.path.join(self.tmp.name, "bad.pptx")
        with open(path, "wb") as f:
            f.write(b"not a zip")
        with self.assertRaisesRegex(ValueError, "Not a readable PowerPoint"):
            parse_pptx(path)


class TestBoxPreamble(BaseConverterTest):

    def test_the_preamble_round_trips(self):
        text = box_preamble(Rect(1219200, 685800, 3657600, 1371600), 12192000, 6858000)
        self.assertEqual(text, "Text box (x 10%, y 10%, w 30%, h 20%)")
        self.assertEqual(parse_box_preamble(text), (10, 10, 30, 20))
        self.assertIsNone(parse_box_preamble("An ordinary quote"))


class TestPptxThroughTheApi(BaseConverterTest):

    def test_markdown_from_the_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = convert(str(FIXTURE), "markdown", output_dir=tmp, image_dir_name="images")
        self.assertIn("# Sezione 1", text)
        self.assertIn("![", text)

    def test_formats_are_inferred(self):
        self.assertEqual(infer_input_format("a.PPTX"), "pptx")
        self.assertEqual(infer_input_format_from_media_type(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"), "pptx")
