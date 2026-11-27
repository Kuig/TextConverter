"""Section titles set as bold body text, read back as headings.

PDF text extraction recognizes headings by font size only, so a title in the
body size and bold comes out as a bold paragraph. ``promote_bold_headings``
turns such paragraphs into ``Heading`` nodes when the document has no heading
structure of its own.
"""
from __future__ import annotations
import re
from ..ast import Document, Heading, ListBlock, Node, Paragraph, Text
from ..renderers._common import plain_text

_MAX_CHARS = 100
_MAX_WORDS = 15
# What an unnumbered title needs after it to count: running text, not a short row.
_MIN_PROSE_CHARS = 60
_MAX_LEVEL = 6

_ARABIC = re.compile(r'(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(?=[^\W\d_])')
_ROMAN = re.compile(r'[IVX]+\.\s+(?=[^\W\d_])')


def promote_bold_headings(doc: Document) -> None:
    """Turn the top-level paragraphs that are bold section titles into headings, in place.

    It runs only when the document has no heading, or one heading before every
    candidate (a title): with more, the document already has its structure. A
    candidate is a short one-line paragraph of bold text only. One that opens
    with a section number (``3.1. Data``, ``2 Methods``, ``IV. Results``) takes
    its level from the number's depth; an unnumbered one must be followed by
    running text, which keeps a bold table header row out, and, unless it is in
    capitals, must not end like a sentence. Levels start at 1, or one below the
    title. The number stays in the heading's text and the bold is removed.
    """
    blocks = doc.children
    candidates = [i for i, block in enumerate(blocks) if _title_text(block) is not None]
    if not candidates:
        return
    headings = [i for i, block in enumerate(blocks) if isinstance(block, Heading)]
    if len(headings) > 1 or (headings and headings[0] > candidates[0]):
        return
    base = blocks[headings[0]].level + 1 if headings else 1
    for i in candidates:
        following = blocks[i + 1] if i + 1 < len(blocks) else None
        depth = _depth(_title_text(blocks[i]), following)
        if depth is not None:
            blocks[i] = _heading(blocks[i], min(base + depth - 1, _MAX_LEVEL))


def _title_text(block: Node) -> str | None:
    """The text of a paragraph that could be a title: short, one line, bold text only."""
    if not isinstance(block, Paragraph) or not block.children:
        return None
    if not all(isinstance(node, Text) and (node.bold or not node.content.strip())
               for node in block.children):
        return None
    text = plain_text(block.children).strip()
    if ('\n' in text or len(text) > _MAX_CHARS or len(text.split()) > _MAX_WORDS
            or not any(c.isalpha() for c in text) or text.endswith((':', ',', ';'))):
        return None
    return text


def _depth(text: str, following: Node | None) -> int | None:
    """The title's depth (1 for a section, 2 for a subsection, ...), or None when it is not one."""
    number = _ARABIC.match(text)
    if number:
        return number.group(1).count('.') + 1
    if _ROMAN.match(text):
        return 1
    if not _is_prose(following):
        return None
    capitals = not any(c.islower() for c in text)
    if not capitals and text.endswith(('.', '!', '?')):
        return None
    return 1


def _is_prose(block: Node | None) -> bool:
    """Whether ``block`` is running text: a list, or a paragraph that is neither short nor a title."""
    if isinstance(block, ListBlock):
        return True
    return (isinstance(block, Paragraph) and _title_text(block) is None
            and len(plain_text(block.children).strip()) >= _MIN_PROSE_CHARS)


def _heading(paragraph: Paragraph, level: int) -> Heading:
    """The paragraph as a heading of ``level``, without bold and without blank text at its ends."""
    children = list(paragraph.children)
    while children and not children[0].content.strip():
        children.pop(0)
    while children and not children[-1].content.strip():
        children.pop()
    for node in children:
        node.bold = False
    return Heading(level=level, children=children)
