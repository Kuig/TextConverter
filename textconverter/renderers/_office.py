"""What the Office renderers share: reading an image's bytes and writing the file properties."""
from __future__ import annotations

import datetime
import os

from ..ast import Document, Node
from ..images import data_url_bytes, is_remote, resolve_local
from ..logger import log_warning
from ._common import plain_text, summary_text

_DC_TERMS = "http://purl.org/dc/terms/"
# The longest text Office keeps in a file property.
_MAX_PROPERTY = 255


def image_bytes(src: str, base_dir: str) -> bytes | None:
    """The bytes of an image source (a data URL or a local path), None when it cannot be read.

    A relative path is looked up under ``base_dir`` and then the current directory; remote images are not fetched.
    """
    if src.startswith("data:"):
        return data_url_bytes(src)
    if not src or is_remote(src):
        return None
    for base in (base_dir, os.getcwd()):
        path = resolve_local(src, base)
        if path and os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()
    return None


def property_text(nodes: list[Node], name: str) -> str:
    """A metadata field as a file property: one line of at most 255 characters, cut at a word."""
    text = summary_text(nodes)
    if len(text) <= _MAX_PROPERTY:
        return text
    log_warning(f"The {name} is too long for the file properties and was cut; the document keeps it whole.")
    return text[:_MAX_PROPERTY + 1].rsplit(" ", 1)[0].rstrip(" ;,")


def write_properties(props, doc: Document) -> None:
    """Set the title, author and date of an Office file's core properties from the document's metadata."""
    props.title = property_text(doc.title, "title")
    props.author = property_text(doc.author, "author")
    props.last_modified_by = props.comments = props.subject = props.keywords = ""
    try:
        day = datetime.date.fromisoformat(plain_text(doc.date).strip())
    except ValueError:
        day = None
    if day is None:
        # The template's own dates would be read back as the document's date.
        for name in ("created", "modified"):
            for el in props._element.findall(f"{{{_DC_TERMS}}}{name}"):
                props._element.remove(el)
    else:
        props.created = props.modified = datetime.datetime(day.year, day.month, day.day,
                                                           tzinfo=datetime.timezone.utc)
