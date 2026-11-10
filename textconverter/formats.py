"""Registry of the document formats, image handling and output modes, PDF modes and templates.

The CLI, the MCP tools, the GUI and ``api.convert()`` all read their choices
from here, so a format or option value is declared once.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Format:
    """A document format TextConverter reads or writes.

    Attributes:
        name: Format name used across the API (``from_format``/``to_format``).
        extensions: File extensions, lowercase with the dot; the first is the
            preferred one.
        binary: Parsed from a file rather than from text (PDF, images).
        image_outputs: How the format can hold images, when it is the output
            format: ``"embed"`` and ``"link"``, the default first; empty when
            it holds none.
        media_types: ``Content-Type`` values that identify the format when
            downloaded; one ending in "/" matches the whole family.
    """
    name: str
    extensions: tuple[str, ...]
    binary: bool = False
    image_outputs: tuple[str, ...] = ()
    media_types: tuple[str, ...] = ()


INPUT_FORMATS: dict[str, Format] = {f.name: f for f in (
    Format("markdown", (".md", ".markdown", ".txt"), media_types=("text/markdown", "text/x-markdown")),
    Format("html", (".html", ".htm"), media_types=("text/html", "application/xhtml+xml")),
    Format("latex", (".tex", ".latex"), media_types=("application/x-tex", "text/x-tex")),
    # The AST as JSON. It has an extension of its own: a .json file is not necessarily an AST.
    Format("json", (".aston",), media_types=("application/json",)),
    Format("pdf", (".pdf",), binary=True, media_types=("application/pdf",)),
    Format("docx", (".docx",), binary=True, media_types=(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",)),
    Format("pptx", (".pptx",), binary=True, media_types=(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",)),
    Format("csv", (".csv", ".tsv"), media_types=("text/csv", "text/tab-separated-values")),
    Format("xlsx", (".xlsx",), binary=True, media_types=(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",)),
    Format("image", (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"), binary=True,
           media_types=("image/",)),
)}

OUTPUT_FORMATS: dict[str, Format] = {f.name: f for f in (
    Format("markdown", (".md", ".markdown"), image_outputs=("link", "embed")),
    Format("html", (".html", ".htm"), image_outputs=("embed", "link")),
    # LaTeX cannot hold an image in its text.
    Format("latex", (".tex", ".latex"), image_outputs=("link",)),
    Format("json", (".aston",), image_outputs=("embed", "link")),
    # Written only by save_to_file(): the HTML rendering, printed.
    Format("pdf", (".pdf",), binary=True, image_outputs=("embed",)),
    # Written only by save_to_file(): the AST rendered straight to a Word file.
    Format("docx", (".docx",), binary=True, image_outputs=("embed",)),
    # Written only by save_to_file(): the AST rendered straight to a PowerPoint file.
    Format("pptx", (".pptx",), binary=True, image_outputs=("embed",)),
    # Tables only. The CSV text is the first table; save_to_file() writes one file per table.
    Format("csv", (".csv",)),
    # Written only by save_to_file(): the AST's tables as sheets of an Excel file.
    Format("xlsx", (".xlsx",), binary=True, image_outputs=("embed",)),
)}

# Output formats convert() returns as a string (the binary ones go through save_to_file()).
TEXT_OUTPUT_FORMATS = tuple(name for name, f in OUTPUT_FORMATS.items() if not f.binary)

# What happens to the images in the document (see the README's Image Handling).
IMAGE_HANDLING_CHOICES = ("auto", "discard", "keep", "split", "transcribe", "describe", "replace", "append")
# How the images left in the document are written to the output.
IMAGE_OUTPUT_CHOICES = ("auto", "embed", "link")

PDF_MODES = ("text", "raster")

# Accepted HTML template names and the template each one selects.
TEMPLATE_ALIASES: dict[str, str] = {
    "plain": "plain",
    "light": "light", "light-theme": "light", "pretty": "light",
    "dark": "dark", "dark-theme": "dark",
}
TEMPLATES = tuple(TEMPLATE_ALIASES)
# One name per template, for menus.
TEMPLATE_CHOICES = ("plain", "light", "dark")


def _infer(path: str, formats: dict[str, Format]) -> str | None:
    ext = pathlib.PurePath(path).suffix.lower()
    return next((f.name for f in formats.values() if ext in f.extensions), None)


def infer_input_format(path: str) -> str | None:
    """Return the input format matching the path's extension, or None."""
    return _infer(path, INPUT_FORMATS)


def infer_input_format_from_media_type(media_type: str) -> str | None:
    """Return the input format a ``Content-Type`` media type identifies, or None."""
    for f in INPUT_FORMATS.values():
        for mt in f.media_types:
            if media_type == mt or (mt.endswith("/") and media_type.startswith(mt)):
                return f.name
    return None


def infer_output_format(path: str) -> str | None:
    """Return the output format matching the path's extension, or None."""
    return _infer(path, OUTPUT_FORMATS)


def check_choice(kind: str, value: str, choices: tuple[str, ...] | dict) -> None:
    """Raise ValueError when ``value`` is not one of ``choices``.

    Args:
        kind: What the value is, for the message (e.g. "image_handling").
        value: The value to check.
        choices: The accepted values.
    """
    if value not in choices:
        raise ValueError(f"Unknown {kind} '{value}'; expected one of: {', '.join(choices)}.")
