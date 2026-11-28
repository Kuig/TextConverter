"""Reading a document from the clipboard, with the Windows calls faked.

Usage: python -m unittest discover -s tests -p "test_clipboard.py"
"""
from __future__ import annotations

from unittest.mock import patch

from textconverter.clipboard import ClipboardError, clipboard_source, parse_cf_html, read_clipboard
from _support import BaseConverterTest, setUpModule, tearDownModule


def cf_html(fragment: str, url: str | None = "https://x.test/a/page", context: bool = True) -> bytes:
    """``HTML Format`` data laid out as Chromium writes it, offsets in bytes of the UTF-8 text.

    Without ``context`` the HTML offsets are -1, as the format allows.
    """
    head = "Version:0.9\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\nStartFragment:{:010d}\r\nEndFragment:{:010d}\r\n"
    if url:
        head += f"SourceURL:{url}\r\n"
    before, after = b"<html><body>\r\n<!--StartFragment-->", b"<!--EndFragment-->\r\n</body>\r\n</html>"
    body = fragment.encode("utf-8")
    start = len(head.format(0, 0, 0, 0).encode("ascii"))
    end = start + len(before) + len(body) + len(after)
    html_start, html_end = (start, end) if context else (-1, -1)
    header = head.format(html_start, html_end, start + len(before), start + len(before) + len(body)).encode("ascii")
    return header + before + body + after + b"\0"


class TestCfHtml(BaseConverterTest):

    def test_html_and_page_address_are_read(self):
        html, url = parse_cf_html(cf_html("<p>Caffè <b>forte</b></p>"))
        self.assertEqual(url, "https://x.test/a/page")
        self.assertTrue(html.startswith("<html><body>"))
        self.assertIn("<p>Caffè <b>forte</b></p>", html)
        self.assertTrue(html.endswith("</html>"))

    def test_missing_or_local_address_is_none(self):
        self.assertIsNone(parse_cf_html(cf_html("<p>x</p>", url=None))[1])
        self.assertIsNone(parse_cf_html(cf_html("<p>x</p>", url="file:///C:/page.html"))[1])

    def test_fragment_offsets_serve_when_the_html_ones_are_missing(self):
        self.assertEqual(parse_cf_html(cf_html("<p>x</p>", context=False))[0], "<p>x</p>")

    def test_bad_offsets_fall_back_to_the_first_tag(self):
        data = b"Version:0.9\r\nStartHTML:9999\r\nEndHTML:99999\r\n<p>x</p>"
        self.assertEqual(parse_cf_html(data)[0], "<p>x</p>")


class TestClipboardSource(BaseConverterTest):

    def test_html_is_preferred_without_a_format(self):
        source = clipboard_source(cf_html("<p>x</p>"), "x", None)
        self.assertEqual((source.from_format, source.url), ("html", "https://x.test/a/page"))

    def test_plain_text_without_html_is_text(self):
        source = clipboard_source(None, "# Not a heading", None)
        self.assertEqual((source.text, source.from_format, source.url), ("# Not a heading", "text", None))

    def test_a_format_given_reads_the_plain_text(self):
        """Markdown copied from a web page is on the clipboard as HTML too."""
        source = clipboard_source(cf_html("<p># Title</p>"), "# Title", "markdown")
        self.assertEqual((source.text, source.from_format), ("# Title", "markdown"))

    def test_blank_html_falls_back_to_the_text(self):
        self.assertEqual(clipboard_source(cf_html("<p> </p>"), "words", None).text, "words")

    def test_an_image_alone_is_content(self):
        self.assertEqual(clipboard_source(cf_html('<img src="a.png">'), None, None).from_format, "html")

    def test_nothing_to_convert_raises(self):
        for html, text in ((None, None), (None, "  \r\n"), (cf_html(""), None)):
            with self.subTest(text=text), self.assertRaisesRegex(ClipboardError, "holds no text"):
                clipboard_source(html, text, None)

    def test_binary_format_is_refused(self):
        with self.assertRaisesRegex(ValueError, "needs a file"):
            clipboard_source(None, "x", "pdf")


class TestReadClipboard(BaseConverterTest):

    def test_reads_through_the_windows_calls(self):
        with patch("textconverter.clipboard.sys.platform", "win32"), \
                patch("textconverter.clipboard._read_windows", return_value=(cf_html("<p>x</p>"), "x")):
            self.assertEqual(read_clipboard().from_format, "html")

    def test_other_platforms_are_refused(self):
        with patch("textconverter.clipboard.sys.platform", "linux"), \
                self.assertRaisesRegex(ClipboardError, "Windows only"):
            read_clipboard()
