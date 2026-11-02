"""The two image options through whole conversions: what stays in the document, and how it is written."""
from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import openpyxl

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

    def test_auto_handling_transcribes_for_latex_and_discards_for_csv(self):
        self.assertEqual(self._handling("docx", "latex"), "transcribe")
        self.assertEqual(self._handling("docx", "csv"), "discard")

    def test_auto_handling_transcribes_a_source_made_of_pages(self):
        for to_format in OUTPUT_FORMATS:
            self.assertEqual(self._handling("image", to_format), "transcribe", to_format)
            self.assertEqual(self._handling("pdf", to_format, pdf_mode="raster"), "transcribe", to_format)

    def test_a_handling_by_name_is_kept_and_is_not_implicit(self):
        for handling in IMAGE_HANDLING_CHOICES[1:]:
            for from_format in INPUT_FORMATS:
                plan = resolve_images(ConvertOptions(image_handling=handling), from_format, "html")
                self.assertEqual((plan.handling, plan.implicit), (handling, False))

    def test_only_keep_and_discard_leave_the_models_alone(self):
        analyzed = {h for h in IMAGE_HANDLING_CHOICES[1:]
                    if resolve_images(ConvertOptions(image_handling=h), "html", "html").analyzes}
        self.assertEqual(analyzed, {"split", "transcribe", "describe", "replace", "append"})

    def test_auto_output_is_the_default_of_the_format(self):
        expected = {"html": "embed", "json": "embed", "markdown": "link", "latex": "link", "pdf": "embed",
                    "docx": "embed", "pptx": "embed", "xlsx": "embed", "csv": None}
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
        path = self.dir / "doc.json"
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
    ANSWERS = {"desc": "A logo.", "ocr": "Read text."}

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
        with patch("unified_ai_client.call_ai", side_effect=self.fake), patch("unified_ai_client.preload_model"):
            return textconverter.convert(str(source or self.source), to_format,
                                         ConvertOptions(image_handling=handling, **kwargs), output_dir=str(self.dir),
                                         config=_config())

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
            self.assertEqual({model for model, _ in self.fake.calls}, models, handling)
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


class TestJsonIsParsable(BaseConverterTest):

    def test_the_embedded_form_reads_back(self):
        doc = json.loads(textconverter.convert_text(f"![x]({DATA_URL})\n", "markdown", "json"))
        self.assertEqual(doc["children"][0]["children"][0]["src"], DATA_URL)
