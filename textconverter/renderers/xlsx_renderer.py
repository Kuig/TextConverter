"""Excel (.xlsx) renderer: writes the document's tables as sheets with XlsxWriter.

Only tables are kept. Each is a sheet named after the heading above it, its
header the bold first row; the ``excel`` code block under it gives the cells
that hold formulas (see ``parsers._excel_formulas``), written with the cell's
text as their stored result. A cell's text becomes a number, a boolean, a date
or a time when that is exactly how the parser would write the value back, else
it stays text. A footnote in a cell is its comment, a link its hyperlink, an
image in it is anchored to it. Change it only together with ``xlsx_parser.py``.
"""
from __future__ import annotations

import datetime
import io
from dataclasses import dataclass, field

import xlsxwriter

from ..ast import Footnote, Image, LineBreak, Link, Node, TableCell, Text
from ..logger import log_warning
from ..parsers._excel_formulas import expand
from ..parsers.xlsx_parser import format_value
from ._common import plain_text, table_grid, text_style
from ._office import image_bytes
from ._sheets import Sheet, collect_sheets, literal_text

_PLAIN = (False, False, False, None)
_MAX_WIDTH = 60
_MIN_WIDTH = 8
_EPOCH = datetime.datetime(1899, 12, 30)
_DATE, _DATETIME, _TIME = "yyyy-mm-dd", "yyyy-mm-dd hh:mm:ss", "hh:mm:ss"
_MAX_LINK = 2079


@dataclass
class _Cell:
    """What a table cell holds, split by how Excel keeps it."""
    runs: list[tuple[str, tuple]] = field(default_factory=list)
    link: str | None = None
    notes: list[str] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(t for t, _ in self.runs)


def _collect(nodes: list[Node], cell: _Cell, spans: list[tuple[str, int, int]]) -> None:
    for node in nodes:
        if isinstance(node, Text):
            cell.runs.append((node.content, text_style(node)))
        elif isinstance(node, LineBreak):
            cell.runs.append(("\n", _PLAIN))
        elif (literal := literal_text(node)) is not None:
            cell.runs.append((literal, _PLAIN))
        elif isinstance(node, Footnote):
            cell.notes.append(plain_text(node.content).strip())
        elif isinstance(node, Image):
            cell.images.append(node)
        elif isinstance(node, Link):
            start = len(cell.runs)
            _collect(node.content, cell, spans)
            spans.append((node.url, start, len(cell.runs)))


def _read_cell(cell: TableCell) -> _Cell:
    """The cell's text runs (merged by style and trimmed), its single whole-cell link, comments and images."""
    out, spans = _Cell(), []
    _collect(cell.children, out, spans)
    if len(spans) == 1 and spans[0][1:] == (0, len(out.runs)):
        out.link = spans[0][0]
    merged: list[tuple[str, tuple]] = []
    for text, style in out.runs:
        if merged and merged[-1][1] == style:
            merged[-1] = (merged[-1][0] + text, style)
        else:
            merged.append((text, style))
    if merged:
        merged[0] = (merged[0][0].lstrip(), merged[0][1])
        merged[-1] = (merged[-1][0].rstrip(), merged[-1][1])
    out.runs = [(t, s) for t, s in merged if t]
    return out


def _typed(text: str):
    """``(value, number format)`` of a cell's text: a number, boolean, date or time when it reads back the same."""
    if text in ("TRUE", "FALSE"):
        return text == "TRUE", None
    try:
        number = float(text)
        if format_value(number) == text and number == number and abs(number) != float("inf"):
            return (int(number) if number.is_integer() else number), None
    except ValueError:
        pass
    for pattern, fmt, kind in (("%Y-%m-%d", _DATE, "date"), ("%Y-%m-%d %H:%M:%S", _DATETIME, "datetime"),
                               ("%H:%M:%S", _TIME, "time")):
        try:
            moment = datetime.datetime.strptime(text, pattern)
        except ValueError:
            continue
        if kind == "time":
            moment = moment.time()
        if (moment.isoformat(sep=" ") if kind == "datetime" else
                moment.isoformat() if kind == "time" else moment.date().isoformat()) == text:
            return moment, fmt
    return text, None


def _serial(value: datetime.datetime | datetime.time) -> float:
    """The Excel serial number of a date, date and time, or time."""
    if isinstance(value, datetime.time):
        return (value.hour * 3600 + value.minute * 60 + value.second) / 86400
    return (value - _EPOCH).total_seconds() / 86400


class _Writer:
    def __init__(self, workbook: xlsxwriter.Workbook, base_dir: str):
        self.workbook = workbook
        self.base_dir = base_dir
        self._formats: dict[tuple, object] = {}
        self.unreadable = 0

    def format(self, style: tuple = _PLAIN, *, header: bool = False, number: str | None = None, wrap: bool = False):
        """The workbook format for a text style (plus header, number format and wrapping), None for the default."""
        bold, italic, strike, script = style
        key = (bold or header, italic, strike, script, number, wrap)
        if not any(key):
            return None
        if key not in self._formats:
            props = {"bold": key[0], "italic": italic, "font_strikeout": strike, "text_wrap": wrap}
            if script:
                props["font_script"] = 1 if script == "sup" else 2
            if number:
                props["num_format"] = number
            self._formats[key] = self.workbook.add_format({k: v for k, v in props.items() if v})
        return self._formats[key]

    def sheet(self, sheet: Sheet) -> None:
        ws = self.workbook.add_worksheet(sheet.name)
        formulas = {(r, c): f for r, c, f in expand(sheet.formulas)}
        headers, rows, ncols = table_grid(sheet.table)
        widths = [0] * ncols
        for r, cells in enumerate(([headers] if headers else []) + rows):
            header = bool(headers) and r == 0
            for c, cell in enumerate(cells):
                widths[c] = max(widths[c], self.cell(ws, r, c, cell, formulas.pop((r + 1, c + 1), None), header))
        for (r, c), formula in formulas.items():
            ws.write_formula(r - 1, c - 1, formula, None, "")
        for c, width in enumerate(widths):
            ws.set_column(c, c, min(max(width + 2, _MIN_WIDTH), _MAX_WIDTH))

    def cell(self, ws, row: int, col: int, node: TableCell, formula: str | None, header: bool) -> int:
        """Write one cell; return the length of its longest line, to size the column."""
        cell = _read_cell(node)
        text = cell.text
        styles = {s for _, s in cell.runs}
        wrap = "\n" in text
        if header:
            styles = {_PLAIN} if cell.runs else set()
        style = next(iter(styles)) if len(styles) == 1 else _PLAIN

        if formula is not None:
            value, number = _typed(text)
            cached = _serial(value) if isinstance(value, (datetime.datetime, datetime.time)) else value
            ws.write_formula(row, col, formula, self.format(style, header=header, number=number, wrap=wrap), cached)
        elif len(styles) > 1:
            self.rich(ws, row, col, cell, wrap)
        elif cell.link and self.link(ws, row, col, cell, self.format(style, header=header, wrap=wrap)):
            pass
        elif text:
            value, number = _typed(text)
            fmt = self.format(style, header=header, number=number, wrap=wrap)
            if isinstance(value, bool):
                ws.write_boolean(row, col, value, fmt)
            elif isinstance(value, (int, float)):
                ws.write_number(row, col, value, fmt)
            elif isinstance(value, (datetime.datetime, datetime.time)):
                ws.write_datetime(row, col, value, fmt)
            else:
                ws.write_string(row, col, value, fmt)
        elif header:
            ws.write_blank(row, col, None, self.format(header=True))

        if cell.notes:
            note = "\n".join(n for n in cell.notes if n)
            if note:
                ws.write_comment(row, col, note, {"x_scale": 1.5, "y_scale": max(1.0, (note.count("\n") + 1) / 4)})
        for image in cell.images:
            self.image(ws, row, col, image)
        return max((len(line) for line in text.split("\n")), default=0)

    def rich(self, ws, row: int, col: int, cell: _Cell, wrap: bool) -> None:
        parts: list = []
        for text, style in cell.runs:
            fmt = self.format(style)
            if fmt is not None:
                parts.append(fmt)
            parts.append(text)
        cell_format = self.format(wrap=wrap)
        if ws.write_rich_string(row, col, *parts, *([cell_format] if cell_format else [])) != 0:
            ws.write_string(row, col, cell.text, self.format(wrap=wrap))

    def link(self, ws, row: int, col: int, cell: _Cell, fmt) -> bool:
        url = f"internal:{cell.link[1:]}" if cell.link.startswith("#") else cell.link
        return len(url) <= _MAX_LINK and ws.write_url(row, col, url, fmt, cell.text) == 0

    def image(self, ws, row: int, col: int, image: Image) -> None:
        data = image_bytes(image.src, self.base_dir)
        if data is None:
            self.unreadable += 1
            return
        try:
            ws.insert_image(row, col, image.src.rsplit("/", 1)[-1][:60] or "image",
                            {"image_data": io.BytesIO(data), "object_position": 1})
        except Exception:
            self.unreadable += 1


def render_xlsx(doc, path: str, *, base_dir: str | None = None) -> None:
    """Write the document's tables to an Excel file.

    Args:
        doc: The document; only its tables, the ``excel`` code blocks under
            them and the metadata are used.
        path: Where to write the ``.xlsx`` file.
        base_dir: Directory relative image paths resolve against (current directory if None).

    Raises:
        ValueError: If the document has no table.
    """
    sheets = collect_sheets(doc)
    workbook = xlsxwriter.Workbook(path, {"strings_to_numbers": False, "strings_to_formulas": False,
                                          "strings_to_urls": False})
    try:
        properties = {"title": plain_text(doc.title).strip(), "author": plain_text(doc.author).strip()}
        try:
            day = datetime.date.fromisoformat(plain_text(doc.date).strip())
            properties["created"] = datetime.datetime(day.year, day.month, day.day)
        except ValueError:
            pass
        workbook.set_properties(properties)
        writer = _Writer(workbook, base_dir or "")
        for sheet in sheets:
            writer.sheet(sheet)
    finally:
        workbook.close()
    if writer.unreadable:
        log_warning(f"{writer.unreadable} image(s) could not be read and were left out of the workbook.")
