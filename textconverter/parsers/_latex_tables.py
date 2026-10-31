"""LaTeX tables: their source split into rows and cells, as a ``Table``."""
from __future__ import annotations
import re

from ..ast import Table, TableCell, TableRow
from ._latex_inline import float_caption, parse_inline_latex
from ._latex_macros import ENV_BOUNDARY, extract_macro_args, find_balanced_braces, strip_macro

# The environments that hold a table's rows, and the floats that wrap them.
TABLE_ENVS = ('tabular', 'tabular*', 'tabularx', 'tabulary', 'longtable', 'longtable*', 'xltabular')
TABLE_FLOATS = ('table', 'table*', 'sidewaystable', 'sidewaystable*', 'wraptable')
TABLE_START = re.compile(r'\\begin\{(' + '|'.join(re.escape(env) for env in TABLE_ENVS) + r')\}')
# Table commands that draw and hold no data: the optional arguments each one takes, right
# after its name (any further away they are the text of the next cell), and how many {...}.
_BRACKET = r'(?:\[[^\]]*\])?'
_TABLE_LAYOUT = {
    'hline': ('', 0), 'morecmidrules': ('', 0), 'toprule': (_BRACKET, 0), 'midrule': (_BRACKET, 0),
    'bottomrule': (_BRACKET, 0), 'addlinespace': (_BRACKET, 0), 'cline': ('', 1), 'hhline': ('', 1),
    'cmidrule': (_BRACKET + r'(?:\([^)]*\))?', 1), 'rowcolor': (_BRACKET, 1), 'cellcolor': (_BRACKET, 1),
    'specialrule': ('', 3),
}
_TABLE_LAYOUT_COMMAND = re.compile('|'.join(
    rf'\\{name}(?![a-zA-Z]){options}' + r'\s*\{[^{}]*\}' * arguments
    for name, (options, arguments) in _TABLE_LAYOUT.items()
))
# A cell of several lines, as the LaTeX renderer writes it.
_CELL_LINES = re.compile(r'\\begin\{tabular\}\{@\{\}c@\{\}\}(.*)\\end\{tabular\}', re.DOTALL)
_TABLE_ROW_END = re.compile(r'\\\\\*?(?:\[[^\]]*\])?|\\tabularnewline(?![a-zA-Z])')
# What stands before the text of a \multirow: the optional and the required arguments.
_MULTIROW = re.compile(r'\\multirow(?:\[[^\]]*\])?\s*\{[^{}]*\}(?:\[[^\]]*\])?\s*\{[^{}]*\}(?:\[[^\]]*\])?\s*')
# The end of a longtable's first head, repeated head and feet; the last two parts are not body.
_LONGTABLE_PART = re.compile(r'\\(endfirsthead|endhead|endfoot|endlastfoot)(?![a-zA-Z])')


def _longtable_rows(content: str) -> str:
    """The first head and the body of a longtable, without the repeated head and the feet."""
    parts = _LONGTABLE_PART.split(content)
    heads = dict(zip(parts[1::2], parts[0::2]))
    return heads.get('endfirsthead', heads.get('endhead', '')) + parts[-1]


def _table_cells(content: str, groups: bool = True) -> list[list[str]]:
    """The source of each cell, row by row.

    Rows and cells only end outside groups and nested environments, so
    ``\\multicolumn{2}{c}{a\\\\b}`` is one cell. ``\\&`` is a literal ampersand.
    With braces that do not balance the rows would run together, so they are
    read again with ``groups`` False, which ignores them.
    """
    rows: list[list[str]] = [[]]
    start = pos = depth = 0
    while pos < len(content):
        char = content[pos]
        if char == '\\':
            row_end = _TABLE_ROW_END.match(content, pos) if depth == 0 else None
            boundary = ENV_BOUNDARY.match(content, pos)
            if row_end:
                rows[-1].append(content[start:pos])
                rows.append([])
                start = pos = row_end.end()
            elif boundary:
                depth += 1 if boundary.group(1) == 'begin' else -1
                pos = boundary.end()
            else:
                pos += 2
            continue
        if char == '{' and groups:
            depth += 1
        elif char == '}' and groups:
            depth -= 1
        elif char == '&' and depth == 0:
            rows[-1].append(content[start:pos])
            start = pos + 1
        pos += 1
    if groups and depth:
        return _table_cells(content, groups=False)
    rows[-1].append(content[start:])
    return rows


def _spanned_cell(source: str) -> tuple[str, int]:
    """A cell's source without ``\\multicolumn`` and ``\\multirow``, and the columns it spans."""
    source = source.strip()
    if source.startswith('\\multicolumn'):
        args, _, end = extract_macro_args(source, '\\multicolumn')
        if len(args) >= 3:
            text, _ = _spanned_cell(args[2])
            return text + source[end:], int(args[0]) if args[0].strip().isdigit() else 1
    multirow = _MULTIROW.match(source)
    if multirow and source.startswith('{', multirow.end()):
        text, end = find_balanced_braces(source, multirow.end())
        return _spanned_cell(text)[0] + source[end:], 1
    return source, 1


def parse_latex_table(content: str) -> Table:
    """A table from the content of its environment.

    The first row is the header. As for HTML ``colspan``, the AST has no spans:
    a ``\\multicolumn`` is its text and blank cells, a ``\\multirow`` its text.
    """
    table = Table()
    content = _longtable_rows(content)
    if '\\caption' in content:  # a longtable holds its own caption
        float_caption(content, table)
        content = strip_macro(strip_macro(content, '\\caption'), '\\label')

    for row in _table_cells(_TABLE_LAYOUT_COMMAND.sub('', content)):
        if len(row) == 1 and not row[0].strip():
            continue
        cells: list[TableCell] = []
        for source in row:
            text, span = _spanned_cell(source)
            lines = _CELL_LINES.fullmatch(text.strip())
            cells.append(TableCell(children=parse_inline_latex((lines.group(1) if lines else text).strip())))
            cells.extend(TableCell() for _ in range(span - 1))
        if table.headers or table.rows:
            table.rows.append(TableRow(cells=cells))
        else:
            table.headers = cells
    return table
