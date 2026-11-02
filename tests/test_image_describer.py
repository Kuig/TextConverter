"""AI image classification and description, with every AI call mocked.

Usage: python -m unittest discover -s tests -p "test_image_describer.py"
"""
from __future__ import annotations
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image as PilImage

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


def _no_crop(data: bytes) -> str:
    raise AssertionError("no crop expected")


def _copies(n: int) -> list[str]:
    """Paths of ``n`` image files of distinct content (the same content is processed once)."""
    paths = []
    OUTPUT_DIR.mkdir(exist_ok=True)
    for i in range(n):
        path = OUTPUT_DIR / f"describer_{i}.jpg"
        path.write_bytes(Path(FOTO).read_bytes() + bytes([i]))
        paths.append(str(path))
    return paths


def _doc_with_images(n: int):
    from textconverter.ast import Document, Image, Paragraph
    return Document(children=[Paragraph(children=[Image(src=path, alt=f"img{i}")])
                              for i, path in enumerate(_copies(n))])


class TestPhasedProcessing(BaseConverterTest):

    def _run(self, fake, doc, handling="describe", config=None):
        from textconverter.image_describer import process_images
        with patch("unified_ai_client.call_ai", side_effect=fake), \
             patch("unified_ai_client.preload_model") as preload:
            process_images(doc, "", handling=handling, config=config or _config(), save_crop=_no_crop)
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
        fake = FakeAi(["text", "table", "formula", "document_scan"], {"ocr": "x"})
        self._run(fake, _doc_with_images(4))
        self.assertEqual([p for m, p in fake.calls if m == "ocr"],
                         ["Text Recognition:", "Table Recognition:",
                          "Formula Recognition:", "Text Recognition:"])

    def test_html_table_is_normalized_to_markdown(self):
        """An OCR answer with an HTML table is stored as a Markdown table."""
        from textconverter.ast import Image, walk
        fake = FakeAi(["table"], {"Table Recognition:": HTML_TABLE})
        doc = _doc_with_images(1)
        self._run(fake, doc, handling="append")
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
        self._run(fake, doc, handling="transcribe")
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
        self._run(fake, doc, handling="transcribe")
        self.assertEqual([type(n) for n in doc.children], [Paragraph, Table, Paragraph])
        self.assertEqual(doc.children[2].children, [Text(content="After.")])

    def test_latex_auto_in_a_table_cell_stays_inline(self):
        """Where blocks cannot go, a transcribed formula becomes an inline Equation."""
        from textconverter.ast import Document, Equation, Image, Table, TableCell, TableRow
        fake = FakeAi(["formula"], {"Formula Recognition:": "$$a+b$$"})
        cell = TableCell(children=[Image(src=FOTO)])
        doc = Document(children=[Table(rows=[TableRow(cells=[cell])])])
        self._run(fake, doc, handling="transcribe")
        self.assertEqual(cell.children, [Equation(code="a+b", inline=True)])

    def test_one_content_in_two_files_is_processed_once(self):
        from textconverter.ast import Document, Image, Paragraph
        first, second = OUTPUT_DIR / "same_a.jpg", OUTPUT_DIR / "same_b.jpg"
        for path in (first, second):
            shutil.copyfile(FOTO, path)
        images = [Image(src=str(first)), Image(src=str(second))]
        fake = FakeAi(["map"], {"desc": "A map."})
        self._run(fake, Document(children=[Paragraph(children=[image]) for image in images]))
        self.assertEqual([m for m, _ in fake.calls], ["cls", "desc"])
        self.assertEqual([(image.category, image.description) for image in images], [("map", "A map.")] * 2)

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
            process_images(doc, str(OUTPUT_DIR.parent), handling="describe", config=_config(), save_crop=_no_crop)
        self.assertEqual([m for m, _ in fake.calls], ["cls", "desc"])
        self.assertEqual({(n.category, n.description) for n in walk(doc) if isinstance(n, Image)},
                         {("photo_drawing_or_comic", "A description.")})

    def test_without_client_only_an_implicit_analysis_keeps_the_images(self):
        """Without unified_ai_client an analysis nobody asked for leaves plain references."""
        from textconverter.image_describer import process_images
        with patch("textconverter.image_describer.ai_client_available", return_value=False):
            process_images(_doc_with_images(1), "", handling="transcribe", required=False, config=_config(),
                           save_crop=_no_crop)
            with self.assertRaises(ImportError):
                process_images(_doc_with_images(1), "", handling="describe", config=_config(), save_crop=_no_crop)


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

    def _run(self, fake, doc=None, config=None, handling="describe"):
        from textconverter.image_describer import process_images
        doc = doc or self._doc()
        self.call = MagicMock(side_effect=fake)
        with patch("unified_ai_client.call_ai", self.call), patch("unified_ai_client.preload_model") as preload:
            process_images(doc, "", handling=handling, config=config or _region_config(), save_crop=self._save)
        self.preloaded = [c.args[1] for c in preload.call_args_list]
        return doc

    def _fake(self, categories=("document_scan",), region=None, ocr="Some text.", desc="A photo."):
        return FakeAi(list(categories), {"region": _labels() if region is None else region, "desc": desc, "ocr": ocr})

    def test_phases_stay_grouped_by_model(self):
        """Classification, labels, then OCR and descriptions on the regions: the text is the figures' context."""
        fake = self._fake()
        self._run(fake)
        models = [m for m, _ in fake.calls]
        self.assertEqual(models[:2], ["cls", "region"])
        self.assertEqual(models, sorted(models, key=["cls", "region", "ocr", "desc"].index))
        self.assertEqual(self.preloaded, ["cls", "region", "ocr", "desc"])

    def test_model_coming_back_is_preloaded_again(self):
        """A call would load it without ``context_size``; a model already in use is left alone."""
        cfg = _region_config()
        cfg.ai.classification_model = "desc"
        self._run(FakeAi(["document_scan"], {"region": _labels(), "ocr": "Some text."}), config=cfg)
        self.assertEqual(self.preloaded, ["desc", "region", "ocr", "desc"])
        cfg.ai.classification_model, cfg.ai.region_model = "cls", "desc"
        self._run(FakeAi(["document_scan"], {"desc": _labels(), "ocr": "Some text."}), config=cfg)
        self.assertEqual(self.preloaded, ["cls", "desc", "ocr", "desc"])
        cfg.ai.description_context = 0
        self._run(FakeAi(["document_scan"], {"desc": _labels(), "ocr": "Some text."}), config=cfg)
        self.assertEqual(self.preloaded, ["cls", "desc", "ocr"])

    def _reading(self, *texts):
        """A fake model that transcribes the crops into ``texts``, in order."""
        fake, answers = self._fake(), iter(texts)
        return lambda **kwargs: MagicMock(text=next(answers)) if kwargs["model"] == "ocr" else fake(**kwargs)

    def _description_prompts(self):
        return [c.kwargs["prompt"] for c in self.call.call_args_list if c.kwargs["model"] == "desc"]

    def test_figures_get_the_text_around_them(self):
        self._run(self._reading("The Title\nFirst text.", "Second text."))
        first, second = self._description_prompts()
        self.assertIn("Title: The Title\nText before: The Title First text.\nText after: Second text.", first)
        self.assertIn("Text before: The Title First text. Second text.", second)
        self.assertNotIn("Text after", second)

    def test_image_source_gets_the_text_of_its_page(self):
        self._run(self._reading("First text.", "Second text."))
        self.assertIn("Text after: Second text.", self._description_prompts()[0])

    def test_failed_transcription_leaves_the_prompt_alone(self):
        self._run(self._fake(ocr=""))
        photo_prompt = _region_config().ai.prompts["photo_drawing_or_comic"]
        self.assertEqual(self._description_prompts(), [photo_prompt, photo_prompt])

    def test_no_context_keeps_the_prompts_and_the_phases(self):
        cfg = _region_config()
        cfg.ai.description_context = 0
        fake = self._fake()
        self._run(fake, config=cfg)
        models = [m for m, _ in fake.calls]
        self.assertEqual(models, sorted(models, key=["cls", "region", "desc", "ocr"].index))
        self.assertEqual(set(self._description_prompts()), {cfg.ai.prompts["photo_drawing_or_comic"]})

    def test_figures_in_a_row_see_the_text_and_not_each_other(self):
        from textconverter.ast import Image
        from textconverter.image_describer import Split, _region_contexts
        photo = Image(src="", category="photo_drawing_or_comic", description="A photo.")
        diagram = Image(src="", category="diagram")
        regions = [Image(src="", category="text", description="Opening line\nBody."), photo, diagram,
                   Image(src="", category="table", description="<table></table>"),
                   Image(src="", category="text", description="x" * 100)]
        contexts = _region_contexts(Split(regions, []), 12)
        self.assertEqual(contexts[id(photo)], contexts[id(diagram)])
        self.assertEqual(contexts[id(photo)], f"Title: Opening line\nText before: g line Body.\nText after: {'x' * 12}")

    def test_page_title_is_cut(self):
        from textconverter.ast import Image
        from textconverter.image_describer import Split, _PAGE_TITLE_LENGTH, _region_contexts
        photo = Image(src="", category="diagram")
        contexts = _region_contexts(Split([photo, Image(src="", category="text", description="y" * 500)], []), 10)
        self.assertIn(f"Title: {'y' * _PAGE_TITLE_LENGTH}\n", contexts[id(photo)])

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

    def test_only_transcribed_crops_have_a_margin(self):
        """A margin lets a line of text into a figure, and the model reads it as part of the picture."""
        from textconverter.image_describer import _REGION_PADDING
        from textconverter.regions import Crop, crop_image
        with patch("textconverter.image_describer.crop_image", wraps=crop_image) as spy:
            self._run(self._fake())
        paddings = {c.args[1].box.label: c.args[2] for c in spy.call_args_list}
        self.assertEqual(paddings, {"text": _REGION_PADDING, "photo_drawing_or_comic": 0})
        figures = [c.args[1].box for c in spy.call_args_list if c.args[2] == 0]
        self.assertEqual(self.saved, [crop_image(ARTICLE, Crop(box), 0) for box in figures])

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

    def test_no_region_model_means_no_regions(self):
        config = _region_config()
        config.ai.region_model = ""
        fake = self._fake()
        doc = self._run(fake, config=config, handling="append")
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
            doc = self._run(fake, handling="append")
            self.assertEqual([m for m, _ in fake.calls], ["cls", "region", "ocr"])
            self.assertEqual(doc.children[0].children[0].description, "Some text.")

    def test_one_kind_of_content_leaves_the_page_whole(self):
        from textconverter.regions import find_blocks
        labels = json.dumps({str(n): "text" for n in range(1, len(find_blocks(ARTICLE)) + 1)})
        fake = self._fake(region=labels)
        doc = self._run(fake, handling="append")
        self.assertEqual([m for m, _ in fake.calls], ["cls", "region", "ocr"])
        self.assertEqual(doc.children[0].children[0].src, ARTICLE)

    def test_failed_labelling_call_leaves_the_page_whole(self):
        doc = self._run(self._fake(region=""), handling="append")
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
        doc = self._run(fake, handling="transcribe")
        self.assertNotIn("desc", [m for m, _ in fake.calls])
        self.assertEqual(len(self.saved), 2)
        photo = doc.children[1].children[0]
        self.assertIsInstance(photo, Image)
        self.assertIsNone(photo.description)

    def test_split_keeps_every_region_as_an_image(self):
        from textconverter.ast import Image, walk
        fake = self._fake()
        doc = self._run(fake, handling="split")
        self.assertEqual({m for m, _ in fake.calls}, {"cls", "region"})
        images = [n for n in walk(doc) if isinstance(n, Image)]
        self.assertEqual(len(images), len(self.saved))
        self.assertTrue(all(image.src.startswith("images/") and not image.description for image in images))

    def test_append_keeps_every_crop_with_its_text(self):
        from textconverter.ast import Image, walk
        doc = self._run(self._fake(), handling="append")
        images = [n for n in walk(doc) if isinstance(n, Image)]
        self.assertEqual(len(images), len(self.saved))
        self.assertEqual({image.description for image in images}, {"Some text.", "A photo."})

    def test_replace_stores_no_crop(self):
        from textconverter.ast import Image, walk
        doc = self._run(self._fake(), handling="replace")
        self.assertEqual(self.saved, [])
        self.assertFalse(any(isinstance(n, Image) for n in walk(doc)))

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

    def test_description_and_ocr_have_a_token_limit(self):
        from textconverter.config import AppConfig
        ai = AppConfig().ai
        self._run(self._fake())
        limits = {c.kwargs["model"]: c.kwargs["max_tokens"] for c in self.call.call_args_list}
        self.assertEqual((limits["desc"], limits["ocr"]), (ai.description_max_tokens, ai.ocr_max_tokens))


class TestRegionsInOutput(BaseConverterTest):
    """A split image, through a whole conversion: files, paths and the overlay."""

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)

    def _fake(self, ocr="Some text."):
        return FakeAi(["document_scan"], {"region": _labels(), "desc": "A photo.", "ocr": ocr})

    def _save(self, source=ARTICLE, name="out.md", fake=None, config=None, image_handling="describe", **options):
        import textconverter
        options["image_handling"] = image_handling
        output = self.dir / name
        with patch("unified_ai_client.call_ai", side_effect=fake or self._fake()), \
             patch("unified_ai_client.preload_model"):
            written = textconverter.save_to_file(source, str(output), textconverter.ConvertOptions(**options),
                                                 config=config or _region_config())
        return output, written

    def _images(self):
        folder = self.dir / "out_images"
        return sorted(p.name for p in folder.iterdir()) if folder.exists() else []

    def test_markdown_links_the_stored_figures(self):
        output, _ = self._save()
        self.assertEqual(self._images(), ["image_1.png", "image_2.png"])
        text = output.read_text(encoding="utf-8")
        self.assertIn("out_images/image_1.png", text)
        self.assertNotIn(str(self.dir), text)
        self.assertIn("A photo.", text)
        self.assertIn("Some text.", text)

    def test_latex_links_the_stored_figures(self):
        output, _ = self._save(name="out.tex")
        self.assertIn(r"\includegraphics{out_images/image_1.png}", output.read_text(encoding="utf-8"))
        self.assertEqual(len(self._images()), 2)

    def test_json_holds_the_figures_with_relative_paths(self):
        output, _ = self._save(name="out.json", image_output="link")
        text = output.read_text(encoding="utf-8")
        self.assertIn('"out_images/image_1.png"', text)
        self.assertIn('"photo_drawing_or_comic"', text)

    def test_html_embeds_the_figures_and_leaves_no_folder(self):
        """An embedded figure is shown, not quoted as a reference holding the whole file."""
        output, _ = self._save(name="out.html")
        text = output.read_text(encoding="utf-8")
        self.assertIn('src="data:image/png;base64,', text)
        self.assertIn("A photo.", text)
        self.assertEqual(self._images(), [])

    def test_replace_writes_no_file_and_keeps_the_descriptions(self):
        output, _ = self._save(image_handling="replace")
        self.assertEqual(self._images(), [])
        self.assertIn("A photo.", output.read_text(encoding="utf-8"))

    def test_failed_ocr_keeps_the_text_as_images(self):
        self._save(fake=self._fake(ocr=""))
        self.assertEqual(len(self._images()), 4)

    def test_failed_image_still_points_to_its_source(self):
        """With nothing transcribed the document refers to the source, from where the output is."""
        import os
        config = _region_config()
        config.ai.region_model = ""
        output, _ = self._save(source=os.path.relpath(ARTICLE), fake=FakeAi(["document_scan"], {}), config=config)
        text = output.read_text(encoding="utf-8")
        target = text[text.index("](") + 2:text.index(")")].strip("<>")
        self.assertTrue(os.path.samefile(self.dir / target, ARTICLE), text)

    def test_document_images_are_stored_next_to_the_output_too(self):
        import shutil
        shutil.copyfile(ARTICLE, self.dir / "page.png")
        source = self.dir / "doc.md"
        source.write_text("![page](page.png)\n", encoding="utf-8")
        output, written = self._save(source=str(source), image_handling="describe")
        self.assertEqual(len(self._images()), 2)
        self.assertEqual(written, [str(output)])
        self.assertIn("out_images/image_1.png", output.read_text(encoding="utf-8"))

    def test_raster_pdf_page_stores_its_figures(self):
        import pymupdf
        pdf_path, page_path = self.dir / "page.pdf", str(self.dir / "page.png")
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_image(page.rect, filename=ARTICLE)
            pdf.save(pdf_path)
            page.get_pixmap(dpi=200).save(page_path)
        fake = FakeAi(["document_scan"], {"region": _labels(page_path), "desc": "A photo.", "ocr": "Some text."})
        output, _ = self._save(source=str(pdf_path), fake=fake, pdf_mode="raster")
        self.assertGreaterEqual(len(self._images()), 1)
        self.assertIn("out_images/image_1.png", output.read_text(encoding="utf-8"))

    def test_image_source_leaves_the_overlay_next_to_the_output(self):
        for name in ("out.md", "out.html", "out.docx"):
            with self.subTest(name):
                output, written = self._save(name=name)
                overlay = self.dir / "out_regions.png"
                self.assertEqual(written, [str(output), str(overlay)])
                with PilImage.open(overlay) as image, PilImage.open(ARTICLE) as source:
                    self.assertEqual(image.size, source.size)
                overlay.unlink()

    def test_overlay_of_an_image_that_was_not_split_shows_its_category(self):
        fake = FakeAi(["photo_drawing_or_comic"], {"desc": "A photo."})
        _, written = self._save(source=FOTO, fake=fake)
        self.assertEqual(len(written), 2)

    def test_a_file_with_the_overlay_name_is_left_alone_by_other_sources(self):
        overlay = self.dir / "out_regions.png"
        overlay.write_bytes(b"mine")
        source = self.dir / "doc.md"
        source.write_text("Text.\n", encoding="utf-8")
        output, written = self._save(source=str(source))
        self.assertEqual(written, [str(output)])
        self.assertEqual(overlay.read_bytes(), b"mine")

    def test_convert_writes_no_overlay(self):
        import textconverter
        with patch("unified_ai_client.call_ai", side_effect=self._fake()), patch("unified_ai_client.preload_model"):
            textconverter.convert(ARTICLE, "markdown", output_dir=str(self.dir), config=_region_config())
        self.assertFalse(list(self.dir.glob("*_regions.png")))


class TestDocumentContext(BaseConverterTest):

    def setUp(self):
        super().setUp()
        self.path = _copies(1)[0]

    def _prompts(self, doc, categories=("photo_drawing_or_comic",), config=None):
        """The description prompts for ``doc``; other models are recorded in ``self.models``."""
        from textconverter.image_describer import process_images
        fake = FakeAi(list(categories), {"desc": "A description.", "ocr": "Some text."})
        with patch("unified_ai_client.call_ai", side_effect=fake), patch("unified_ai_client.preload_model"):
            process_images(doc, "", handling="describe", config=config or _config(), save_crop=_no_crop)
        self.models = [model for model, _ in fake.calls]
        return [prompt for model, prompt in fake.calls if model == "desc"]

    def _report(self, **image):
        from textconverter.ast import Document, Heading, Image, Paragraph, Text
        return Document(title=[Text(content="The Report")], children=[
            Heading(level=1, children=[Text(content="Machines")]),
            Paragraph(children=[Text(content="Before the image.")]),
            Paragraph(children=[Image(src=self.path, **image)]),
            Paragraph(children=[Text(content="After the image.")]),
        ])

    def test_title_section_and_text_around(self):
        (prompt,) = self._prompts(self._report())
        self.assertIn("Title: The Report\nSection: Machines\nText before: Machines Before the image.\n"
                      "Text after: After the image.", prompt)

    def test_caption_opens_the_text_after(self):
        from textconverter.ast import Text
        (prompt,) = self._prompts(self._report(caption=[Text(content="The caption.")]))
        self.assertIn("Text after: The caption. After the image.", prompt)

    def test_text_is_cut_per_side(self):
        cfg = _config()
        cfg.ai.description_context = 6
        (prompt,) = self._prompts(self._report(), config=cfg)
        self.assertIn("Text before: mage.\nText after: After", prompt)

    def test_image_in_a_table_cell(self):
        from textconverter.ast import Document, Image, Table, TableCell, TableRow, Text
        cells = [TableCell(children=[Text(content="Left")]), TableCell(children=[Image(src=self.path)]),
                 TableCell(children=[Text(content="Right")])]
        (prompt,) = self._prompts(Document(children=[Table(rows=[TableRow(cells=cells)])]))
        self.assertIn("Text before: Left\nText after: Right", prompt)

    def test_image_in_a_list(self):
        from textconverter.ast import Document, Image, ListBlock, ListItem, Paragraph, Text
        items = [ListItem(children=[Paragraph(children=[Text(content="First")])]),
                 ListItem(children=[Paragraph(children=[Image(src=self.path)])])]
        (prompt,) = self._prompts(Document(children=[ListBlock(ordered=False, items=items)]))
        self.assertIn("Text before: First", prompt)

    def test_copies_take_the_first_context(self):
        from textconverter.ast import Document, Image, Paragraph, Text
        doc = Document(children=[Paragraph(children=[Text(content="One"), Image(src=self.path)]),
                                 Paragraph(children=[Text(content="Two"), Image(src=self.path)])])
        (prompt,) = self._prompts(doc)
        self.assertIn("Text before: One\nText after: Two", prompt)

    def test_no_text_leaves_the_prompt_alone(self):
        (prompt,) = self._prompts(_doc_with_images(1))
        self.assertEqual(prompt, _config().ai.prompts["photo_drawing_or_comic"])

    def test_no_context_setting(self):
        cfg = _config()
        cfg.ai.description_context = 0
        (prompt,) = self._prompts(self._report(), config=cfg)
        self.assertEqual(prompt, cfg.ai.prompts["photo_drawing_or_comic"])

    def test_extracted_text_stays(self):
        cfg = _config()
        cfg.ai.provide_extracted_text_to_describer = True
        (prompt,) = self._prompts(self._report(extracted_text="Text of the vector."), config=cfg)
        self.assertIn("Text of the vector.", prompt)
        self.assertIn("Section: Machines", prompt)

    def test_without_split_pages_descriptions_stay_before_ocr(self):
        """Nothing is read for a figure there, so reordering would only cost a model swap."""
        from textconverter.ast import Image, Paragraph
        doc = self._report()
        doc.children.append(Paragraph(children=[Image(src=_copies(2)[1])]))
        self._prompts(doc, categories=("photo_drawing_or_comic", "table"))
        self.assertEqual(self.models, ["cls", "cls", "desc", "ocr"])


class TestThinking(BaseConverterTest):

    def _calls(self, config):
        from textconverter.image_describer import process_images
        fake = FakeAi(["diagram"], {"desc": "A diagram."})
        call = MagicMock(side_effect=fake)
        with patch("unified_ai_client.call_ai", call), patch("unified_ai_client.preload_model"):
            process_images(_doc_with_images(1), "", handling="describe", config=config, save_crop=_no_crop)
        return {c.kwargs["model"]: c.kwargs["thinking"] for c in call.call_args_list}

    def test_off_by_default(self):
        self.assertEqual(self._calls(_config()), {"cls": False, "desc": False})

    def test_description_thinking_leaves_it_to_the_model(self):
        """The setting is for descriptions only: classification stays off."""
        config = _config()
        config.ai.description_thinking = True
        self.assertEqual(self._calls(config), {"cls": False, "desc": "default"})


class TestAnswers(BaseConverterTest):

    def setUp(self):
        super().setUp()
        self.paths = _copies(3)

    def _transcribe(self, fake):
        from textconverter.ast import Document, Image, Paragraph
        from textconverter.image_describer import process_images
        doc = Document(children=[Paragraph(children=[Image(src=path)]) for path in self.paths])
        with patch("unified_ai_client.call_ai", side_effect=fake), \
             patch("unified_ai_client.preload_model"):
            process_images(doc, "", handling="describe", config=_config(), save_crop=_no_crop)
        return doc

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
                                              textconverter.ConvertOptions(image_handling="append"))

    def test_markdown_keeps_the_image_markers_and_table(self):
        md = self._convert("markdown")
        self.assertIn("![pic](", md)
        self.assertIn("----- Start of picture description (table) -----", md)
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
        from textconverter.ast import Image, Link, Paragraph, Text
        link = Link(url="https://e.org", content=[self._described()])
        doc = self._lowered(Paragraph(children=[Text(content="See "), link, Text(content=" here.")]))
        first, header = doc.children[:2]
        self.assertEqual(first.children[1].content, [Image(src="pic.png", category="photo_drawing_or_comic")])
        self.assertEqual(first.children[2], Text(content=" here."))
        self.assertIn("Start of picture description", header.children[0].content)
        self.assertEqual(doc.children[-1].children[:2], [Text(content="Figure: "), Text(content="The car")])

    def test_described_image_in_a_table_cell_follows_the_table(self):
        from textconverter.ast import Paragraph, Table, TableCell, TableRow, Text
        cell = TableCell(children=[self._described()])
        doc = self._lowered(Table(rows=[TableRow(cells=[cell])]), Paragraph(children=[Text(content="After.")]))
        self.assertIsInstance(doc.children[0], Table)
        self.assertEqual(cell.children[0].src, "pic.png")
        self.assertEqual(doc.children[-1].children, [Text(content="After.")])
        self.assertIn("red", "".join(n.content for p in doc.children[1:-1] for n in getattr(p, "children", [])
                                     if isinstance(n, Text)))

    def test_json_keeps_the_described_image(self):
        import json
        doc = json.loads(self._convert("json"))
        images = [n for n in doc["children"][1]["children"] if n["type"] == "Image"]
        self.assertEqual(images[0]["category"], "table")
        self.assertIn("| a | b |", images[0]["description"])
