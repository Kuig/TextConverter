"""Helpers shared by the Markdown, HTML and LaTeX renderers."""
from __future__ import annotations

from collections.abc import Callable

from ..ast import Citation, Footnote, Image, Label, Node, Paragraph, Reference, Table, TableCell, Text, walk


def plain_text(nodes: list[Node]) -> str:
    """The text of a list of nodes, descendants included, without formatting."""
    return ''.join(n.content for node in nodes for n in walk(node) if isinstance(n, Text))


def caption_paragraphs(node: Node) -> list[Paragraph]:
    """A ``Table: ...`` / ``Figure: ...`` paragraph for the node's caption and its figures' captions.

    For the renderers that have no caption construct of their own; a table's
    caption comes first, the captions of the figures in a paragraph after it.
    """
    if isinstance(node, Table):
        return [Paragraph(children=[Text(content="Table: "), *node.caption])] if node.caption else []
    return [Paragraph(children=[Text(content="Figure: "), *n.caption])
            for n in walk(node) if isinstance(n, Image) and n.caption]


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
