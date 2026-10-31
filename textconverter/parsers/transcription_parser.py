"""Parse AI transcriptions of images into the AST.

Vision and OCR models answer in Markdown, but some (GLM-OCR) emit tables as
HTML and may wrap the whole answer in a code fence. These helpers turn such
output into AST nodes so every caller treats it the same way.
"""
from __future__ import annotations
import re
from ..ast import Document, Equation, Node, Table
from ._math import unwrap_math
from .html_parser import parse_html
from .markdown_parser import parse_markdown

_HTML_TABLE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
_FENCE = re.compile(r"^```[\w-]*\n(.*?)\n?```$", re.DOTALL)


def strip_fence(text: str) -> str:
    """Return the text without surrounding whitespace and an enclosing code fence."""
    text = text.strip()
    match = _FENCE.match(text)
    return match.group(1).strip() if match else text


def parse_transcription(text: str) -> Document:
    """Parse a transcription into a Document, routing HTML tables to the HTML parser.

    Args:
        text: Model output: Markdown, possibly with ``<table>`` blocks, possibly fenced.

    Returns:
        A Document whose children follow the order of the transcription.
    """
    text = strip_fence(text)
    doc = Document()
    pos = 0
    for match in _HTML_TABLE.finditer(text):
        doc.children.extend(parse_markdown(text[pos:match.start()], indented_code=False).children)
        for node in parse_html(match.group(0)).children:
            # OCR models write every row with <td>: the first one is the header
            if isinstance(node, Table) and not node.headers and len(node.rows) > 1:
                node.headers = node.rows.pop(0).cells
            doc.children.append(node)
        pos = match.end()
    doc.children.extend(parse_markdown(text[pos:], indented_code=False).children)
    return doc


def transcription_nodes(text: str, category: str | None = None) -> list[Node]:
    """Return the AST blocks for an image's transcription or description.

    Args:
        text: Model output.
        category: The image category; for ``"formula"`` an undelimited answer
            is taken as the formula itself.

    Returns:
        ``[Equation]`` when the whole text is one display formula, otherwise
        the blocks of ``parse_transcription``.
    """
    code = equation_code(text, bare_is_formula=category == "formula")
    if code:
        return [Equation(code=code, inline=False)]
    return parse_transcription(text).children


def normalize_transcription(text: str) -> str:
    """Return the transcription as plain Markdown, converting any HTML table."""
    text = strip_fence(text)
    if not _HTML_TABLE.search(text):
        return text
    from ..renderers.markdown_renderer import render_markdown
    return render_markdown(parse_transcription(text)).strip()


def equation_code(text: str, bare_is_formula: bool = False) -> str | None:
    """Return the LaTeX code when the whole transcription is one display formula.

    Args:
        text: Model output.
        bare_is_formula: Treat text without math delimiters as a formula too
            (the image was classified as one), also accepting inline ``$...$``
            and ``\\(...\\)``.

    Returns:
        The formula without delimiters, or None if the text is not a formula.
        Several delimited formulas (``$$a$$ and $$b$$``) are not one formula.
    """
    code = strip_fence(text)
    inner = unwrap_math(code, display_only=True)
    if inner is not None:
        return inner
    if not bare_is_formula or not code:
        return None
    inner = unwrap_math(code)
    if inner is not None:
        return inner
    if code.startswith("$") or code.endswith("$"):
        inner = code.strip("$")
        return inner.strip() if len(code) > 2 and "$" not in inner else None
    return code
