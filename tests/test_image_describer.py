"""AI image classification and description, with every AI call mocked.

Usage: python -m unittest discover -s tests -p "test_image_describer.py"
"""
from __future__ import annotations
import json
import shutil
from unittest.mock import MagicMock, patch

from _support import BaseConverterTest, FakeAi, setUpModule, tearDownModule, INPUT_DIR, OUTPUT_DIR


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


def _copies(n: int) -> list[str]:
    """Paths of ``n`` distinct image files (a file shown twice is processed once)."""
    paths = []
    for i in range(n):
        path = OUTPUT_DIR / f"describer_{i}.jpg"
        OUTPUT_DIR.mkdir(exist_ok=True)
        shutil.copyfile(FOTO, path)
        paths.append(str(path))
    return paths


def _doc_with_images(n: int):
    from textconverter.ast import Document, Image, Paragraph
    return Document(children=[Paragraph(children=[Image(src=path, alt=f"img{i}")])
                              for i, path in enumerate(_copies(n))])


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
        # GLM-OCR writes every row with <td>: the first row is the header
        self.assertIn("| a | b |\n|---|---|\n| 1 | 2 |", img.description)
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

    def test_one_file_is_processed_once(self):
        """Four images of one file (relative and absolute paths): one call per phase, shared result."""
        import os
        from textconverter.ast import Document, Image, Paragraph, walk
        path = _copies(1)[0]
        relative = os.path.relpath(path, str(OUTPUT_DIR.parent))
        doc = Document(children=[Paragraph(children=[Image(src=src) for src in (path, path, relative, path)])])
        fake = FakeAi(["photo_drawing_or_comic"], {"desc": "A description."})
        from textconverter.image_describer import process_images
        with patch("unified_ai_client.call_ai", side_effect=fake), patch("unified_ai_client.preload_model"):
            process_images(doc, str(OUTPUT_DIR.parent), config=_config())
        self.assertEqual([m for m, _ in fake.calls], ["cls", "desc"])
        self.assertEqual({(n.category, n.description) for n in walk(doc) if isinstance(n, Image)},
                         {("photo_drawing_or_comic", "A description.")})

    def test_latex_auto_without_client_keeps_images(self):
        """Without unified_ai_client, auto_latex degrades to plain references; describe raises."""
        from textconverter.image_describer import process_images
        with patch("textconverter.image_describer.ai_client_available", return_value=False):
            process_images(_doc_with_images(1), "", latex_auto=True, config=_config())
            with self.assertRaises(ImportError):
                process_images(_doc_with_images(1), "", config=_config())


ARTICLE = str(INPUT_DIR / "Article_image.png")


def _region_config():
    cfg = _config()
    cfg.ai.region_model = "region"
    return cfg


def _labels(path: str = ARTICLE) -> str:
    """A model's answer for a page: dense blocks are photos, the rest text."""
    from textconverter.regions import find_blocks
    return json.dumps({str(number): "photo_drawing_or_comic" if block.dense else "text"
                       for number, block in enumerate(find_blocks(path), 1)})


class TestRegions(BaseConverterTest):

    def setUp(self):
        super().setUp()
        self.saved: list[bytes] = []

    def _save(self, data: bytes) -> str:
        self.saved.append(data)
        return f"images/crop_{len(self.saved)}.png"

    def _doc(self, *paths):
        from textconverter.ast import Document, Image, Paragraph
        return Document(children=[Paragraph(children=[Image(src=path, alt="page")]) for path in paths or (ARTICLE,)])

    def _run(self, fake, doc=None, config=None, save_crop="default", **kwargs):
        from textconverter.image_describer import process_images
        doc = doc or self._doc()
        self.call = MagicMock(side_effect=fake)
        with patch("unified_ai_client.call_ai", self.call), patch("unified_ai_client.preload_model") as preload:
            process_images(doc, "", config=config or _region_config(),
                           save_crop=self._save if save_crop == "default" else save_crop, **kwargs)
        self.preloaded = [c.args[1] for c in preload.call_args_list]
        return doc

    def _fake(self, categories=("document_scan",), region=None, ocr="Some text.", desc="A photo."):
        return FakeAi(list(categories), {"region": _labels() if region is None else region, "desc": desc, "ocr": ocr})

    def test_phases_stay_grouped_by_model(self):
        """Classification, then labels, then descriptions and OCR on the regions: each model loads once."""
        fake = self._fake()
        self._run(fake)
        models = [m for m, _ in fake.calls]
        self.assertEqual(models[:2], ["cls", "region"])
        self.assertEqual(models, sorted(models, key=["cls", "region", "desc", "ocr"].index))
        self.assertEqual(self.preloaded, ["cls", "region", "desc", "ocr"])

    def test_labelling_call_has_the_tile_count_and_no_thinking(self):
        from textconverter.regions import find_blocks
        self._run(self._fake())
        (call,) = [c for c in self.call.call_args_list if c.kwargs["model"] == "region"]
        self.assertIn(f"exactly {len(find_blocks(ARTICLE))} separate tiles", call.kwargs["prompt"])
        self.assertIs(call.kwargs["thinking"], False)
        self.assertEqual(call.kwargs["max_tokens"], 1500)
        self.assertTrue(call.kwargs["format_json"])

    def test_page_is_replaced_by_its_regions_in_reading_order(self):
        from textconverter.ast import Image, Paragraph, Text
        doc = self._run(self._fake())
        kinds = [type(n.children[0]).__name__ for n in doc.children]
        self.assertEqual(kinds, ["Text", "Image", "Text", "Image"])
        self.assertEqual(doc.children[0], Paragraph(children=[Text(content="Some text.")]))
        photo = doc.children[1].children[0]
        self.assertIsInstance(photo, Image)
        self.assertEqual((photo.src, photo.category, photo.description, photo.alt),
                         ("images/crop_1.png", "photo_drawing_or_comic", "A photo.", "page"))

    def test_only_what_is_not_transcribed_is_stored(self):
        self._run(self._fake())
        self.assertEqual(len(self.saved), 2)
        self.assertTrue(all(data.startswith(b"\x89PNG") for data in self.saved))

    def test_text_runs_are_read_at_once(self):
        """Consecutive text blocks take one OCR call, not one each."""
        fake = self._fake()
        self._run(fake)
        self.assertEqual(len([m for m, _ in fake.calls if m == "ocr"]), 2)

    def test_failed_transcription_keeps_the_crop(self):
        """Text that could not be read stays in the document as an image."""
        doc = self._run(self._fake(ocr=""))
        self.assertEqual(len(self.saved), 4)
        self.assertEqual(doc.children[0].children[0].category, "text")

    def test_without_storage_a_description_stays_as_text(self):
        from textconverter.ast import Text
        doc = self._run(self._fake(), save_crop=None)
        self.assertEqual(doc.children[1].children, [Text(content="A photo.")])

    def test_no_region_model_means_no_regions(self):
        config = _region_config()
        config.ai.region_model = ""
        fake = self._fake()
        doc = self._run(fake, config=config)
        self.assertEqual([m for m, _ in fake.calls], ["cls", "ocr"])
        self.assertEqual(doc.children[0].children[0].src, ARTICLE)

    def test_other_categories_are_not_looked_at(self):
        fake = self._fake(categories=["infographic_or_depliant"])
        self._run(fake)
        self.assertEqual([m for m, _ in fake.calls], ["cls", "desc"])
        self.assertNotIn("region", self.preloaded)

    def test_plain_text_page_loads_no_region_model(self):
        """Pillow alone can tell, so a page of text costs no call and no model load."""
        import pymupdf
        path = str(OUTPUT_DIR / "regions_text_page.png")
        OUTPUT_DIR.mkdir(exist_ok=True)
        with pymupdf.open(INPUT_DIR / "Journal PDF.pdf") as pdf:
            pdf[0].get_pixmap(dpi=200).save(path)
        fake = self._fake()
        self._run(fake, doc=self._doc(path))
        self.assertEqual([m for m, _ in fake.calls], ["cls", "ocr"])
        self.assertNotIn("region", self.preloaded)

    def test_unusable_labels_leave_the_page_as_it_was(self):
        """A partial or broken answer gives the behaviour with no regions."""
        for answer in ("not json", '{"1": "text"}'):
            fake = self._fake(region=answer)
            doc = self._run(fake)
            self.assertEqual([m for m, _ in fake.calls], ["cls", "region", "ocr"])
            self.assertEqual(doc.children[0].children[0].description, "Some text.")

    def test_one_kind_of_content_leaves_the_page_whole(self):
        from textconverter.regions import find_blocks
        labels = json.dumps({str(n): "text" for n in range(1, len(find_blocks(ARTICLE)) + 1)})
        fake = self._fake(region=labels)
        doc = self._run(fake)
        self.assertEqual([m for m, _ in fake.calls], ["cls", "region", "ocr"])
        self.assertEqual(doc.children[0].children[0].src, ARTICLE)

    def test_failed_labelling_call_leaves_the_page_whole(self):
        doc = self._run(self._fake(region=""))
        self.assertEqual(doc.children[0].children[0].category, "document_scan")

    def test_each_copy_of_a_file_gets_the_regions(self):
        """A file shown twice is processed once; both places get their own nodes."""
        fake = self._fake()
        doc = self._run(fake, doc=self._doc(ARTICLE, ARTICLE))
        self.assertEqual(len(doc.children), 8)
        self.assertEqual(len([m for m, _ in fake.calls if m == "region"]), 1)
        self.assertEqual(doc.children[1], doc.children[5])
        self.assertIsNot(doc.children[1].children[0], doc.children[5].children[0])

    def test_latex_auto_keeps_figures_as_plain_images(self):
        from textconverter.ast import Image
        fake = self._fake()
        doc = self._run(fake, latex_auto=True)
        self.assertNotIn("desc", [m for m, _ in fake.calls])
        self.assertEqual(len(self.saved), 2)
        photo = doc.children[1].children[0]
        self.assertIsInstance(photo, Image)
        self.assertIsNone(photo.description)

    def test_render_metadata_reaches_the_regions(self):
        from textconverter.ast import Document, Image, Paragraph
        doc = Document(children=[Paragraph(children=[Image(src=ARTICLE, render_metadata=False)])])
        self._run(self._fake(), doc=doc)
        self.assertFalse(doc.children[1].children[0].render_metadata)

    def test_in_a_table_cell_the_image_stays_and_regions_follow(self):
        from textconverter.ast import Document, Image, Table, TableCell, TableRow
        cell = TableCell(children=[Image(src=ARTICLE)])
        doc = Document(children=[Table(rows=[TableRow(cells=[cell])])])
        self._run(self._fake(), doc=doc)
        self.assertEqual(cell.children[0].src, ARTICLE)
        self.assertEqual(len(doc.children), 5)

    def test_regions_lower_to_text_in_every_format(self):
        """A stored crop is an ordinary described image for the renderers."""
        from textconverter.images import lower_image_descriptions
        from textconverter.renderers.markdown_renderer import render_markdown
        doc = self._run(self._fake())
        lower_image_descriptions(doc)
        markdown = render_markdown(doc)
        self.assertLess(markdown.index("Some text."), markdown.index("images/crop_1.png"))
        self.assertIn("A photo.", markdown)

    def test_transcribe_images_uses_the_regions(self):
        from textconverter.image_describer import transcribe_images
        fake = self._fake()
        with patch("unified_ai_client.call_ai", side_effect=fake), patch("unified_ai_client.preload_model"):
            doc = transcribe_images([ARTICLE], config=_region_config(), save_crop=self._save)
        self.assertEqual([type(n.children[0]).__name__ for n in doc.children], ["Text", "Image", "Text", "Image"])

    def test_description_and_ocr_have_a_token_limit(self):
        from textconverter.config import AppConfig
        ai = AppConfig().ai
        self._run(self._fake())
        limits = {c.kwargs["model"]: c.kwargs["max_tokens"] for c in self.call.call_args_list}
        self.assertEqual((limits["desc"], limits["ocr"]), (ai.description_max_tokens, ai.ocr_max_tokens))


class TestTranscribeImages(BaseConverterTest):

    def setUp(self):
        super().setUp()
        self.paths = _copies(3)

    def _transcribe(self, fake):
        from textconverter.image_describer import transcribe_images
        with patch("unified_ai_client.call_ai", side_effect=fake), \
             patch("unified_ai_client.preload_model"):
            return transcribe_images(self.paths, config=_config())

    def test_answers_become_ast_nodes_in_order(self):
        """HTML table → Table, formula → Equation, failed call → image reference."""
        from textconverter.ast import Equation, Paragraph, Table
        fake = FakeAi(["table", "formula", "map"],
                       {"Table Recognition:": HTML_TABLE, "Formula Recognition:": "$$a+b$$"})
        doc = self._transcribe(fake)
        self.assertIsInstance(doc.children[0], Table)
        self.assertEqual(doc.children[1], Equation(code="a+b", inline=False))
        self.assertIsInstance(doc.children[2], Paragraph)
        self.assertEqual(doc.children[2].children[0].src, self.paths[2])


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

    def _lowered(self, *blocks):
        from textconverter.ast import Document
        from textconverter.images import lower_image_descriptions
        doc = Document(children=list(blocks))
        lower_image_descriptions(doc)
        return doc

    @staticmethod
    def _described():
        from textconverter.ast import Image, Text
        return Image(src="pic.png", description="A *red* car.", category="photo_drawing_or_comic",
                     caption=[Text(content="The car")], label="fig:car")

    def test_described_image_in_a_link_keeps_its_place(self):
        """The whole description used to be crammed into the link text."""
        from textconverter.ast import Link, Paragraph, Text
        link = Link(url="https://e.org", content=[self._described()])
        doc = self._lowered(Paragraph(children=[Text(content="See "), link, Text(content=" here.")]))
        first, header = doc.children[:2]
        self.assertEqual(first.children[1].content,
                         [Text(content="[Image Reference: pic.png - Class: photo_drawing_or_comic]", bold=True)])
        self.assertEqual(first.children[2], Text(content=" here."))
        self.assertIn("Start of picture description", header.children[-1].content)
        self.assertEqual(doc.children[-1].children[:2], [Text(content="Figure: "), Text(content="The car")])

    def test_described_image_in_a_table_cell_follows_the_table(self):
        from textconverter.ast import Paragraph, Table, TableCell, TableRow, Text
        cell = TableCell(children=[self._described()])
        doc = self._lowered(Table(rows=[TableRow(cells=[cell])]), Paragraph(children=[Text(content="After.")]))
        self.assertIsInstance(doc.children[0], Table)
        self.assertEqual(cell.children[0].content[:16], "[Image Reference")
        self.assertEqual(doc.children[-1].children, [Text(content="After.")])
        self.assertIn("red", "".join(n.content for p in doc.children[1:-1] for n in getattr(p, "children", [])
                                     if isinstance(n, Text)))

    def test_json_keeps_the_described_image(self):
        import json
        doc = json.loads(self._convert("json"))
        images = [n for n in doc["children"][1]["children"] if n["type"] == "Image"]
        self.assertEqual(images[0]["category"], "table")
        self.assertIn("| a | b |", images[0]["description"])
