"""The two image options through whole conversions: what stays in the document, and how it is written."""
from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import openpyxl
from PIL import Image as PilImage

import textconverter
from textconverter import ConvertOptions
from textconverter.config import AppConfig
from textconverter.formats import IMAGE_HANDLING_CHOICES, INPUT_FORMATS, OUTPUT_FORMATS
from textconverter.options import resolve_images

from _support import BaseConverterTest, FakeAi, INPUT_DIR, setUpModule, tearDownModule  # noqa: F401

PNG = INPUT_DIR / "googlelogo_color_272x92dp.png"
DATA_URL = "data:image/png;base64," + base64.b64encode(PNG.read_bytes()).decode()


def _config() -> AppConfig:
    cfg = AppConfig()
    cfg.ai.classification_model, cfg.ai.description_model, cfg.ai.ocr_model = "cls", "desc", "ocr"
    cfg.ai.region_model = ""
    return cfg


class TestResolution(BaseConverterTest):

    def _handling(self, from_format, to_format, **options):
        return resolve_images(ConvertOptions(**options), from_format, to_format).handling

    def test_auto_handling_keeps_the_images_of_a_document(self):
        for to_format in ("markdown", "html", "json", "pdf", "docx", "pptx", "xlsx"):
            self.assertEqual(self._handling("docx", to_format), "keep", to_format)

    def test_auto_handling_transcribes_for_latex_and_discards_for_csv_and_text(self):
        self.assertEqual(self._handling("docx", "latex"), "transcribe")
        self.assertEqual(self._handling("docx", "csv"), "discard")
        self.assertEqual(self._handling("docx", "text"), "discard")

    def test_auto_handling_transcribes_a_source_made_of_pages(self):
        for to_format in OUTPUT_FORMATS:
            self.assertEqual(self._handling("image", to_format), "transcribe", to_format)
            self.assertEqual(self._handling("pdf", to_format, pdf_mode="raster"), "transcribe", to_format)

    def test_a_handling_by_name_is_kept_and_needs_its_models(self):
        for handling in IMAGE_HANDLING_CHOICES[1:]:
            for from_format in INPUT_FORMATS:
                if handling == "discard" and from_format == "image":
                    continue
                plan = resolve_images(ConvertOptions(image_handling=handling), from_format, "html")
                self.assertEqual((plan.handling, plan.ai_required), (handling, True))

    def test_only_keep_and_discard_leave_the_models_alone(self):
        analyzed = {h for h in IMAGE_HANDLING_CHOICES[1:]
                    if resolve_images(ConvertOptions(image_handling=h), "html", "html").analyzes}
        self.assertEqual(analyzed, {"split", "transcribe", "describe", "replace", "append"})

    def test_auto_output_is_the_default_of_the_format(self):
        expected = {"html": "embed", "json": "embed", "markdown": "link", "latex": "link", "pdf": "embed",
                    "docx": "embed", "pptx": "embed", "xlsx": "embed", "csv": None, "text": None}
        self.assertEqual({name: resolve_images(ConvertOptions(), "html", name).output for name in OUTPUT_FORMATS},
                         expected)

    def test_an_output_the_format_lacks_gives_its_default_with_one_warning(self):
        for to_format, asked, used in (("latex", "embed", "link"), ("docx", "link", "embed"), ("pdf", "link", "embed"),
                                       ("csv", "embed", None)):
            with self.subTest(to_format=to_format), patch("textconverter.options.log_warning") as warn:
                plan = resolve_images(ConvertOptions(image_output=asked), "html", to_format)
                self.assertEqual(plan.output, used)
                warn.assert_called_once()

    def test_an_output_the_format_offers_gives_no_warning(self):
        for to_format, asked in (("markdown", "embed"), ("html", "link"), ("json", "link"), ("docx", "embed")):
            with self.subTest(to_format=to_format), patch("textconverter.options.log_warning") as warn:
                self.assertEqual(resolve_images(ConvertOptions(image_output=asked), "html", to_format).output, asked)
                warn.assert_not_called()

    def test_the_old_values_are_gone(self):
        for value in ("embed", "link", "auto_latex"):
            with self.assertRaises(ValueError):
                ConvertOptions(image_handling=value)


class TestOutputOfTheImages(BaseConverterTest):

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        (self.dir / "p.png").write_bytes(PNG.read_bytes())
        self.source = self.dir / "doc.md"
        self.source.write_text("Before.\n\n![x](p.png)\n\nAfter.\n", encoding="utf-8")

    def _json_source(self) -> Path:
        path = self.dir / "doc.aston"
        path.write_text(textconverter.convert(str(self.source), "json", ConvertOptions(image_output="link"),
                                              output_dir=str(self.dir)), encoding="utf-8")
        return path

    def test_json_embeds_by_default(self):
        self.assertIn("data:image/png;base64,", textconverter.convert(str(self.source), "json"))

    def test_json_links_when_asked(self):
        doc = textconverter.convert(str(self.source), "json", ConvertOptions(image_output="link"),
                                    output_dir=str(self.dir))
        self.assertIn('"src": "p.png"', doc)

    def test_a_linked_data_url_becomes_a_file_in_every_format(self):
        self.source.write_text(f"![x]({DATA_URL})\n", encoding="utf-8")
        for to_format in ("markdown", "html", "json", "latex"):
            with self.subTest(to_format=to_format):
                out = self.dir / "out"
                text = textconverter.convert(str(self.source), to_format,
                                             ConvertOptions(image_handling="keep", image_output="link"),
                                             output_dir=str(self.dir), image_dir_name="out")
                self.assertNotIn("data:", text)
                self.assertEqual(len(list(out.iterdir())), 1)

    def test_a_kept_data_url_stays_embedded(self):
        self.source.write_text(f"![x]({DATA_URL})\n", encoding="utf-8")
        self.assertIn(DATA_URL, textconverter.convert(str(self.source), "html"))

    def test_a_data_url_reaches_the_models(self):
        self.source.write_text(f"![x]({DATA_URL})\n", encoding="utf-8")
        fake = FakeAi(["photo_drawing_or_comic"], {"desc": "A logo."})
        with patch("unified_ai_client.call_ai", side_effect=fake), patch("unified_ai_client.preload_model"):
            text = textconverter.convert(str(self.source), "markdown", ConvertOptions(image_handling="describe"),
                                         output_dir=str(self.dir), image_dir_name="imgs", config=_config())
        self.assertIn("A logo.", text)

    def test_an_analyzed_image_is_embedded_too(self):
        fake = FakeAi(["photo_drawing_or_comic"], {"desc": "A logo."})
        with patch("unified_ai_client.call_ai", side_effect=fake), patch("unified_ai_client.preload_model"):
            text = textconverter.convert(str(self.source), "html", ConvertOptions(image_handling="describe"),
                                         config=_config())
        self.assertIn('src="data:image/png;base64,', text)
        self.assertIn("A logo.", text)

    def test_a_pdf_is_printed_with_its_images_whatever_is_asked(self):
        import pymupdf
        out = self.dir / "out.pdf"
        with patch("textconverter.options.log_warning") as warn:
            textconverter.save_to_file(str(self.source), str(out), ConvertOptions(image_output="link"))
        warn.assert_called_once()
        with pymupdf.open(out) as pdf:
            self.assertEqual(sum(len(page.get_images()) for page in pdf), 1)
        self.assertFalse((self.dir / "out_images").exists())

    def test_json_is_a_source_like_the_others(self):
        source = self._json_source()
        self.assertIn('src="data:image/png;base64,', textconverter.convert(str(source), "html"))
        self.assertNotIn("p.png", textconverter.convert(str(source), "markdown",
                                                        ConvertOptions(image_handling="discard")))

    def test_json_goes_through_the_models_when_asked(self):
        fake = FakeAi(["photo_drawing_or_comic"], {"desc": "A logo."})
        with patch("unified_ai_client.call_ai", side_effect=fake), patch("unified_ai_client.preload_model"):
            text = textconverter.convert(str(self._json_source()), "markdown",
                                         ConvertOptions(image_handling="describe"), config=_config())
        self.assertIn("A logo.", text)


class TestWithoutImages(BaseConverterTest):

    def test_csv_leaves_no_image_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.csv"
            textconverter.save_to_file(str(INPUT_DIR / "Test_sheets.xlsx"), str(out))
            self.assertEqual({p.suffix for p in Path(tmp).iterdir()}, {".csv"})

    def test_csv_drops_an_image_kept_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.csv"
            source = Path(tmp) / "doc.md"
            (Path(tmp) / "p.png").write_bytes(PNG.read_bytes())
            source.write_text("| a |\n|---|\n| ![x](p.png) |\n", encoding="utf-8")
            textconverter.save_to_file(str(source), str(out), ConvertOptions(image_handling="keep"))
            self.assertNotIn("p.png", out.read_text(encoding="utf-8-sig"))
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["doc.md", "out.csv", "p.png"])

    def test_excel_embeds_the_image_of_a_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.xlsx"
            textconverter.save_to_file(str(INPUT_DIR / "Test_sheets.xlsx"), str(out))
            book = openpyxl.load_workbook(out)
            self.assertEqual(sum(len(sheet._images) for sheet in book), 1)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["out.xlsx"])


class TestClientMissing(BaseConverterTest):

    def _convert(self, to_format, **options):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "doc.md"
            (Path(tmp) / "p.png").write_bytes(PNG.read_bytes())
            source.write_text("![x](p.png)\n", encoding="utf-8")
            with patch("textconverter.image_describer.ai_client_available", return_value=False):
                return textconverter.convert(str(source), to_format, ConvertOptions(**options), output_dir=tmp)

    def test_an_analysis_by_name_needs_the_client(self):
        for handling in ("transcribe", "describe"):
            with self.assertRaises(ImportError):
                self._convert("latex", image_handling=handling)

    def test_auto_for_latex_keeps_the_image(self):
        self.assertIn(r"\includegraphics{p.png}", self._convert("latex"))


class TestTreatments(BaseConverterTest):
    """What each handling leaves of a text image and of a figure, in Markdown and in the AST."""

    PHOTO = "photo_drawing_or_comic"
    ANSWERS = {"desc": "A logo.", "ocr": "Read text.", "region": ""}

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        (self.dir / "p.png").write_bytes(PNG.read_bytes())
        self.source = self.dir / "doc.md"
        self.source.write_text("Before.\n\n![x](p.png)\n\nAfter.\n", encoding="utf-8")

    def _convert(self, category, handling, to_format="markdown", source=None, **kwargs):
        self.fake = FakeAi([category], self.ANSWERS)
        config = _config()
        config.ai.region_model = "region"
        with patch("unified_ai_client.call_ai", side_effect=self.fake), patch("unified_ai_client.preload_model"):
            return textconverter.convert(str(source or self.source), to_format,
                                         ConvertOptions(image_handling=handling, **kwargs), output_dir=str(self.dir),
                                         config=config)

    def test_what_stays_of_each_kind_of_image(self):
        expected = {  # handling: (figure: image, description; text image: image, text)
            "split": (True, False, True, False),
            "transcribe": (True, False, False, True),
            "describe": (True, True, False, True),
            "replace": (False, True, False, True),
            "append": (True, True, True, True),
        }
        for handling, (figure_image, description, text_image, text) in expected.items():
            with self.subTest(handling=handling):
                figure = self._convert(self.PHOTO, handling)
                self.assertEqual(("![x](p.png)" in figure, "A logo." in figure), (figure_image, description))
                transcribed = self._convert("text", handling)
                self.assertEqual(("![x](p.png)" in transcribed, "Read text." in transcribed), (text_image, text))

    def test_a_handling_calls_only_the_models_it_needs(self):
        needed = {"split": {"cls"}, "transcribe": {"cls", "ocr"}, "describe": {"cls", "ocr"}, "replace": {"cls", "ocr"},
                  "append": {"cls", "ocr"}}
        for handling, models in needed.items():
            self._convert("text", handling)
            self.assertEqual({model for model, _ in self.fake.calls} - {"region"}, models, handling)
        self._convert(self.PHOTO, "transcribe")
        self.assertEqual({model for model, _ in self.fake.calls}, {"cls"})
        self._convert(self.PHOTO, "describe")
        self.assertEqual({model for model, _ in self.fake.calls}, {"cls", "desc"})

    def test_a_page_scan_is_a_text_image_whatever_the_handling(self):
        self.assertIn("Read text.", self._convert("document_scan", "transcribe"))

    def test_text_replaces_the_image_without_markers(self):
        self.assertNotIn("picture description", self._convert("text", "describe"))

    def test_a_kept_description_is_framed_with_its_category(self):
        text = self._convert(self.PHOTO, "describe")
        self.assertIn("![x](p.png)", text)
        self.assertIn(f"----- Start of picture description ({self.PHOTO}) -----", text)
        self.assertIn("----- End of picture description -----", text)

    def test_no_reference_line_is_left(self):
        for handling in ("describe", "append"):
            self.assertNotIn("Image Reference", self._convert(self.PHOTO, handling))

    def test_json_holds_what_the_handling_leaves(self):
        kept = json.loads(self._convert(self.PHOTO, "describe", "json", image_output="link"))
        image = kept["children"][1]["children"][0]
        self.assertEqual((image["src"], image["description"], image["category"]), ("p.png", "A logo.", self.PHOTO))
        replaced = self._convert(self.PHOTO, "replace", "json")
        self.assertNotIn('"Image"', replaced)
        self.assertIn("A logo.", replaced)

    def test_a_failed_analysis_leaves_the_image(self):
        with patch("unified_ai_client.call_ai", side_effect=ConnectionError("down")), \
             patch("unified_ai_client.preload_model"):
            text = textconverter.convert(str(self.source), "markdown", ConvertOptions(image_handling="replace"),
                                         output_dir=str(self.dir), config=_config())
        self.assertIn("![x](p.png)", text)

    def test_a_described_document_is_not_analyzed_again(self):
        again = self.dir / "again.md"
        again.write_text(self._convert(self.PHOTO, "describe"), encoding="utf-8")
        self.assertIn("A logo.", self._convert(self.PHOTO, "describe", source=again))
        self.assertEqual(self.fake.calls, [])

    def test_a_kept_description_follows_the_handling_asked(self):
        again = self.dir / "again.md"
        again.write_text(self._convert(self.PHOTO, "describe"), encoding="utf-8")
        replaced = self._convert(self.PHOTO, "replace", source=again)
        self.assertEqual(("![x](p.png)" in replaced, "A logo." in replaced), (False, True))
        transcribed = self._convert(self.PHOTO, "transcribe", source=again)
        self.assertEqual(("![x](p.png)" in transcribed, "A logo." in transcribed), (True, False))

    def test_a_kept_image_reaches_word_and_the_pdf_with_its_description(self):
        import docx
        import pymupdf
        fake = FakeAi([self.PHOTO, self.PHOTO], self.ANSWERS)
        options = ConvertOptions(image_handling="describe")
        word, pdf = self.dir / "out.docx", self.dir / "out.pdf"
        with patch("unified_ai_client.call_ai", side_effect=fake), patch("unified_ai_client.preload_model"):
            textconverter.save_to_file(str(self.source), str(word), options, config=_config())
            textconverter.save_to_file(str(self.source), str(pdf), options, config=_config())
        written = docx.Document(word)
        self.assertEqual(len(written.inline_shapes), 1)
        self.assertIn("A logo.", "\n".join(p.text for p in written.paragraphs))
        with pymupdf.open(pdf) as printed:
            self.assertEqual(sum(len(page.get_images()) for page in printed), 1)
            self.assertIn("A logo.", printed[0].get_text())


class TestImageSource(BaseConverterTest):
    """An image file as the source goes through the same options as an image in a document."""

    PHOTO = "photo_drawing_or_comic"
    ANSWERS = {"desc": "A logo.", "ocr": "Read text."}

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)

    def _convert(self, category="text", to_format="markdown", **options):
        self.fake = FakeAi([category], self.ANSWERS)
        with patch("unified_ai_client.call_ai", side_effect=self.fake), patch("unified_ai_client.preload_model"):
            return textconverter.convert(str(PNG), to_format, ConvertOptions(**options), output_dir=str(self.dir),
                                         image_dir_name="imgs", config=_config())

    def test_auto_transcribes_text_for_every_output(self):
        for to_format in ("markdown", "html", "latex", "json"):
            self.assertIn("Read text.", self._convert(to_format=to_format), to_format)

    def test_auto_leaves_a_photo_as_an_image(self):
        text = self._convert(self.PHOTO)
        self.assertIn("![googlelogo_color_272x92dp.png](", text)
        self.assertNotIn("A logo.", text)
        self.assertEqual({model for model, _ in self.fake.calls}, {"cls"})

    def test_describe_keeps_a_photo_with_its_description(self):
        text = self._convert(self.PHOTO, image_handling="describe")
        self.assertIn("![googlelogo_color_272x92dp.png](", text)
        self.assertIn("A logo.", text)

    def test_replace_leaves_the_text_only(self):
        text = self._convert(self.PHOTO, image_handling="replace")
        self.assertEqual(text.strip(), "A logo.")

    def test_append_keeps_the_text_image_too(self):
        text = self._convert(image_handling="append")
        self.assertIn("Read text.", text)
        self.assertIn("![", text)

    def test_keep_calls_no_model_and_needs_no_client(self):
        with patch("textconverter.image_describer.ai_client_available", return_value=False):
            html = self._convert(to_format="html", image_handling="keep")
        self.assertEqual(self.fake.calls, [])
        self.assertIn('src="data:image/png;base64,', html)

    def test_a_kept_image_links_to_its_source(self):
        text = self._convert(image_handling="keep")
        target = text[text.index("](") + 2:text.index(")")].strip("<>")
        self.assertTrue((self.dir / target).samefile(PNG), text)

    def test_discard_is_refused(self):
        with self.assertRaisesRegex(ValueError, "replace"):
            self._convert(image_handling="discard")

    def test_auto_needs_the_client(self):
        with patch("textconverter.image_describer.ai_client_available", return_value=False):
            with self.assertRaises(ImportError):
                self._convert()

    def test_split_needs_a_region_model(self):
        with self.assertRaisesRegex(ValueError, "region_model"):
            self._convert(image_handling="split")
        self.assertEqual(self.fake.calls, [])

    def test_an_image_from_a_url_outlives_the_conversion(self):
        from textconverter._net import Download
        download = Download(data=PNG.read_bytes(), content_type="image/png", charset=None)
        with patch("textconverter._net.fetch", return_value=download):
            text = textconverter.convert("https://x.test/logo.png", "markdown", ConvertOptions(image_handling="keep"),
                                         output_dir=str(self.dir), image_dir_name="imgs")
        self.assertIn("(imgs/image_1.png)", text)
        self.assertTrue((self.dir / "imgs" / "image_1.png").exists())

    def test_no_model_touches_a_refused_source_in_save_to_file(self):
        with self.assertRaises(ValueError):
            textconverter.save_to_file(str(PNG), str(self.dir / "out.md"), ConvertOptions(image_handling="discard"))
        self.assertEqual(list(self.dir.iterdir()), [])


class TestDescriptionInACell(BaseConverterTest):

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        (self.dir / "p.png").write_bytes(PNG.read_bytes())
        self.source = self.dir / "doc.md"
        self.source.write_text("| a | b |\n|---|---|\n| ![x](p.png) | 1 |\n\nAfter.\n", encoding="utf-8")

    def _save(self, name, answer="A logo.", handling="describe", category="photo_drawing_or_comic"):
        out = self.dir / name
        fake = FakeAi([category], {"desc": answer, "ocr": answer})
        with patch("unified_ai_client.call_ai", side_effect=fake), patch("unified_ai_client.preload_model"):
            textconverter.save_to_file(str(self.source), str(out), ConvertOptions(image_handling=handling),
                                       config=_config())
        return out

    def test_excel_keeps_it_as_the_comment_of_the_cell(self):
        sheet = openpyxl.load_workbook(self._save("out.xlsx")).active
        self.assertEqual(len(sheet._images), 1)
        self.assertEqual(sheet["A2"].comment.text.strip(), "A logo.")
        self.assertEqual(sheet["B2"].value, 1)

    def test_excel_holds_a_transcription_of_several_blocks(self):
        sheet = openpyxl.load_workbook(self._save("out.xlsx", "First.\n\nSecond.", "append", "text")).active
        self.assertIn("First.", sheet["A2"].comment.text)
        self.assertIn("Second.", sheet["A2"].comment.text)

    def test_excel_with_replace_has_the_text_in_the_cell(self):
        sheet = openpyxl.load_workbook(self._save("out.xlsx", handling="replace")).active
        self.assertEqual((sheet["A2"].value, len(sheet._images)), ("A logo.", 0))

    def test_other_formats_keep_it_after_the_table(self):
        text = self._save("out.md").read_text(encoding="utf-8")
        self.assertLess(text.index("| 1 |"), text.index("A logo."))
        self.assertLess(text.index("A logo."), text.index("After."))


class TestScreening(BaseConverterTest):
    """What never reaches a model: images too small to hold anything, or in a form none reads."""

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        PilImage.new("RGB", (16, 16), "white").save(self.dir / "icon.png")
        (self.dir / "p.png").write_bytes(PNG.read_bytes())
        (self.dir / "v.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")

    def _convert(self, *names, config=None):
        source = self.dir / "doc.md"
        source.write_text("\n\n".join(f"![{name}]({name})" for name in names) + "\n", encoding="utf-8")
        self.fake = FakeAi(["photo_drawing_or_comic"] * 3, {"desc": "A logo."})
        with patch("unified_ai_client.call_ai", side_effect=self.fake), patch("unified_ai_client.preload_model"):
            return textconverter.convert(str(source), "markdown", ConvertOptions(image_handling="describe"),
                                         output_dir=str(self.dir), config=config or _config())

    def test_a_small_image_stays_as_it_is_without_a_call(self):
        text = self._convert("icon.png")
        self.assertEqual(self.fake.calls, [])
        self.assertIn("![icon.png](icon.png)", text)

    def test_the_other_images_are_still_read(self):
        text = self._convert("icon.png", "p.png")
        self.assertEqual(len(self.fake.calls), 2)
        self.assertEqual(text.count("A logo."), 1)

    def test_the_limit_is_the_area(self):
        config = _config()
        config.ai.min_image_pixels = 16 * 16
        self._convert("icon.png", config=config)
        self.assertEqual(len(self.fake.calls), 2)

    def test_zero_turns_the_limit_off(self):
        config = _config()
        config.ai.min_image_pixels = 0
        self._convert("icon.png", config=config)
        self.assertEqual(len(self.fake.calls), 2)

    def test_a_form_no_model_reads_is_left_out_whatever_the_limit(self):
        config = _config()
        config.ai.min_image_pixels = 0
        self.assertIn("![v.svg](v.svg)", self._convert("v.svg", config=config))
        self.assertEqual(self.fake.calls, [])

    def test_an_image_source_is_read_however_small(self):
        fake = FakeAi(["text"], {"ocr": "Read."})
        with patch("unified_ai_client.call_ai", side_effect=fake), patch("unified_ai_client.preload_model"):
            text = textconverter.convert(str(self.dir / "icon.png"), "markdown", output_dir=str(self.dir),
                                         config=_config())
        self.assertIn("Read.", text)


class TestFailures(BaseConverterTest):
    """A phase stops when calls keep failing, so a provider that is down costs a few calls only."""

    IMAGES = 6

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        self.source = self.dir / "doc.md"
        for n in range(self.IMAGES):
            PilImage.new("RGB", (100, 100), (n, 0, 0)).save(self.dir / f"{n}.png")
        self.source.write_text("\n\n".join(f"![{n}]({n}.png)" for n in range(self.IMAGES)) + "\n", encoding="utf-8")
        self.calls = []

    def _convert(self, answer, handling="describe"):
        """The document as Markdown; ``answer(model, number of the call to it)`` raises to fail a call."""
        def call(**kwargs):
            self.calls.append(kwargs["model"])
            return MagicMock(text=answer(kwargs["model"], self.calls.count(kwargs["model"])))

        with patch("unified_ai_client.call_ai", side_effect=call), patch("unified_ai_client.preload_model"), \
             patch("textconverter.image_describer.log_info") as info:
            text = textconverter.convert(str(self.source), "markdown", ConvertOptions(image_handling=handling),
                                         output_dir=str(self.dir), config=_config())
        self.logged = [c.args[0] for c in info.call_args_list]
        return text

    @staticmethod
    def _photo(model, number):
        if model == "cls":
            return '{"category": "photo_drawing_or_comic"}'
        raise ConnectionError("down")

    def test_a_stopped_classification_ends_the_analysis(self):
        def down(model, number):
            raise ConnectionError("down")
        text = self._convert(down)
        self.assertEqual(self.calls, ["cls"] * 3)
        self.assertEqual(text.count("!["), self.IMAGES)

    def test_a_stopped_phase_leaves_the_images_as_they_are(self):
        text = self._convert(self._photo)
        self.assertEqual(self.calls.count("desc"), 3)
        self.assertEqual(text.count("!["), self.IMAGES)
        self.assertNotIn("picture description", text)

    def test_an_empty_answer_counts_as_a_failure(self):
        self._convert(lambda model, number: '{"category": "photo_drawing_or_comic"}' if model == "cls" else "")
        self.assertEqual(self.calls.count("desc"), 3)

    def test_a_good_answer_starts_the_count_again(self):
        def every_third(model, number):
            if model == "cls":
                return '{"category": "photo_drawing_or_comic"}'
            if number % 3:
                raise ConnectionError("down")
            return "A photo."
        self._convert(every_third)
        self.assertEqual(self.calls.count("desc"), self.IMAGES)

    def test_a_stopped_phase_leaves_the_next_one_to_try(self):
        def by_model(model, number):
            if model == "cls":
                return '{"category": "%s"}' % ("table" if number % 2 else "photo_drawing_or_comic")
            if model == "desc":
                raise ConnectionError("down")
            return "| a |\n|---|\n| 1 |"
        self._convert(by_model)
        self.assertEqual((self.calls.count("desc"), self.calls.count("ocr")), (3, 3))

    def test_the_last_image_failing_is_no_stop(self):
        with patch("textconverter.image_describer.log_warning") as warn:
            self._convert(lambda model, number: '{"category": "text"}' if model == "cls" else
                          ("Read." if number <= self.IMAGES - 3 else ""))
        self.assertFalse(any("stopped" in c.args[0] for c in warn.call_args_list))

    def test_the_summary_counts_what_was_read(self):
        self._convert(lambda model, number: '{"category": "text"}' if model == "cls" else
                      ("" if number == 2 else "Read."))
        self.assertIn(f"{self.IMAGES - 1} of {self.IMAGES} images read.", self.logged)


class TestJsonIsParsable(BaseConverterTest):

    def test_the_embedded_form_reads_back(self):
        doc = json.loads(textconverter.convert_text(f"![x]({DATA_URL})\n", "markdown", "json"))
        self.assertEqual(doc["children"][0]["children"][0]["src"], DATA_URL)
