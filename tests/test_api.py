"""The public API shape (convert, convert_text, save_to_file, ConvertOptions) and
the source-independent AST passes applied by api.convert().

Usage: python -m unittest discover -s tests -p "test_api.py"
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
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


class TestUnsafeLinks(BaseConverterTest):
    """A link that would run code is neutralized in every format that keeps links."""

    SOURCE = "[click](javascript:alert(1)) and [fine](https://x.test)\n"

    def test_text_formats(self):
        from unittest.mock import patch
        for to in ("markdown", "latex", "html"):
            with self.subTest(to=to), patch("textconverter.images.log_warning") as warn:
                out = textconverter.convert_text(self.SOURCE, "markdown", to, ConvertOptions(image_handling="link"))
                self.assertNotIn("javascript", out)
                self.assertIn("click", out)
                self.assertIn("https://x.test", out)
                warn.assert_called_once()

    def test_the_ast_form_keeps_the_address(self):
        self.assertIn("javascript:alert(1)",
                      textconverter.convert_text(self.SOURCE, "markdown", "json", ConvertOptions(image_handling="link")))


class TestDiscardedImages(BaseConverterTest):

    def test_a_link_around_an_image_goes_with_it(self):
        md = textconverter.convert_text("a [![x](p.png)](http://y.test) b\n", "markdown", "markdown",
                                        ConvertOptions(image_handling="discard"))
        self.assertEqual(md, "a  b\n")

    def test_a_link_with_text_stays(self):
        md = textconverter.convert_text("[t ![x](p.png)](http://y.test)\n", "markdown", "markdown",
                                        ConvertOptions(image_handling="discard"))
        self.assertIn("http://y.test", md)

    def test_a_caption_goes_with_its_image(self):
        for to in ("markdown", "html", "latex"):
            with self.subTest(to=to):
                out = textconverter.convert_text("![x](p.png)\n\nFigure: The caption\n", "markdown", to,
                                                 ConvertOptions(image_handling="discard"))
                self.assertNotIn("The caption", out)


class TestEmbedInLatex(BaseConverterTest):

    def test_embed_writes_files_and_warns(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "a.md"
            (Path(tmp) / "p.png").write_bytes((INPUT_DIR / "googlelogo_color_272x92dp.png").read_bytes())
            src.write_text("![x](p.png)\n", encoding="utf-8")
            out = Path(tmp) / "out" / "a.tex"
            out.parent.mkdir()
            with patch("textconverter.api.log_warning") as warn:
                textconverter.save_to_file(str(src), str(out), ConvertOptions(image_handling="embed"))
            tex = out.read_text(encoding="utf-8")
        self.assertNotIn("data:", tex)
        self.assertIn("\\includegraphics{", tex)
        warn.assert_called_once()

    def test_a_data_url_becomes_a_file(self):
        import base64
        data = base64.b64encode((INPUT_DIR / "googlelogo_color_272x92dp.png").read_bytes()).decode()
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "a.md"
            src.write_text(f"![x](data:image/png;base64,{data})\n", encoding="utf-8")
            out = Path(tmp) / "a.tex"
            textconverter.save_to_file(str(src), str(out), ConvertOptions(image_handling="link"))
            tex = out.read_text(encoding="utf-8")
            self.assertNotIn("data:", tex)
            self.assertEqual(len(list((Path(tmp) / "a_images").iterdir())), 1)
        self.assertRegex(tex, r"\\includegraphics\{a_images/image_\w+\.png\}")

    def test_embed_still_embeds_elsewhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "a.md"
            (Path(tmp) / "p.png").write_bytes((INPUT_DIR / "googlelogo_color_272x92dp.png").read_bytes())
            src.write_text("![x](p.png)\n", encoding="utf-8")
            self.assertIn("data:image/png", textconverter.convert(str(src), "markdown", ConvertOptions(image_handling="embed")))


class TestOutputFolder(BaseConverterTest):

    def test_missing_folders_are_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "a.md"
            src.write_text("# a\n\n| x |\n|---|\n| 1 |\n", encoding="utf-8")
            for name in ("a.md", "a.html", "a.docx", "a.pptx", "a.xlsx", "a.csv", "a.pdf"):
                with self.subTest(name):
                    out = Path(tmp) / "new" / name.replace(".", "_") / "deep" / name
                    self.assertEqual(textconverter.save_to_file(str(src), str(out)), [str(out)])
                    self.assertTrue(out.exists())

    def test_a_folder_that_cannot_exist_fails_before_converting(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "a.md"
            src.write_text("# a", encoding="utf-8")
            blocker = Path(tmp) / "file"
            blocker.write_text("x", encoding="utf-8")
            with patch("textconverter.api._convert") as run, self.assertRaisesRegex(OSError, "output folder"):
                textconverter.save_to_file(str(src), str(blocker / "sub" / "a.md"))
            run.assert_not_called()


class TestSourceSignature(BaseConverterTest):
    """A file that is not what ``from_format`` says gives a readable error, not a parser's own."""

    def test_a_text_file_given_as_a_binary_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "a.md"
            src.write_text("# a", encoding="utf-8")
            for name in ("pdf", "docx", "pptx", "xlsx"):
                with self.subTest(name), self.assertRaisesRegex(ValueError, f"not a valid {name}"):
                    textconverter.convert(str(src), "markdown", from_format=name)

    def test_office_formats_are_told_apart(self):
        with self.assertRaisesRegex(ValueError, "not a valid xlsx"):
            textconverter.convert(str(INPUT_DIR / "Test_docx.docx"), "markdown", from_format="xlsx")

    def test_real_files_pass(self):
        self.assertIn("Lorem", textconverter.convert(str(INPUT_DIR / "Simple Pdf.pdf"), "markdown",
                                                     ConvertOptions(image_handling="discard"), from_format="pdf"))


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
        self.assertEqual(infer_input_format("x.docx"), "docx")
        self.assertIsNone(infer_input_format("x.doc"))
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


@unittest.skipUnless(sys.platform == "win32", "the context menu is Windows only")
class TestWindowsIntegration(BaseConverterTest):
    FOLDER = INPUT_DIR.parent.parent / "Windows Integration"

    def _register(self, folder: str) -> str:
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(self.FOLDER / "generate_registry_files.ps1"), "-OutputDir", folder],
                       check=True, capture_output=True)
        return (Path(folder) / "register.reg").read_text(encoding="utf-16")

    def _menu(self, register: str) -> dict[str, set[str]]:
        """The target extensions of each source extension, from the generated registry file."""
        menu: dict[str, set[str]] = {}
        source = ""
        for line in register.splitlines():
            key = re.search(r'SystemFileAssociations.(\.\w+).shell.TextConverter', line)
            source = key.group(1) if key else source
            target = re.search(r'%1\W+(\.\w+) --template', line)
            if target:
                menu.setdefault(source, set()).add(target.group(1))
        return menu

    def test_context_menu_goes_from_every_input_to_every_output(self):
        """Except .txt as a source, JSON as a target, and a format to itself (HTML cleans a page up)."""
        from textconverter.formats import INPUT_FORMATS, OUTPUT_FORMATS
        targets = {f.extensions[0] for f in OUTPUT_FORMATS.values()} - {".json"}
        with tempfile.TemporaryDirectory() as tmp:
            register = self._register(tmp)
        menu = self._menu(register)
        expected = {}
        for name, fmt in INPUT_FORMATS.items():
            own = OUTPUT_FORMATS[name].extensions[0] if name in OUTPUT_FORMATS else None
            for ext in fmt.extensions:
                expected[ext] = targets if name == "html" or ext == ".tsv" else targets - {own}
        del expected[".txt"]
        self.assertEqual(menu, expected)
        self.assertIn(".csv --template plain --pdf-mode raster", register)
        self.assertIn(".xlsx --template plain --extract-html", register)

    def _run_entry(self, source: Path, target: str, *options: str) -> None:
        """Run convert.cmd the way Explorer does, with the file name quoted by the registry command."""
        command = f'cmd /c ""{self.FOLDER / "convert.cmd"}" "{source}" {target} {" ".join(options)}"'
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout)

    @unittest.skipUnless((INPUT_DIR.parent.parent / ".venv" / "Scripts" / "textconverter.exe").exists(), "no .venv")
    def test_context_menu_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "a & b 50%.html"
            source.write_text("<p>x</p>", encoding="utf-8")
            self._run_entry(source, ".html", "--template", "plain")
            self._run_entry(source, ".html", "--template", "dark-theme")
            self._run_entry(source, ".html", "--template", "plain")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),
                             ["a & b 50%.html", "a & b 50%_converted.html", "a & b 50%_converted2.html",
                              "a & b 50%_converted3.html"])
            self.assertEqual(source.read_text(encoding="utf-8"), "<p>x</p>")

    @unittest.skipUnless((INPUT_DIR.parent.parent / ".venv" / "Scripts" / "textconverter.exe").exists(), "no .venv")
    def test_context_menu_counts_the_files_of_a_table_each(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "t.md"
            source.write_text("# A\n\n| a |\n|---|\n| 1 |\n\n# B\n\n| b |\n|---|\n| 2 |\n", encoding="utf-8")
            self._run_entry(source, ".csv", "--template", "plain")
            self._run_entry(source, ".csv", "--template", "plain")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),
                             ["t.md", "t_converted2_A.csv", "t_converted2_B.csv", "t_converted_A.csv", "t_converted_B.csv"])


class TestCli(BaseConverterTest):

    def test_from_and_choices_come_from_the_registry(self):
        import contextlib
        import io
        from textconverter.__main__ import build_parser
        args = build_parser().parse_args(["convert", "page", "out.md", "--from", "html", "--template", "dark"])
        self.assertEqual((args.from_format, args.template), ("html", "dark"))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["convert", "a.md", "b.html", "--template", "drak"])
