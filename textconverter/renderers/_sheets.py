"""What the CSV and Excel renderers share: the tables of a document and the sheet each one is named after."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..ast import Citation, CodeBlock, CodeInline, Document, Equation, Heading, Node, Reference, Table, walk
from ..parsers._excel_formulas import FORMULA_LANGUAGE
from ._common import latex_reference_macro, plain_text

_MAX_NAME = 31
_INVALID = re.compile(r"[\[\]:*?/\\]")


@dataclass
class Sheet:
    """A table with the name of its sheet and the formula lines written under it."""
    name: str
    table: Table
    formulas: list[str] = field(default_factory=list)


def literal_text(node: Node) -> str | None:
    """What a cell shows for an inline node that holds no ``Text``: code, a ``$formula$``, a reference macro."""
    if isinstance(node, CodeInline):
        return node.code
    if isinstance(node, Equation):
        return f"${node.code}$"
    if isinstance(node, (Citation, Reference)):
        return latex_reference_macro(node, plain_text)
    return None


def _clean(name: str) -> str:
    return _INVALID.sub(" ", name).strip().strip("'")[:_MAX_NAME].strip()


def _unique(name: str, taken: set[str]) -> str:
    """``name`` made different from every name in ``taken`` (compared case-insensitively) with a `` (n)`` suffix."""
    candidate, counter = name, 1
    while candidate.lower() in taken:
        counter += 1
        suffix = f" ({counter})"
        candidate = name[:_MAX_NAME - len(suffix)] + suffix
    return candidate


def collect_sheets(doc: Document) -> list[Sheet]:
    """The document's tables in order, each named after the nearest heading above it.

    A table without a heading above it is ``Sheet<n>``. A code block in the
    ``excel`` language after a table, before the next table or heading, holds
    that table's formulas, one per line.

    Raises:
        ValueError: If the document has no table.
    """
    sheets: list[Sheet] = []
    taken: set[str] = set()
    heading = ""
    current: Sheet | None = None
    for node in walk(doc):
        if isinstance(node, Heading):
            heading, current = _clean(plain_text(node.children)), None
        elif isinstance(node, Table):
            name = _unique(heading or f"Sheet{len(sheets) + 1}", taken)
            taken.add(name.lower())
            current = Sheet(name, node)
            sheets.append(current)
        elif isinstance(node, CodeBlock) and current is not None and node.language == FORMULA_LANGUAGE:
            current.formulas.extend(line for line in node.code.splitlines() if line.strip())
    if not sheets:
        raise ValueError("The document has no table to write as a spreadsheet.")
    return sheets
