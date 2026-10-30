"""Tables, charts and SmartArt diagrams of a slide, read into AST nodes."""
from __future__ import annotations

from dataclasses import replace

from lxml import etree

from ..ast import LineBreak, ListBlock, ListItem, Node, Paragraph, Table, TableCell, TableRow, Text
from ._pptx_text import TextReader
from ._pptx_xml import NS, R, a, xpath

_DGM = NS["dgm"]
# Diagram points that structure the diagram instead of carrying text.
_DIAGRAM_LAYOUT_POINTS = ("doc", "pres", "parTrans", "sibTrans")


def read_table(reader: TextReader, table: etree._Element) -> Table:
    """A ``a:tbl``: the first row is the header when the table has the Header Row option.

    A cell merged into its neighbour is an empty cell, as in the Word parser.
    """
    rows = []
    for tr in table.findall(a("tr")):
        cells = []
        for tc in tr.findall(a("tc")):
            merged = tc.get("hMerge") in ("1", "true") or tc.get("vMerge") in ("1", "true")
            cells.append(TableCell(children=[] if merged else _cell(reader, tc)))
        rows.append(cells)
    result = Table()
    props = table.find(a("tblPr"))
    if rows and props is not None and props.get("firstRow") in ("1", "true"):
        result.headers = rows[0]
        rows = rows[1:]
        for cell in result.headers:
            # A header is already set apart; its bold text would be bold twice.
            cell.children = [replace(n, bold=False) if isinstance(n, Text) else n for n in cell.children]
    result.rows = [TableRow(cells=cells) for cells in rows]
    return result


def _cell(reader: TextReader, tc: etree._Element) -> list[Node]:
    """A cell's content as inline nodes, one line per paragraph."""
    body = tc.find(a("txBody"))
    out: list[Node] = []
    for paragraph in body.findall(a("p")) if body is not None else []:
        nodes, _ = reader.inline(paragraph)
        if nodes:
            out.extend([LineBreak()] if out else [])
            out.extend(nodes)
    return out


def read_chart(chart) -> Table | None:
    """A chart's cached data as a table: one row per category, one column per series.

    Returns None when the chart has no categories (a scatter plot, for one).
    """
    plots = list(chart.plots)
    if not plots:
        return None
    categories = [str(c) for c in plots[0].categories]
    series = [s for plot in plots for s in plot.series]
    if not categories or not series:
        return None
    header = [TableCell(children=[])] + [TableCell(children=[Text(content=s.name or "")]) for s in series]
    values = [list(s.values) for s in series]
    rows = []
    for i, category in enumerate(categories):
        cells = [TableCell(children=[Text(content=category)])]
        for column in values:
            number = column[i] if i < len(column) else None
            cells.append(TableCell(children=[Text(content=_number(number))] if number is not None else []))
        rows.append(TableRow(cells=cells))
    caption = []
    if chart.has_title and chart.chart_title.has_text_frame and chart.chart_title.text_frame.text.strip():
        caption = [Text(content=chart.chart_title.text_frame.text.strip())]
    return Table(headers=header, rows=rows, caption=caption)


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def read_diagram(data: etree._Element) -> ListBlock | None:
    """The text of a SmartArt data model as a nested list, in the diagram's own order."""
    texts: dict[str, str] = {}
    root_id = None
    for point in data.findall(f"{{{_DGM}}}ptLst/{{{_DGM}}}pt"):
        kind = point.get("type", "node")
        if kind == "doc":
            root_id = point.get("modelId")
        elif kind not in _DIAGRAM_LAYOUT_POINTS:
            text = " ".join("".join(t.text or "" for t in p.iter(a("t"))).strip()
                            for p in xpath(point, "dgm:t/a:p")).strip()
            texts[point.get("modelId")] = text
    children: dict[str, list[tuple[int, str]]] = {}
    for link in data.findall(f"{{{_DGM}}}cxnLst/{{{_DGM}}}cxn"):
        if link.get("type", "parOf") == "parOf":
            children.setdefault(link.get("srcId"), []).append((int(link.get("srcOrd", "0")), link.get("destId")))
    return _diagram_list(root_id, texts, children)


def _diagram_list(parent: str | None, texts: dict[str, str], children: dict[str, list[tuple[int, str]]]) -> ListBlock | None:
    items = []
    for _, node in sorted(children.get(parent, [])):
        nested = _diagram_list(node, texts, children)
        text = texts.get(node, "")
        if text:
            item = ListItem(children=[Paragraph(children=[Text(content=text)])])
            if nested:
                item.children.append(nested)
            items.append(item)
        elif nested:
            items.extend(nested.items)
    return ListBlock(ordered=False, items=items) if items else None


def relationship_id(frame: etree._Element, xpath_expression: str, attribute: str) -> str | None:
    """The value of a relationship attribute (``r:id``, ``r:dm``, ...) found under a graphic frame."""
    found = xpath(frame, xpath_expression)
    return found[0].get(f"{{{R}}}{attribute}") if found else None
