"""Helpers shared by the Markdown, HTML and LaTeX renderers."""
from __future__ import annotations

from collections.abc import Callable

from ..ast import Citation, Footnote, Label, Node, Reference, Table, TableCell


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
        return f"\\{node.style}{{{escape(','.join(node.keys))}}}"
    if isinstance(node, Reference):
        return f"\\ref{{{escape(node.label)}}}"
    if isinstance(node, Label):
        return f"\\label{{{escape(node.name)}}}"
    return None
