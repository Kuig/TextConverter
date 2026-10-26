"""Source downloads and the image passes (download, embed, paths), with the network faked.

Usage: python -m unittest discover -s tests -p "test_images.py"
"""
from __future__ import annotations

import io
import os
import tempfile
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch

import textconverter
from textconverter import ConvertOptions
from textconverter._net import DownloadError
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PNG_2 = b"\x89PNG\r\n\x1a\n" + b"\x01" * 16


class _Response:
    def __init__(self, data: bytes, content_type: str | None):
        self.data = data
        self.headers = Message()
        if content_type:
            self.headers["Content-Type"] = content_type

    def read(self) -> bytes:
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Web:
    """Fake ``_net.open_url``: serves ``routes`` (url -> (body, content type) or exception)."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.requested: list[str] = []

    def __call__(self, req, timeout):
        url = req.full_url
        self.requested.append(url)
        answer = self.routes.get(url)
        if answer is None:
            raise urllib.error.URLError(f"no route for {url}")
        if isinstance(answer, Exception):
            raise answer
        return _Response(*answer)


class _WebTest(BaseConverterTest):

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def serve(self, routes: dict) -> _Web:
        web = _Web(routes)
        patcher = patch("textconverter._net.open_url", side_effect=web)
        patcher.start()
        self.addCleanup(patcher.stop)
        return web


class TestSourceDownload(_WebTest):

    def test_charset_from_header(self):
        """A Latin-1 page keeps its accented letters (they used to be dropped)."""
        self.serve({"https://x.test/p": ("<p>caff\xe8</p>".encode("latin-1"), "text/html; charset=ISO-8859-1")})
        self.assertIn("caffè", textconverter.convert("https://x.test/p", "markdown"))

    def test_charset_from_meta_tag(self):
        page = '<html><head><meta charset="windows-1252"></head><body><p>perch\xe9</p></body></html>'
        self.serve({"https://x.test/p": (page.encode("cp1252"), "text/html")})
        self.assertIn("perché", textconverter.convert("https://x.test/p", "markdown"))

    def test_content_type_identifies_a_pdf_without_extension(self):
        """An arXiv-style URL with no .pdf is parsed as a PDF, and no temporary file is left behind."""
        pdf = (INPUT_DIR / "Simple Pdf.pdf").read_bytes()
        self.serve({"https://x.test/pdf/2401.12345": (pdf, "application/pdf")})
        md = textconverter.convert("https://x.test/pdf/2401.12345", "markdown",
                                   ConvertOptions(image_handling="discard"), output_dir=str(self.tmp))
        self.assertIn("Lorem ipsum", md)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_forbidden_source_raises_download_error(self):
        self.serve({"https://x.test/p": urllib.error.HTTPError("https://x.test/p", 403, "Forbidden", Message(), io.BytesIO())})
        with self.assertRaisesRegex(DownloadError, "403"):
            textconverter.convert("https://x.test/p", "markdown")


class TestImageDownload(_WebTest):

    def _page(self, body: str, routes: dict, **kwargs) -> str:
        web = self.serve({"https://x.test/a/page": (f"<html><body>{body}</body></html>".encode(), "text/html"), **routes})
        md = textconverter.convert("https://x.test/a/page", "markdown", ConvertOptions(image_handling="link"),
                                   output_dir=str(self.tmp), image_dir_name="imgs", **kwargs)
        self.requested = web.requested
        return md

    def test_relative_and_protocol_relative_sources_are_downloaded(self):
        md = self._page('<img src="pic.png"><img src="//cdn.test/b.png">',
                        {"https://x.test/a/pic.png": (PNG, "image/png"), "https://cdn.test/b.png": (PNG_2, "image/png")})
        self.assertIn("(imgs/pic.png)", md)
        self.assertIn("(imgs/b.png)", md)

    def test_empty_source_does_not_download_the_page(self):
        self._page('<p>x</p><img src="">', {})
        self.assertEqual(self.requested, ["https://x.test/a/page"])
        self.assertFalse((self.tmp / "imgs").exists())

    def test_octet_stream_keeps_the_url_extension(self):
        md = self._page('<img src="pic.png">', {"https://x.test/a/pic.png": (PNG, "application/octet-stream")})
        self.assertIn("(imgs/pic.png)", md)

    def test_non_image_response_is_not_saved(self):
        md = self._page('<img src="pic.png">', {"https://x.test/a/pic.png": (b"<html>error</html>", "text/html")})
        self.assertIn("(https://x.test/a/pic.png)", md)
        self.assertFalse((self.tmp / "imgs").exists())

    def test_identical_images_share_a_file_and_clashes_get_numbered(self):
        md = self._page('<img src="1/pic.png"><img src="2/pic.png"><img src="3/pic.png">',
                        {"https://x.test/a/1/pic.png": (PNG, "image/png"),
                         "https://x.test/a/2/pic.png": (PNG, "image/png"),
                         "https://x.test/a/3/pic.png": (PNG_2, "image/png")})
        self.assertEqual(md.count("(imgs/pic.png)"), 2)
        self.assertIn("(imgs/pic_1.png)", md)
        self.assertEqual(sorted(p.name for p in (self.tmp / "imgs").iterdir()), ["pic.png", "pic_1.png"])


class TestImagePaths(_WebTest):

    def _source(self) -> Path:
        """A/doc.md with a local image next to it and a remote one."""
        src_dir = self.tmp / "A"
        (src_dir / "img").mkdir(parents=True)
        (src_dir / "img" / "local.png").write_bytes(PNG)
        doc = src_dir / "doc.md"
        doc.write_text("![l](img/local.png)\n\n![r](https://x.test/remote.png)\n", encoding="utf-8")
        self.serve({"https://x.test/remote.png": (PNG_2, "image/png")})
        return doc

    def test_html_in_another_folder_embeds_local_and_remote_images(self):
        """Images used to be looked up next to the source while the download went next to the output."""
        out = self.tmp / "B" / "doc.html"
        out.parent.mkdir()
        textconverter.save_to_file(str(self._source()), str(out))
        html = out.read_text(encoding="utf-8")
        self.assertEqual(html.count('src="data:image/png;base64,'), 2, html)

    def test_markdown_in_another_folder_links_resolve_from_the_output(self):
        out = self.tmp / "B" / "doc.md"
        out.parent.mkdir()
        textconverter.save_to_file(str(self._source()), str(out))
        md = out.read_text(encoding="utf-8")
        self.assertIn("(../A/img/local.png)", md)
        self.assertIn("(doc_images/remote.png)", md)
        self.assertTrue((out.parent / "doc_images" / "remote.png").exists())

    def test_markdown_next_to_the_source_keeps_its_links(self):
        src = self._source()
        out = src.with_name("copy.md")
        textconverter.save_to_file(str(src), str(out))
        self.assertIn("(img/local.png)", out.read_text(encoding="utf-8"))

    def test_relative_images_resolve_from_the_source_whatever_the_cwd(self):
        """convert() used to resolve them against the current directory."""
        src = self._source()
        html = textconverter.convert(str(src), "html", ConvertOptions(image_handling="embed"),
                                     output_dir=str(src.parent))
        self.assertEqual(html.count('src="data:image/png;base64,'), 2)
        self.assertNotEqual(Path(os.getcwd()), src.parent)

    def test_data_urls_are_not_treated_as_files(self):
        from textconverter.images import resolve_local
        self.assertIsNone(resolve_local("data:image/png;base64,AAAA", "x"))
        self.assertIsNone(resolve_local("//host/x.png", "x"))
        self.assertEqual(resolve_local("C:\\img\\a.png", "x"), "C:\\img\\a.png")
