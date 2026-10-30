"""CSV renderer: writes the document's tables as comma-separated text.

Only tables are kept. A cell is its plain text (a line break stays a newline);
footnotes, images and formulas are dropped.
"""
from __future__ import annotations

import csv
import io
import re

from ..ast import Document, Footnote, LineBreak, Table, TableCell, Text, walk
from ..logger import log_warning
from ._common import table_grid
from ._sheets import Sheet, collect_sheets

_FILE_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def cell_text(cell: TableCell) -> str:
    """The text of a table cell: its texts and line breaks, descendants included, footnotes left out."""
    skip: set[int] = set()
    parts: list[str] = []
    for node in walk(cell):
        if isinstance(node, Footnote):
            skip.update(id(n) for n in walk(node))
        if id(node) in skip:
            continue
        if isinstance(node, Text):
            parts.append(node.content)
        elif isinstance(node, LineBreak):
            parts.append("\n")
    return "".join(parts).strip()


def table_rows(table: Table) -> list[list[str]]:
    """The table as rows of text, the header first (when it has one)."""
    headers, rows, _ = table_grid(table)
    return [[cell_text(c) for c in row] for row in ([headers] if headers else []) + rows]


def _csv(table: Table) -> str:
    out = io.StringIO(newline="")
    csv.writer(out, lineterminator="\r\n").writerows(table_rows(table))
    return out.getvalue()


def render_csv(doc: Document) -> str:
    """Render the first table of ``doc`` as CSV text, with a warning when there are more tables.

    Raises:
        ValueError: If the document has no table.
    """
    sheets = collect_sheets(doc)
    if len(sheets) > 1:
        log_warning(f"The document has {len(sheets)} tables; the CSV text holds the first. "
                    "Save to a .csv file to write one file per table.")
    return _csv(sheets[0].table)


def _file_part(name: str) -> str:
    return _FILE_UNSAFE.sub("_", name).strip(" .") or "table"


def render_csv_files(doc: Document) -> list[tuple[str, str]]:
    """Render every table as CSV: a list of ``(suffix, text)`` pairs.

    The suffix is empty for a document with one table, else ``_<sheet name>``
    (to append to the output file's stem).

    Raises:
        ValueError: If the document has no table.
    """
    sheets: list[Sheet] = collect_sheets(doc)
    if len(sheets) == 1:
        return [("", _csv(sheets[0].table))]
    return [(f"_{_file_part(s.name)}", _csv(s.table)) for s in sheets]
