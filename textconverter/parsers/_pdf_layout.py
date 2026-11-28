"""Repairs of the page layout in pymupdf4llm's text.

Running heads, footers and page numbers sit in the outermost line at the top or
the bottom of a page. ``page_furniture`` finds them from the PDF's geometry and
``strip_furniture`` removes them from a page's Markdown. ``join_split_paragraphs``
then joins the paragraphs pymupdf4llm ends in the middle of a sentence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..ast import Document, Image, Node, Paragraph, Text, walk
from ..renderers._common import plain_text

# The share of the page height, at the top and at the bottom, where furniture sits.
_BAND = 0.1
# How close two lines must be, as a share of the page height, to stand at the same place.
_SAME_PLACE = 0.01
# A page's furniture is looked for in this many non-blank lines at each end of its Markdown.
_END_LINES = 3
_PAGE_NUMBER = re.compile(r'\d{1,4}')


@dataclass(frozen=True)
class _EdgeLine:
    """A line of the outermost row at the top or bottom of a page."""
    page: int
    text: str
    top: float  # as a share of the page height
    size: float


def page_furniture(pdf_path: str) -> dict[int, list[str]]:
    """The furniture texts of each page (by 1-based page number) of a PDF.

    A line of a page's outermost row, at the top or the bottom within ``_BAND``,
    is furniture when its text, digits aside, stands at an edge of another page
    too; when it is the page number (the page's own, or numbering that keeps
    one offset on two pages); or when it stands at the same place and in the
    same font size as a line that is furniture by those rules (a running head
    that alternates between even and odd pages, the name next to a page number).
    """
    import pymupdf

    with pymupdf.open(pdf_path) as pdf:
        lines = [line for page in pdf for line in _edge_lines(page)]

    pages_by_text: dict[str, set[int]] = {}
    for line in lines:
        pages_by_text.setdefault(_shape(line.text), set()).add(line.page)
    offsets: dict[int, set[int]] = {}
    for line in lines:
        if _PAGE_NUMBER.fullmatch(line.text):
            offsets.setdefault(int(line.text) - line.page, set()).add(line.page)

    def numbered(line: _EdgeLine) -> bool:
        if not _PAGE_NUMBER.fullmatch(line.text):
            return False
        offset = int(line.text) - line.page
        return offset == 0 or len(offsets[offset]) > 1

    known = [line for line in lines if len(pages_by_text[_shape(line.text)]) > 1 or numbered(line)]
    furniture: dict[int, list[str]] = {}
    for line in lines:
        if line in known or any(abs(line.top - k.top) <= _SAME_PLACE and line.size == k.size for k in known):
            furniture.setdefault(line.page, []).append(line.text)
    return furniture


def strip_furniture(page_text: str, furniture: list[str]) -> str:
    """A page's Markdown without the lines, near its ends, made only of furniture texts.

    A line goes only when every letter and digit in it belongs to one of
    ``furniture`` (each used once), so a line with any other text stays; table
    rows and images are never touched.
    """
    if not furniture:
        return page_text
    keys = sorted((_alnum(text) for text in furniture), key=len, reverse=True)
    lines = page_text.split('\n')
    filled = [i for i, line in enumerate(lines) if line.strip()]
    ends = set(filled[:_END_LINES] + filled[-_END_LINES:])
    return '\n'.join(line for i, line in enumerate(lines) if i not in ends or not _is_furniture(line, keys))


def _edge_lines(page) -> list[_EdgeLine]:
    """The lines of the page's outermost row at the top and at the bottom, when they lie within ``_BAND``."""
    height = page.rect.height
    if not height:
        return []
    found: list[_EdgeLine] = []
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            text = ' '.join(''.join(span['text'] for span in line['spans']).split())
            if text:
                size = max(round(span['size'] * 2) / 2 for span in line['spans'])
                found.append(_EdgeLine(page.number + 1, text, line['bbox'][1] / height, size))
    if not found:
        return []
    first = min(line.top for line in found)
    last = max(line.top for line in found)
    return [line for line in found
            if (line.top <= _BAND and line.top - first <= _SAME_PLACE)
            or (line.top >= 1 - _BAND and last - line.top <= _SAME_PLACE)]


def _shape(text: str) -> str:
    """The text with every run of digits alike, so that ``Page 2`` and ``Page 3`` match."""
    return re.sub(r'\d+', '#', text)


def _alnum(text: str) -> str:
    """The letters and digits of a text, lowercased: what is left of it once Markdown and spacing differ."""
    return ''.join(ch for ch in text if ch.isalnum()).lower()


def _is_furniture(line: str, keys: list[str]) -> bool:
    if line.lstrip().startswith(('|', '![')):
        return False
    rest = _alnum(line)
    if not rest:
        return False
    for key in keys:
        rest = rest.replace(key, '', 1)
    return not rest


# What ends a sentence or a clause, before any closing quotes or brackets.
_SENTENCE_END = re.compile(r'[.!?:;]["\'”’»)\]]*$')
# A citation mark opening a paragraph: "[3], [4]. Consequently".
_CITATION_START = re.compile(r'\[\d')


def join_split_paragraphs(doc: Document) -> None:
    """Join the top-level paragraphs that pymupdf4llm ends in the middle of a sentence, in place.

    A paragraph whose text ends without punctuation goes on in the next one
    when that starts in lowercase, with a citation mark (``[3]``) or with
    ``,;)``; one that ends with a comma goes on in the next whatever it starts
    with. A paragraph of bold text only (a title) or with an image is never
    joined.
    """
    out: list[Node] = []
    for block in doc.children:
        previous = out[-1] if out else None
        if isinstance(previous, Paragraph) and isinstance(block, Paragraph) and _continues(previous, block):
            if not _edge_space(previous.children[-1], block.children[0]):
                previous.children.append(Text(content=" "))
            previous.children.extend(block.children)
            continue
        out.append(block)
    doc.children[:] = out


def _continues(first: Paragraph, second: Paragraph) -> bool:
    """Whether ``second`` goes on with the sentence ``first`` leaves open."""
    if not first.children or not second.children or _apart(first) or _apart(second):
        return False
    end, start = plain_text(first.children).rstrip(), plain_text(second.children).lstrip()
    if not end or not start or _SENTENCE_END.search(end):
        return False
    return end.endswith(',') or start[0].islower() or start[0] in ',;)' or bool(_CITATION_START.match(start))


def _apart(paragraph: Paragraph) -> bool:
    """A paragraph that stands on its own: bold text only (a title) or one with an image."""
    if any(isinstance(node, Image) for node in walk(paragraph)):
        return True
    if not all(isinstance(node, Text) for node in paragraph.children):
        return False
    texts = [node for node in paragraph.children if node.content.strip()]
    return bool(texts) and all(node.bold for node in texts)


def _edge_space(last: Node, first: Node) -> bool:
    """Whether a space already separates the two paragraphs' texts."""
    return ((isinstance(last, Text) and last.content[-1:].isspace())
            or (isinstance(first, Text) and first.content[:1].isspace()))
