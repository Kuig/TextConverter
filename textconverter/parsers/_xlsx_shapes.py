"""The text boxes of a workbook, read from its drawing parts: openpyxl does not load shapes."""
from __future__ import annotations

import posixpath
import zipfile
from collections import Counter

from lxml import etree
from openpyxl.utils import get_column_letter

from ..ast import BlockQuote, Paragraph, Text
from ._docx_blocks import Flow
from ._office import BoxFrame, box_preamble
from ._pptx_text import TextReader, dominant_font
from ._pptx_xml import a

_XDR = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"
_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RELATIONS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_ANCHORS = (f"{_XDR}twoCellAnchor", f"{_XDR}oneCellAnchor")


class _NoRelationships:
    """Stands for the part ``TextReader`` resolves links with: a shape's links are not read."""
    rels: dict = {}


def _relations(archive: zipfile.ZipFile, part: str) -> list[etree._Element]:
    """The relationships of a part of the package."""
    path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    return list(etree.fromstring(archive.read(path))) if path in archive.namelist() else []


def _target(part: str, relation: etree._Element) -> str:
    """The package path a relationship of ``part`` points to."""
    target = relation.get("Target", "")
    if target.startswith("/"):
        return target[1:]
    return posixpath.normpath(posixpath.join(posixpath.dirname(part), target))


def _cell(marker: etree._Element) -> str:
    """The name of the cell a ``xdr:from`` or ``xdr:to`` points to."""
    column = int(marker.findtext(f"{_XDR}col", "0")) + 1
    return f"{get_column_letter(column)}{int(marker.findtext(f'{_XDR}row', '0')) + 1}"


def _cells(anchor: etree._Element) -> str | None:
    start, end = anchor.find(f"{_XDR}from"), anchor.find(f"{_XDR}to")
    if start is None:
        return None
    return f"{_cell(start)}:{_cell(end)}" if end is not None else _cell(start)


def _quote(body: etree._Element, cells: str | None, index: int) -> BlockQuote:
    flow = Flow()
    TextReader(_NoRelationships(), Counter()).blocks(body, flow, index, [])
    flow.close()
    frame = BoxFrame(cells=cells, font=dominant_font(body, []))
    return BlockQuote(children=[Paragraph(children=[Text(content=box_preamble(frame))]), *flow.out])


def _drawing_boxes(archive: zipfile.ZipFile, part: str) -> list[BlockQuote]:
    boxes: list[BlockQuote] = []
    for anchor in etree.fromstring(archive.read(part)):
        if anchor.tag not in _ANCHORS:
            continue
        for shape in anchor.iter(f"{_XDR}sp"):
            body = shape.find(f"{_XDR}txBody")
            if body is not None and "".join(t.text or "" for t in body.iter(a("t"))).strip():
                boxes.append(_quote(body, _cells(anchor), len(boxes)))
    return boxes


def read_text_boxes(file_path: str) -> dict[str, list[BlockQuote]]:
    """Each sheet's text boxes as quotes headed by the cells they cover, by sheet name.

    Args:
        file_path: Path of the ``.xlsx`` file.
    """
    boxes: dict[str, list[BlockQuote]] = {}
    with zipfile.ZipFile(file_path) as archive:
        book = "xl/workbook.xml"
        sheets = {r.get("Id"): _target(book, r) for r in _relations(archive, book)}
        for sheet in etree.fromstring(archive.read(book)).iter(f"{_MAIN}sheet"):
            part = sheets.get(sheet.get(_REL_ID))
            if part is None:
                continue
            for relation in _relations(archive, part):
                if relation.get("Type", "").endswith("/drawing") and relation.tag == f"{_RELATIONS}Relationship":
                    found = _drawing_boxes(archive, _target(part, relation))
                    if found:
                        boxes.setdefault(sheet.get("name"), []).extend(found)
    return boxes
