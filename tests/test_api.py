"""The public API shape (convert, convert_text, save_to_file, ConvertOptions) and
the source-independent AST passes applied by api.convert().

Usage: python -m unittest discover -s tests -p "test_api.py"
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import textconverter
from textconverter import ConvertOptions
from textconverter.formats import infer_input_format, infer_output_format
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR


class TestDiscardLinks(BaseConverterTest):

    def test_discard_links_is_source_independent(self):
        """--discard-links unwraps every link to its text, keeping a link-wrapped image."""
        src = ("[Modena](https://en.wikipedia.org/wiki/Modena) is a [city](http://x.test). "
               "[![alt](pic.jpg)](http://y.test)")
        md = textconverter.convert_text(src, "markdown", "markdown", ConvertOptions(discard_links=True))
        self.assertIn("Modena is a city.", md)
        self.assertNotIn("http", md)
        self.assertIn("![alt](pic.jpg)", md)


class TestOptionsValidation(BaseConverterTest):

    def test_unknown_option_values_fail_on_creation(self):
        """A misspelled value is rejected before any work, not silently ignored."""
        for kwargs in ({"template": "drak"}, {"image_handling": "embedd"}, {"pdf_mode": "ocr"}):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                ConvertOptions(**kwargs)

    def test_template_aliases_are_accepted(self):
        for name in ("plain", "light", "light-theme", "pretty", "dark", "dark-theme"):
            ConvertOptions(template=name)

    def test_unknown_formats_fail_before_parsing(self):
        with self.assertRaises(ValueError):
            textconverter.convert_text("# x", "markdown", "md")
        with self.assertRaises(ValueError):
            textconverter.convert_text("# x", "rst", "html")

    def test_get_template_rejects_unknown_names(self):
        from textconverter.renderers.templates import get_template
        self.assertIn("<html", get_template("Dark-Theme"))
        with self.assertRaises(ValueError):
            get_template("drak")


class TestTextAndFiles(BaseConverterTest):

    def test_convert_text_never_reads_a_file(self):
        """Text that happens to be an existing file name stays text."""
        name = str(INPUT_DIR / "SampleMD.md")
        md = textconverter.convert_text(name, "markdown", "markdown")
        self.assertIn("SampleMD", md)
        self.assertEqual(len(md.strip().splitlines()), 1, "the file content was read")

    def test_binary_formats_need_a_file(self):
        with self.assertRaisesRegex(ValueError, "needs a file"):
            textconverter.convert_text("%PDF-1.7", "pdf", "markdown")

    def test_convert_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            textconverter.convert("no/such/file.md", "html")

    def test_txt_is_read_as_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "notes.txt"
            src.write_text("# Title\n\nSome *text*.", encoding="utf-8")
            html = textconverter.convert(str(src), "html")
        self.assertIn("<h1>Title</h1>", html)
        self.assertIn("<i>text</i>", html)

    def test_format_inference(self):
        self.assertEqual(infer_input_format("a/B.TEX"), "latex")
        self.assertEqual(infer_input_format("x.webp"), "image")
        self.assertIsNone(infer_input_format("x.docx"))
        self.assertEqual(infer_output_format("out.htm"), "html")
        self.assertIsNone(infer_output_format("out.txt"))

    def test_save_to_file_refuses_to_overwrite_the_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.md")
            Path(src).write_text("# a", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source file itself"):
                textconverter.save_to_file(src, src)
            self.assertEqual(Path(src).read_text(encoding="utf-8"), "# a")


class TestEmbeddedImages(BaseConverterTest):

    def test_embedding_leaves_no_image_folder(self):
        """Images extracted from a PDF, then embedded, used to leave an <stem>_images folder."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "vector.html"
            textconverter.save_to_file(str(INPUT_DIR / "Vector Image PDF.pdf"), str(out))
            self.assertIn("data:image/", out.read_text(encoding="utf-8"))
            self.assertEqual(os.listdir(tmp), ["vector.html"])
            # With link, the folder is the output's
            textconverter.save_to_file(str(INPUT_DIR / "Vector Image PDF.pdf"), str(out.with_suffix(".md")))
            self.assertIn("vector_images", os.listdir(tmp))

    def test_root_relative_path_is_explained(self):
        from unittest.mock import patch
        with patch("textconverter.images.log_warning") as warn:
            textconverter.convert_text('<p><img src="/media/x.png"></p>', "html", "html")
        self.assertIn("relative to the root of the site", warn.call_args.args[0])


class TestWindowsIntegration(BaseConverterTest):

    def test_context_menu_covers_every_input_format(self):
        """Every input extension except .txt (left out on purpose) has a context menu entry."""
        import re
        from textconverter.formats import INPUT_FORMATS
        script = (INPUT_DIR.parent.parent / "Windows Integration" / "generate_registry_files.ps1").read_text(encoding="utf-8")
        menu = set(re.findall(r'^\s+"(\.\w+)"\s*=', script, flags=re.MULTILINE))
        supported = {ext for f in INPUT_FORMATS.values() for ext in f.extensions} - {".txt"}
        self.assertEqual(menu, supported)


class TestCli(BaseConverterTest):

    def test_from_and_choices_come_from_the_registry(self):
        import contextlib
        import io
        from textconverter.__main__ import build_parser
        args = build_parser().parse_args(["convert", "page", "out.md", "--from", "html", "--template", "dark"])
        self.assertEqual((args.from_format, args.template), ("html", "dark"))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["convert", "a.md", "b.html", "--template", "drak"])
