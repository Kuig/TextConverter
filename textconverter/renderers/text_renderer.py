"""Render the AST as plain text: a block structure the text parser reads back, and no inline markup.

The conventions live in ``parsers._text_format``. Text formatting is lost: a
link is its text with the URL in parentheses, code and formulas are their
source, and images are left out (the pipeline drops them before rendering).
"""
from __future__ import annotations

from contextvars import ContextVar

from ..ast import (
    Abstract, Bibliography, BlockQuote, Citation, CodeBlock, CodeInline, Document, Equation, Footnote, Heading,
    HorizontalRule, Label, LineBreak, Link, ListBlock, Node, Paragraph, Reference, Table, TableCell, Text,
)
from ..parsers._text_format import (
    CODE_INDENT, METADATA_LABELS, RULE, TITLE_RULE, UNDERLINES, display_width,
)
from ._common import bibliography_paragraphs, caption_paragraphs, latex_reference_macro, table_grid

# The footnotes met while rendering one document, numbered in order.
_FOOTNOTES: ContextVar[list[Footnote] | None] = ContextVar("text_footnotes", default=None)
# The shortest heading underline, so that a short heading is not read as something else.
_MIN_UNDERLINE = 3


def render_text(doc: Document) -> str:
    """Renders an AST Document to plain text.

    The title stands between two rules of ``=``, followed by ``Author:`` and
    ``Date:`` lines; footnotes are ``[n]`` markers with their text at the end.
    """
    footnotes: list[Footnote] = []
    # The metadata is read before the notes at the end: a note there stays a macro
    metadata = _metadata(doc)
    token = _FOOTNOTES.set(footnotes)
    try:
        blocks = [metadata, *(text for _, text in _blocks(doc.children))]
        definitions: list[str] = []
        # A note's content may hold another note, numbered after it
        while len(definitions) < len(footnotes):
            n = len(definitions) + 1
            definitions.append(_lines_of(f"[{n}] " + _inline(footnotes[n - 1].content)))
        blocks.extend(definitions)
    finally:
        _FOOTNOTES.reset(token)
    return '\n\n'.join(filter(None, blocks)) + '\n'


def _metadata(doc: Document) -> str:
    """The title between two rules, then a labelled line for each other field; a line break starts a new line."""
    lines = []
    if doc.title:
        title = _lines_of(_inline(doc.title)).split('\n')
        rule = TITLE_RULE * max(_MIN_UNDERLINE, *(display_width(line) for line in title))
        lines += [rule, *title, rule]
    for name, label in METADATA_LABELS.items():
        nodes = getattr(doc, name)
        if nodes:
            lines.append(_lines_of(f"{label} {_inline(nodes)}"))
    return '\n'.join(filter(None, lines))


def _render_node(node: Node) -> str:
    render = _RENDERERS.get(type(node))
    return render(node) if render else ""


def _blocks(children: list[Node]) -> list[tuple[Node, str]]:
    """Each block that shows something, with its text; rendered once, since a footnote is numbered as it is.

    Consecutive lists that plain text cannot tell apart are written as one:
    bullet lists, and numbered lists whose numbering goes on.
    """
    merged: list[Node] = []
    for child in children:
        previous = merged[-1] if merged else None
        if (isinstance(child, ListBlock) and isinstance(previous, ListBlock) and child.ordered == previous.ordered
                and (not child.ordered or child.start == previous.start + len(previous.items))):
            merged[-1] = ListBlock(ordered=child.ordered, items=previous.items + child.items, start=previous.start)
        else:
            merged.append(child)
    return [(child, text) for child in merged if (text := _render_node(child)).strip()]


def _inline(nodes: list[Node]) -> str:
    return ''.join(_render_node(node) for node in nodes)


def _lines_of(text: str) -> str:
    """Text as lines with no indentation and no blank line: either would change the block it is read as."""
    return '\n'.join(line for line in (line.strip() for line in text.strip().split('\n')) if line)


def _indent(text: str, pad: str) -> str:
    return '\n'.join(pad + line if line else "" for line in text.split('\n'))


def _footnote(node: Footnote) -> str:
    footnotes = _FOOTNOTES.get(None)
    if footnotes is None:  # rendered outside render_text: keep the LaTeX form
        return latex_reference_macro(node, _inline)
    footnotes.append(node)
    return f"[{len(footnotes)}]"


def _link(node: Link) -> str:
    """The link's text, followed by its URL in parentheses when the text is not the URL itself."""
    shown = _inline(node.content).strip()
    if not shown or shown == node.url:
        return node.url
    if node.url in ('mailto:' + shown, 'http://' + shown, 'https://' + shown):
        return shown
    return f"{shown} ({node.url})"


def _heading(node: Heading) -> str:
    text = ' '.join(_lines_of(_inline(node.children)).split('\n'))
    if not text:
        return ""
    return f"{text}\n{UNDERLINES[node.level - 1] * max(_MIN_UNDERLINE, display_width(text))}"


def _paragraph(node: Paragraph) -> str:
    blocks = [_lines_of(_inline(node.children)), *(_paragraph(p) for p in caption_paragraphs(node))]
    return '\n\n'.join(filter(None, blocks))


def _code_block(node: CodeBlock) -> str:
    return _indent(node.code.strip('\n'), ' ' * CODE_INDENT) if node.code.strip() else ""


def _tight_after_first(child: Node) -> bool:
    """Whether a block can follow an item's first paragraph without a blank line: a list that interrupts it."""
    return isinstance(child, ListBlock) and (not child.ordered or child.start == 1)


def _list(node: ListBlock) -> str:
    items: list[str] = []
    loose = False
    for i, item in enumerate(node.items):
        prefix = f"{node.start + i}. " if node.ordered else "- "
        if item.checked is not None:
            prefix += "[x] " if item.checked else "[ ] "
        pad = ' ' * len(prefix.split('[')[0])
        blocks = _blocks(item.children)
        children = [c for c, _ in blocks]
        parts: list[str] = []
        for j, (child, rendered) in enumerate(blocks):
            if j == 0 and not isinstance(child, CodeBlock):
                parts.append(_indent(rendered, pad)[len(pad):])
                continue
            tight = j == 1 and isinstance(children[0], Paragraph) and _tight_after_first(child)
            loose = loose or not tight
            parts.append(('\n' if tight or j == 0 else '\n\n') + _indent(rendered, pad))
        body = ''.join(parts)
        items.append((prefix + body) if body and not body.startswith('\n') else prefix.rstrip() + body)
    return ('\n\n' if loose else '\n').join(items)


def _table(node: Table) -> str:
    headers, rows, ncols = table_grid(node)
    if not ncols:
        return ""
    grid = [[_cell_lines(cell) for cell in row] for row in ([headers] if headers else []) + rows]
    widths = [max(1, *(display_width(line) for row in grid for line in row[j])) for j in range(ncols)]
    border, header_border = ('+' + '+'.join(ch * (w + 2) for w in widths) + '+' for ch in '-=')
    lines = [border]
    for k, row in enumerate(grid):
        for i in range(max(len(cell) for cell in row)):
            texts = [cell[i] if i < len(cell) else "" for cell in row]
            lines.append('|' + '|'.join(f" {t}{' ' * (w - display_width(t))} " for t, w in zip(texts, widths)) + '|')
        lines.append(header_border if headers and k == 0 else border)
    return '\n\n'.join([*(_paragraph(p) for p in caption_paragraphs(node)), '\n'.join(lines)])


def _cell_lines(cell: TableCell) -> list[str]:
    return _lines_of(_inline(cell.children)).split('\n')


def _block_quote(node: BlockQuote) -> str:
    body = '\n\n'.join(text for _, text in _blocks(node.children))
    return _quote(f"[!{node.alert_type}]\n{body}" if node.alert_type else body)


def _abstract(node: Abstract) -> str:
    """A quote opening with "Abstract:", on the first paragraph's first line when there is one."""
    blocks = _blocks(node.children)
    body = '\n\n'.join(text for _, text in blocks)
    joint = '\n' if blocks and isinstance(blocks[0][0], Paragraph) else '\n\n'
    return _quote("Abstract:" + joint + body)


def _quote(text: str) -> str:
    return '\n'.join(f"> {line}" if line else ">" for line in text.split('\n'))


def _equation(node: Equation) -> str:
    if node.inline:
        return f"${node.code}$"
    if node.env:
        return f"$$\n\\begin{{{node.env}}}\n{node.code}\n\\end{{{node.env}}}\n$$"
    return f"$$\n{node.code}\n$$"


_RENDERERS = {
    Heading: _heading,
    Paragraph: _paragraph,
    CodeBlock: _code_block,
    ListBlock: _list,
    Table: _table,
    Text: lambda node: node.content,
    Link: _link,
    CodeInline: lambda node: node.code,
    LineBreak: lambda node: " \\and " if node.author_separator else "\n",
    BlockQuote: _block_quote,
    HorizontalRule: lambda node: RULE,
    Equation: _equation,
    Abstract: _abstract,
    Footnote: _footnote,
    # Commands and entries stay visible as LaTeX, one per paragraph
    Bibliography: lambda node: '\n\n'.join(_paragraph(p) for p in bibliography_paragraphs(node)),
    **{cls: lambda node: latex_reference_macro(node, _inline) for cls in (Citation, Reference, Label)},
}
