"""CSV parser: reads delimited text into a Document holding one table.

The first row is the table's header. The delimiter is detected among
``, ; <tab> |`` and falls back to a comma; ragged rows are padded to the
widest row.
"""
from __future__ import annotations

import csv
import io

from ..ast import Document, Table, TableCell, TableRow, Text

_DELIMITERS = ",;\t|"
_SAMPLE = 8192


def _delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:_SAMPLE], delimiters=_DELIMITERS).delimiter
    except csv.Error:
        return ","


def table_cell(value: str) -> TableCell:
    """A table cell holding ``value`` as plain text (no children when it is empty)."""
    return TableCell([Text(value)] if value else [])


def parse_csv(text: str) -> Document:
    """Parse CSV (or TSV) text into an AST Document.

    Args:
        text: The delimited text.

    Returns:
        A Document with a single Table whose header is the first row; an
        empty Document when the text has no rows.
    """
    text = text.lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=_delimiter(text)))
    while rows and not any(cell.strip() for cell in rows[-1]):
        rows.pop()
    if not rows:
        return Document()
    width = max(len(row) for row in rows)
    cells = [[table_cell(value) for value in [*row, *[""] * (width - len(row))]] for row in rows]
    return Document([Table(headers=cells[0], rows=[TableRow(row) for row in cells[1:]])])
