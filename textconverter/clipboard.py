"""Read a document from the Windows clipboard: the HTML a browser copies, else plain text.

A browser puts a copied selection on the clipboard twice: as plain text and
in the ``HTML Format`` (CF_HTML), whose header gives the byte offsets of the
HTML and the ``SourceURL`` of the page. Both are read with ``ctypes``.
"""
from __future__ import annotations

import ctypes
import re
import sys
import time
from ctypes import wintypes

from .options import TextSource

_CF_UNICODETEXT = 13
_HTML_FORMAT = "HTML Format"
# Another program may hold the clipboard for a moment, as when it has just written to it.
_OPEN_ATTEMPTS = 10
_OPEN_DELAY_S = 0.05
# Tags and comments, images aside: what is left when a copy holds nothing.
_MARKUP = re.compile(r"<!--.*?-->|<(?!img\b)[^>]*>", re.DOTALL | re.IGNORECASE)


class ClipboardError(RuntimeError):
    """The clipboard could not be read, or holds nothing to convert."""


def read_clipboard(from_format: str | None = None) -> TextSource:
    """Return the clipboard's content as a document.

    Args:
        from_format: Format of the clipboard's plain text. None takes the
            HTML a browser copied, with the page's address, and else reads the
            plain text as ``"text"``. A format given always reads the plain
            text, so Markdown copied from a web page is read as Markdown.

    Returns:
        The document, with ``url`` set to the page HTML was copied from.

    Raises:
        ClipboardError: If the platform is not Windows, the clipboard stays
            busy, or it holds no text (an image or a copied file).
        ValueError: If ``from_format`` is unknown or needs a file.
    """
    if sys.platform != "win32":
        raise ClipboardError("Reading the clipboard is supported on Windows only.")
    html, text = _read_windows()
    return clipboard_source(html, text, from_format)


def clipboard_source(html: bytes | None, text: str | None, from_format: str | None) -> TextSource:
    """Choose the document from what the clipboard holds (see ``read_clipboard``).

    Args:
        html: The ``HTML Format`` data, or None.
        text: The plain text, or None.
        from_format: Format of the plain text; None prefers the HTML.

    Returns:
        The document.

    Raises:
        ClipboardError: If the chosen content is missing or blank.
        ValueError: If ``from_format`` is unknown or needs a file.
    """
    if from_format is None and html is not None:
        page, url = parse_cf_html(html)
        if _MARKUP.sub("", page).strip():
            return TextSource(page, "html", url)
    if text and text.strip():
        return TextSource(text, from_format or "text")
    raise ClipboardError("The clipboard holds no text: copy the page or the text first "
                         "(an image or a file cannot be converted from the clipboard).")


def parse_cf_html(data: bytes) -> tuple[str, str | None]:
    """Split ``HTML Format`` data into the HTML and the address of its page.

    The header's offsets count bytes of the UTF-8 data. The whole HTML is
    taken, not only the fragment, since it keeps the selection's enclosing
    elements (Firefox writes them; Chromium writes ``<html><body>``).

    Args:
        data: The clipboard data, header included.

    Returns:
        The HTML, and the ``SourceURL`` when it is an http(s) address (a
        local file's is left out), else None.
    """
    data = data.split(b"\0", 1)[0]
    fields = {}
    for line in data.split(b"<", 1)[0].splitlines():
        key, sep, value = line.decode("ascii", errors="replace").partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    start, end = _offset(fields, "StartHTML"), _offset(fields, "EndHTML")
    if start is None or end is None:
        start, end = _offset(fields, "StartFragment"), _offset(fields, "EndFragment")
    if start is None or end is None or not 0 <= start < end <= len(data):
        index = data.find(b"<")
        start, end = (index, len(data)) if index >= 0 else (len(data), len(data))
    url = fields.get("SourceURL")
    if url and not url.startswith(("http://", "https://")):
        url = None
    return data[start:end].decode("utf-8", errors="replace"), url or None


def _offset(fields: dict[str, str], name: str) -> int | None:
    """A header offset, or None when it is missing, malformed or -1 (not given)."""
    try:
        value = int(fields[name])
    except (KeyError, ValueError):
        return None
    return value if value >= 0 else None


def _read_windows() -> tuple[bytes | None, str | None]:
    """The clipboard's ``HTML Format`` data and plain text, each None when it holds none."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.restype = ctypes.c_size_t

    def data(fmt: int) -> bytes | None:
        if not user32.IsClipboardFormatAvailable(fmt):
            return None
        handle = user32.GetClipboardData(fmt)
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.string_at(pointer, kernel32.GlobalSize(handle))
        finally:
            kernel32.GlobalUnlock(handle)

    html_format = user32.RegisterClipboardFormatW(_HTML_FORMAT)
    for _ in range(_OPEN_ATTEMPTS):
        if user32.OpenClipboard(None):
            break
        time.sleep(_OPEN_DELAY_S)
    else:
        raise ClipboardError("The clipboard is in use by another program; try again.")
    try:
        html = data(html_format) if html_format else None
        raw_text = data(_CF_UNICODETEXT)
    finally:
        user32.CloseClipboard()
    text = raw_text.decode("utf-16-le", errors="replace").split("\0", 1)[0] if raw_text else None
    return html, text
