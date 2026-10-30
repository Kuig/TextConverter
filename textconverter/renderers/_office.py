"""What the Word and PowerPoint renderers share: reading an image's bytes and writing the file properties."""
from __future__ import annotations

import base64
import datetime
import os
import urllib.parse

from ..ast import Document
from ..images import is_remote, resolve_local
from ._common import plain_text

_DC_TERMS = "http://purl.org/dc/terms/"


def image_bytes(src: str, base_dir: str) -> bytes | None:
    """The bytes of an image source (a data URL or a local path), None when it cannot be read.

    A relative path is looked up under ``base_dir`` and then the current directory; remote images are not fetched.
    """
    if src.startswith("data:"):
        header, _, data = src.partition(",")
        return base64.b64decode(data) if header.endswith(";base64") else urllib.parse.unquote_to_bytes(data)
    if not src or is_remote(src):
        return None
    for base in (base_dir, os.getcwd()):
        path = resolve_local(src, base)
        if path and os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()
    return None


def write_properties(props, doc: Document) -> None:
    """Set the title, author and date of an Office file's core properties from the document's metadata."""
    props.title = plain_text(doc.title).strip()
    props.author = plain_text(doc.author).strip()
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
