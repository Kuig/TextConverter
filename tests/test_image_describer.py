"""AI image classification and description, with every AI call mocked.

Usage: python -m unittest discover -s tests -p "test_image_describer.py"
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch

from _support import BaseConverterTest, FakeAi, setUpModule, tearDownModule, INPUT_DIR


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

        content = self.convert_fixture("Foto.jpg", "Foto_described.md", image_handling="describe")
        self.assertIn("This is a detailed mock description of the diagram.", content,
                      "Description text not found in output")
        # Verify both calls were made (classification + description)
        self.assertEqual(mock_call.call_count, 2, "Expected 2 AI calls (classify + describe)")
        mock_preload.assert_called()


FOTO = str(INPUT_DIR / "Foto.jpg")
HTML_TABLE = "<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>"


def _config(ocr_model: str = "ocr"):
    """Configuration with distinct model names, so calls can be told apart."""
    from textconverter.config import AppConfig
    cfg = AppConfig()
    cfg.ai.classification_model = "cls"
    cfg.ai.description_model = "desc"
    cfg.ai.ocr_model = ocr_model
    return cfg


def _doc_with_images(n: int):
    from textconverter.ast import Document, Image, Paragraph
    return Document(children=[Paragraph(children=[Image(src=FOTO, alt=f"img{i}")]) for i in range(n)])


class TestPhasedProcessing(BaseConverterTest):

    def _run(self, fake, doc, latex_auto=False, config=None):
        from textconverter.image_describer import process_images
        with patch("unified_ai_client.call_ai", side_effect=fake), \
             patch("unified_ai_client.preload_model") as preload:
            process_images(doc, "", latex_auto=latex_auto, config=config or _config())
        return [c.args[1] for c in preload.call_args_list]

    def test_calls_are_grouped_by_model(self):
        """All classifications first, then descriptions, then OCR: each model preloaded once."""
        fake = FakeAi(["photo_drawing_or_comic", "table", "map", "formula"],
                       {"desc": "A description.", "ocr": "x"})
        preloaded = self._run(fake, _doc_with_images(4))
        self.assertEqual([m for m, _ in fake.calls], ["cls"] * 4 + ["desc"] * 2 + ["ocr"] * 2)
        self.assertEqual(preloaded, ["cls", "desc", "ocr"])

    def test_ocr_categories_use_ocr_prompts(self):
        """Text, table, formula and document scans get the OCR model's task prompt."""
        fake = FakeAi(["text", "table", "formula", "document_scan"], {})
        self._run(fake, _doc_with_images(4))
        self.assertEqual([p for m, p in fake.calls if m == "ocr"],
                         ["Text Recognition:", "Table Recognition:",
                          "Formula Recognition:", "Text Recognition:"])

    def test_html_table_is_normalized_to_markdown(self):
        """An OCR answer with an HTML table is stored as a Markdown table."""
        from textconverter.ast import Image, walk
        fake = FakeAi(["table"], {"Table Recognition:": HTML_TABLE})
        doc = _doc_with_images(1)
        self._run(fake, doc)
        (img,) = [n for n in walk(doc) if isinstance(n, Image)]
        self.assertIn("| a | b |", img.description)
        self.assertNotIn("<table", img.description)

    def test_without_ocr_model_description_model_transcribes(self):
        """With no ocr_model, OCR categories go to the description model with the category prompt."""
        from textconverter.config import AppConfig
        fake = FakeAi(["formula"], {})
        preloaded = self._run(fake, _doc_with_images(1), config=_config(ocr_model=""))
        self.assertEqual(fake.calls[1], ("desc", AppConfig().ai.prompts["formula"]))
        self.assertEqual(preloaded, ["cls", "desc"])

    def test_latex_auto_replaces_transcribed_images(self):
        """auto_latex: a bare formula becomes an Equation, text a paragraph, a photo is not described."""
        from textconverter.ast import Equation, Paragraph, Text
        fake = FakeAi(["formula", "text", "photo_drawing_or_comic"],
                       {"Formula Recognition:": "E = mc^2", "Text Recognition:": "Some words."})
        doc = _doc_with_images(3)
        self._run(fake, doc, latex_auto=True)
        self.assertEqual(doc.children[0], Equation(code="E = mc^2", inline=False))
        self.assertEqual(doc.children[1], Paragraph(children=[Text(content="Some words.")]))
        self.assertIsNone(doc.children[2].children[0].description)
        self.assertNotIn("desc", [m for m, _ in fake.calls])

    def test_latex_auto_table_in_a_paragraph_becomes_a_table(self):
        """A table image amid text splits the paragraph: text, real Table, text."""
        from textconverter.ast import Document, Image, Paragraph, Table, Text
        fake = FakeAi(["table"], {"Table Recognition:": HTML_TABLE})
        doc = Document(children=[Paragraph(children=[
            Text(content="Before."), Image(src=FOTO), Text(content="After.")])])
        self._run(fake, doc, latex_auto=True)
        self.assertEqual([type(n) for n in doc.children], [Paragraph, Table, Paragraph])
        self.assertEqual(doc.children[2].children, [Text(content="After.")])

    def test_latex_auto_in_a_table_cell_stays_inline(self):
        """Where blocks cannot go, a transcribed formula becomes an inline Equation."""
        from textconverter.ast import Document, Equation, Image, Table, TableCell, TableRow
        fake = FakeAi(["formula"], {"Formula Recognition:": "$$a+b$$"})
        cell = TableCell(children=[Image(src=FOTO)])
        doc = Document(children=[Table(rows=[TableRow(cells=[cell])])])
        self._run(fake, doc, latex_auto=True)
        self.assertEqual(cell.children, [Equation(code="a+b", inline=True)])

    def test_latex_auto_without_client_keeps_images(self):
        """Without unified_ai_client, auto_latex degrades to plain references; describe raises."""
        from textconverter.image_describer import process_images
        with patch("textconverter.image_describer.ai_client_available", return_value=False):
            process_images(_doc_with_images(1), "", latex_auto=True, config=_config())
            with self.assertRaises(ImportError):
                process_images(_doc_with_images(1), "", config=_config())


class TestTranscribeImages(BaseConverterTest):

    def _transcribe(self, fake):
        from textconverter.image_describer import transcribe_images
        with patch("unified_ai_client.call_ai", side_effect=fake), \
             patch("unified_ai_client.preload_model"):
            return transcribe_images([FOTO, FOTO, FOTO], config=_config())

    def test_answers_become_ast_nodes_in_order(self):
        """HTML table → Table, formula → Equation, failed call → image reference."""
        from textconverter.ast import Equation, Paragraph, Table
        fake = FakeAi(["table", "formula", "map"],
                       {"Table Recognition:": HTML_TABLE, "Formula Recognition:": "$$a+b$$"})
        doc = self._transcribe(fake)
        self.assertIsInstance(doc.children[0], Table)
        self.assertEqual(doc.children[1], Equation(code="a+b", inline=False))
        self.assertIsInstance(doc.children[2], Paragraph)
        self.assertEqual(doc.children[2].children[0].src, FOTO)


class TestDescribedImagesInOutput(BaseConverterTest):
    """describe mode: the description reaches every output as real document content."""

    def _convert(self, to_format: str) -> str:
        import textconverter
        fake = FakeAi(["table"], {"Table Recognition:": HTML_TABLE})
        with patch("unified_ai_client.call_ai", side_effect=fake), \
             patch("unified_ai_client.preload_model"), \
             patch("textconverter.api.load_config", return_value=_config()):
            return textconverter.convert_text(f"Intro.\n\n![pic]({FOTO})\n", "markdown", to_format,
                                              textconverter.ConvertOptions(image_handling="describe"))

    def test_markdown_keeps_reference_markers_and_table(self):
        md = self._convert("markdown")
        self.assertIn("Image Reference:", md)
        self.assertIn("----- Start of picture description -----", md)
        self.assertIn("| a | b |", md)
        self.assertIn("----- End of picture description -----", md)

    def test_html_and_latex_get_a_real_table(self):
        """The described table used to be escaped text in HTML and LaTeX."""
        self.assertIn("<table>", self._convert("html"))
        self.assertIn(r"\begin{tabular}", self._convert("latex"))

    def test_json_keeps_the_described_image(self):
        import json
        doc = json.loads(self._convert("json"))
        images = [n for n in doc["children"][1]["children"] if n["type"] == "Image"]
        self.assertEqual(images[0]["category"], "table")
        self.assertIn("| a | b |", images[0]["description"])
