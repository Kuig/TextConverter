"""Registry of the document formats, image handling modes, PDF modes and templates.

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
        auto_images: What ``image_handling="auto"`` resolves to when this is
            the output format (None for input-only formats).
        media_types: ``Content-Type`` values that identify the format when
            downloaded; one ending in "/" matches the whole family.
    """
    name: str
    extensions: tuple[str, ...]
    binary: bool = False
    auto_images: str | None = None
    media_types: tuple[str, ...] = ()


INPUT_FORMATS: dict[str, Format] = {f.name: f for f in (
    Format("markdown", (".md", ".markdown", ".txt"), media_types=("text/markdown", "text/x-markdown")),
    Format("html", (".html", ".htm"), media_types=("text/html", "application/xhtml+xml")),
    Format("latex", (".tex", ".latex"), media_types=("application/x-tex", "text/x-tex")),
    Format("json", (".json",), media_types=("application/json",)),
    Format("pdf", (".pdf",), binary=True, media_types=("application/pdf",)),
    Format("image", (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"), binary=True,
           media_types=("image/",)),
)}

OUTPUT_FORMATS: dict[str, Format] = {f.name: f for f in (
    Format("markdown", (".md", ".markdown"), auto_images="link"),
    Format("html", (".html", ".htm"), auto_images="embed"),
    Format("latex", (".tex", ".latex"), auto_images="auto_latex"),
    Format("json", (".json",), auto_images="auto_latex"),
    # Written only by save_to_file(): the HTML rendering, printed.
    Format("pdf", (".pdf",), binary=True, auto_images="embed"),
)}

# Output formats convert() returns as a string.
TEXT_OUTPUT_FORMATS = tuple(name for name, f in OUTPUT_FORMATS.items() if not f.binary)

# "auto_latex" is what "auto" resolves to for LaTeX and JSON output: only
# text, table and formula images are transcribed, and inlined.
IMAGE_HANDLING_MODES = ("auto", "describe", "embed", "link", "discard", "auto_latex")

PDF_MODES = ("text", "raster")

# Accepted HTML template names and the template each one selects.
TEMPLATE_ALIASES: dict[str, str] = {
    "plain": "plain",
    "light": "light", "light-theme": "light", "pretty": "light",
    "dark": "dark", "dark-theme": "dark",
}
TEMPLATES = tuple(TEMPLATE_ALIASES)


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
