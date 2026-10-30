"""The formula lines written under a table: ``D2:D100 = B2*C2``.

A line is a range of cells (or one cell), `` = ``, and the formula of the
range's first cell without its leading ``=``. The other cells hold the same
formula moved by their offset (relative references shift, ``$`` ones stay), so
a column that repeats one formula takes one line. The Excel parser writes the
lines (``compress``) and the Excel renderer reads them (``expand``).
"""
from __future__ import annotations

from collections.abc import Iterator

from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter, range_boundaries

# The language of the code block that holds a table's formula lines.
FORMULA_LANGUAGE = "excel"
_SEPARATOR = " = "


def _name(row: int, col: int) -> str:
    return f"{get_column_letter(col)}{row}"


def _moved(formula: str, row: int, col: int, to_row: int, to_col: int) -> str:
    """``formula`` of cell (row, col) as it reads in cell (to_row, to_col)."""
    return Translator(formula, origin=_name(row, col)).translate_formula(_name(to_row, to_col))


def _same(formula: str, row: int, col: int, other: str, to_row: int, to_col: int) -> bool:
    try:
        return _moved(formula, row, col, to_row, to_col) == other
    except Exception:  # an expression the translator cannot read is never merged
        return False


def _runs(cells: dict[tuple[int, int], str], step: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    """Maximal runs ``(row, col, row_end, col_end)`` of cells along ``step`` that repeat their first formula."""
    taken: set[tuple[int, int]] = set()
    runs = []
    for (row, col) in sorted(cells):
        if (row, col) in taken:
            continue
        end = (row, col)
        while True:
            nxt = (end[0] + step[0], end[1] + step[1])
            if nxt not in cells or nxt in taken or not _same(cells[(row, col)], row, col, cells[nxt], *nxt):
                break
            end = nxt
        taken.update((r, c) for r in range(row, end[0] + 1) for c in range(col, end[1] + 1))
        runs.append((row, col, *end))
    return runs


def compress(cells: dict[tuple[int, int], str]) -> list[str]:
    """The formula lines of a sheet.

    Args:
        cells: ``(row, column)`` (1-based) to the cell's formula, with its leading ``=``.

    Returns:
        One line per run of cells that repeat a formula down a column; single
        cells left over in a row are merged along the row.
    """
    lines: list[tuple[tuple[int, int], str]] = []
    singles: dict[tuple[int, int], str] = {}
    for row, col, row_end, col_end in _runs(cells, (1, 0)):
        if row_end == row:
            singles[(row, col)] = cells[(row, col)]
        else:
            lines.append(((row, col), f"{_name(row, col)}:{_name(row_end, col_end)}"
                          f"{_SEPARATOR}{cells[(row, col)][1:]}"))
    for row, col, row_end, col_end in _runs(singles, (0, 1)):
        where = _name(row, col) if col_end == col else f"{_name(row, col)}:{_name(row_end, col_end)}"
        lines.append(((row, col), f"{where}{_SEPARATOR}{singles[(row, col)][1:]}"))
    return [line for _, line in sorted(lines)]


def expand(lines: list[str]) -> Iterator[tuple[int, int, str]]:
    """The formula of every cell the lines cover: ``(row, column, formula with its leading =)``.

    A line that is not ``<range> = <formula>``, or whose range is not valid,
    is skipped; a later line replaces an earlier one on the same cell.
    """
    cells: dict[tuple[int, int], str] = {}
    for line in lines:
        where, sep, formula = line.strip().partition(_SEPARATOR)
        if not sep or not formula.strip():
            continue
        try:
            min_col, min_row, max_col, max_row = range_boundaries(where.strip().upper())
        except ValueError:
            continue
        if None in (min_col, min_row, max_col, max_row):
            continue
        origin = "=" + formula.strip()
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                try:
                    cells[(row, col)] = _moved(origin, min_row, min_col, row, col)
                except Exception:
                    cells[(row, col)] = origin
    for (row, col), formula in sorted(cells.items()):
        yield row, col, formula
