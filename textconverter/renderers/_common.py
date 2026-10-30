"""Helpers shared by the Markdown, HTML, LaTeX and Word renderers."""
from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable
from dataclasses import replace

from ..ast import Citation, Footnote, Image, Label, Link, Node, Paragraph, Reference, Table, TableCell, Text, walk


# Link schemes that run code when clicked; such links are rendered inert.
_UNSAFE_SCHEMES = ("javascript", "vbscript", "data")


def safe_href(url: str) -> str:
    """The URL, or "#" when its scheme would run code (``javascript:`` and the like)."""
    scheme = urllib.parse.urlparse(url.strip()).scheme.lower()
    return "#" if scheme in _UNSAFE_SCHEMES else url


def plain_text(nodes: list[Node]) -> str:
    """The text of a list of nodes, descendants included, without formatting."""
    return ''.join(n.content for node in nodes for n in walk(node) if isinstance(n, Text))


# Text formatting that the renderers open and close around runs of text,
# outermost first when two start and end together.
EMPHASIS_STYLES = ('strikethrough', 'bold', 'italic')


def text_style(node: Text) -> tuple:
    """Everything about a Text's formatting: equal styles make one run."""
    return node.bold, node.italic, node.strikethrough, node.script


def text_runs(nodes: list[Node]) -> list[Node]:
    """The nodes with adjacent texts of the same formatting merged into one."""
    runs: list[Node] = []
    for node in nodes:
        prev = runs[-1] if runs else None
        if isinstance(node, Text) and isinstance(prev, Text) and text_style(node) == text_style(prev):
            runs[-1] = replace(prev, content=prev.content + node.content)
        else:
            runs.append(node)
    return runs


def style_extent(runs: list[Node], start: int, style: str) -> int:
    """How many runs from ``start`` keep ``style`` (whitespace-only texts do not interrupt it).

    A renderer opens the longest-lasting style first, so the shorter ones nest inside it.
    """
    count = 0
    for node in runs[start:]:
        if not isinstance(node, Text):
            break
        if node.content.strip():
            if not getattr(node, style):
                break
            count += 1
    return count


def split_spaces(content: str) -> tuple[str, str, str]:
    """``(leading whitespace, the rest, trailing whitespace)``: formatting goes around the middle only."""
    return re.match(r'(\s*)(.*?)(\s*)$', content, re.DOTALL).groups()


def figure_image(node: Node) -> Image | None:
    """The captioned or labelled image a paragraph child shows as a figure (alone or as a link's content)."""
    if isinstance(node, Link) and len(node.content) == 1:
        node = node.content[0]
    return node if isinstance(node, Image) and (node.caption or node.label) else None


def caption_paragraphs(node: Node) -> list[Paragraph]:
    """A ``Table: ...`` / ``Figure: ...`` paragraph for the node's caption and its figures' captions.

    For the renderers that have no caption construct of their own; a table's
    caption comes first, the captions of the figures in a paragraph after it.
    A label follows its caption as ``\\label{...}``, which the Markdown parser
    reads back.
    """
    def caption(prefix: str, target: Table | Image) -> Paragraph:
        label = ([Text(content=" ")] if target.caption else []) + [Label(name=target.label)] if target.label else []
        return Paragraph(children=[Text(content=prefix + " "), *target.caption, *label])

    if isinstance(node, Table):
        return [caption("Table:", node)] if node.caption or node.label else []
    return [caption("Figure:", n) for n in walk(node) if isinstance(n, Image) and (n.caption or n.label)]


def table_grid(table: Table) -> tuple[list[TableCell], list[list[TableCell]], int]:
    """Return the table's header cells, its rows and the column count, padded to a rectangle.

    The column count is the widest of the header and the rows; shorter rows
    get empty cells, and nothing is ever cut. The header list stays empty
    when the table has none.
    """
    ncols = max([len(table.headers), *(len(row.cells) for row in table.rows)], default=0)

    def pad(cells: list[TableCell]) -> list[TableCell]:
        return [*cells, *(TableCell() for _ in range(ncols - len(cells)))]

    headers = pad(table.headers) if table.headers else []
    return headers, [pad(row.cells) for row in table.rows], ncols


def latex_reference_macro(
    node: Node,
    inline: Callable[[list[Node]], str],
    escape: Callable[[str], str] = lambda s: s,
) -> str | None:
    """Render a Footnote, Citation, Reference or Label as its LaTeX macro.

    Every output format keeps these as LaTeX macros, which the Markdown and
    LaTeX parsers read back.

    Args:
        node: The node to render.
        inline: Renders a list of inline nodes (the footnote content).
        escape: Escapes the macro arguments for the target format.

    Returns:
        The macro, or None when the node is none of these types.
    """
    if isinstance(node, Footnote):
        return f"\\footnote{{{inline(node.content)}}}"
    if isinstance(node, Citation):
        options = ''.join(f"[{escape(o)}]" for o in node.options)
        return f"\\{node.style}{options}{{{escape(','.join(node.keys))}}}"
    if isinstance(node, Reference):
        return f"\\ref{{{escape(node.label)}}}"
    if isinstance(node, Label):
        return f"\\label{{{escape(node.name)}}}"
    return None
