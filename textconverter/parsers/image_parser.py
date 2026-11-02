from __future__ import annotations
import os
from ..ast import Document, Image, Paragraph


def parse_image(file_path: str, *, output_dir: str | None = None) -> Document:
    """Parse an image file into a Document holding that image, for the image passes to read.

    The image path in the Document is relative to ``output_dir``, like those of
    the other binary parsers.

    Args:
        file_path: Image file path.
        output_dir: Base directory of the document's image paths (current directory if None).

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Image file not found: {file_path}")
    src = _relative(file_path, output_dir or os.getcwd())
    return Document(children=[Paragraph(children=[Image(src=src, alt=os.path.basename(file_path))])])


def _relative(path: str, base_dir: str) -> str:
    """``path`` relative to ``base_dir``, or absolute when it is on another drive."""
    try:
        return os.path.relpath(path, base_dir).replace(os.sep, "/")
    except ValueError:
        return os.path.abspath(path)
