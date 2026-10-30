"""Word (.docx) parser: reads a document with python-docx into the AST.

Styles are recognized by name (python-docx maps Word's built-in names to their
English form), never by style id, which Word localizes. Features Word has and
the AST does not (underline, highlight, headers and footers, shapes) are
dropped, with a single warning listing them.
"""
from __future__ import annotations

import re
import zipfile
from collections import Counter
from dataclasses import dataclass, replace

from lxml import etree

from ..ast import (
    BlockQuote, CodeInline, Document, Equation, Footnote, Heading, HorizontalRule, Image, LineBreak, Link, Node,
    Paragraph, Table, TableCell, TableRow, Text,
)
from ..images import ImageStore
from ..logger import log_warning
from ..renderers._common import text_runs
from ._docx_blocks import Field, Flow, Inline, ListRef, Numbering, tidy
from ._docx_xml import NS, M, OFFICE, R, flag, local, val, w, xpath
from ._latex_macros import lift_macros
from ._math import split_math_env
from ._office import MONOSPACE, is_code
from ._omml import omml_to_latex

_CODE_STYLES = frozenset({"code", "source code", "preformatted text", "html preformatted", "macro text"})
_QUOTE_STYLES = frozenset({"quote", "intense quote", "block text"})
_HEADING = re.compile(r"^Heading (\d)$")
_LIST_STYLE = re.compile(r"^List (Bullet|Number)(?: (\d))?$")
_HYPERLINK_INSTR = re.compile(r'HYPERLINK\s+(?:"([^"]*)")?(?:.*?\\l\s+"([^"]*)")?', re.IGNORECASE)
# Notes that Word keeps in the notes part but are layout, not content.
_NOTE_LAYOUT = ("separator", "continuationSeparator", "continuationNotice")


_ALIGNED = re.compile(r"^\\begin\{aligned\} (.*) \\end\{aligned\}$", re.DOTALL)


def display_equation(math: etree._Element) -> Equation:
    """A display equation; a whole equation array is an ``align`` environment."""
    code = omml_to_latex(math)
    aligned = _ALIGNED.match(code)
    if aligned:
        return Equation(code=aligned.group(1), inline=False, env="align")
    return Equation(code=code, inline=False)


@dataclass
class _RunFormat:
    bold: bool = False
    italic: bool = False
    strike: bool = False
    script: str | None = None
    code: bool = False
    equation: bool = False
    underline: bool = False
    highlight: bool = False


def parse_docx(
    file_path: str,
    *,
    output_dir: str | None = None,
    image_dir_name: str | None = None,
    write_images: bool = True,
) -> Document:
    """Parse a Word document into an AST Document.

    Args:
        file_path: Path of the ``.docx`` file.
        output_dir: Base directory for the extracted images (current directory if None).
        image_dir_name: Image subdirectory name inside ``output_dir``.
        write_images: Extract the embedded images; when False they are left out.

    Raises:
        ValueError: If the file is not a readable ``.docx`` document.
    """
    import docx
    from docx.opc.exceptions import PackageNotFoundError
    try:
        document = docx.Document(file_path)
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise ValueError(f"Not a readable Word (.docx) document: {file_path} ({exc})") from exc
    return _Reader(document, output_dir, image_dir_name, write_images).read()


class _Reader:
    """Reads one python-docx document; see ``parse_docx``."""

    def __init__(self, document, output_dir: str | None, image_dir_name: str | None, write_images: bool):
        from docx.enum.style import WD_STYLE_TYPE
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
        self.document = document
        self.part = document.part
        self._style_types = WD_STYLE_TYPE
        self._rt = RT
        self._store = ImageStore(output_dir, image_dir_name)
        self.write_images = write_images
        self.dropped: Counter[str] = Counter()
        self._styles: dict[tuple[str, str | None], object] = {}
        self._notes: dict[str, tuple[object, dict[str, etree._Element]]] = {}
        self._numbering: Numbering | None = None
        self._title: list[Node] = []

    # ---- document -------------------------------------------------------

    def read(self) -> Document:
        body = self.document.element.body
        children = self._blocks(body, top=True)
        props = self.document.core_properties
        doc = Document(children=children, title=self._title)
        if not doc.title and props.title:
            doc.title = [Text(content=props.title)]
        if props.author:
            doc.author = [Text(content=props.author)]
        if props.created:
            doc.date = [Text(content=props.created.date().isoformat())]
        self._note_headers_and_footers()
        if self.dropped:
            what = ", ".join(f"{name} ({count})" if count > 1 else name for name, count in self.dropped.items())
            log_warning(f"Word features without a counterpart were dropped: {what}.")
        return doc

    def _note_headers_and_footers(self) -> None:
        for kind in ("header", "footer"):
            for section in self.document.sections:
                part = getattr(section, kind)
                if not part.is_linked_to_previous and any(p.text.strip() for p in part.paragraphs):
                    self.dropped[kind] += 1
                    break

    # ---- styles ---------------------------------------------------------

    def _style(self, style_id: str | None, kind: str):
        key = (kind, style_id)
        if key not in self._styles:
            self._styles[key] = self.document.styles.get_by_id(style_id, getattr(self._style_types, kind))
        return self._styles[key]

    def _paragraph_style(self, p: etree._Element):
        pstyle = p.find(f"{w('pPr')}/{w('pStyle')}")
        return self._style(val(pstyle), "PARAGRAPH")

    def _style_numbering(self, style) -> tuple[str, int] | None:
        """The list a paragraph style applies (``numId``, level), looking through its base styles."""
        while style is not None:
            pr = style.element.pPr
            if pr is not None and pr.numPr is not None and pr.numPr.numId is not None:
                level = pr.numPr.ilvl.val if pr.numPr.ilvl is not None else 0
                return str(pr.numPr.numId.val), int(level)
            style = style.base_style
        return None

    def _list_ref(self, p: etree._Element, style) -> ListRef | None:
        """The list the paragraph belongs to, or None."""
        num_pr = p.find(f"{w('pPr')}/{w('numPr')}")
        if num_pr is not None:
            num_id = val(num_pr.find(w("numId")), "0")
            if num_id == "0":
                return None
            level = int(val(num_pr.find(w("ilvl")), "0"))
            ordered, start = self._numbering_model().level(num_id, level)
            return ListRef(num_id, level, ordered, start)
        named = _LIST_STYLE.match(style.name or "") if style is not None else None
        if named:
            return ListRef(("style", named.group(1)), int(named.group(2) or 1) - 1, named.group(1) == "Number")
        numbered = self._style_numbering(style)
        if numbered and numbered[0] != "0":
            ordered, start = self._numbering_model().level(*numbered)
            return ListRef(numbered[0], numbered[1], ordered, start)
        return None

    def _numbering_model(self) -> Numbering:
        if self._numbering is None:
            try:
                root = etree.fromstring(self.document.part.part_related_by(self._rt.NUMBERING).blob)
            except KeyError:
                root = None
            self._numbering = Numbering(root)
        return self._numbering

    # ---- blocks ---------------------------------------------------------

    @staticmethod
    def _body_elements(parent: etree._Element):
        """The paragraphs and tables of a body or text box, through content controls."""
        for child in parent:
            tag = child.tag if isinstance(child.tag, str) else ""
            if tag in (w("p"), w("tbl")):
                yield child
            elif tag == w("sdt"):
                content = child.find(w("sdtContent"))
                if content is not None:
                    yield from _Reader._body_elements(content)

    def _blocks(self, parent: etree._Element, top: bool = False) -> list[Node]:
        """The blocks of a body or text box."""
        flow = Flow()
        elements = list(self._body_elements(parent))
        for index, el in enumerate(elements):
            if el.tag == w("tbl"):
                flow.table(self._table(el))
                continue
            style = self._paragraph_style(el)
            name = (style.name if style is not None else "") or ""
            lowered = name.lower()
            nodes, ctx = self._inline_paragraph(el)
            followed_by_table = index + 1 < len(elements) and elements[index + 1].tag == w("tbl")
            list_ref = self._list_ref(el, style)
            if lowered == "caption" and nodes:
                flow.caption(nodes, ctx, followed_by_table)
            elif list_ref is not None:
                flow.list_item(list_ref, self._flatten(nodes, ctx))
            elif lowered == "title" and top and not self._title and nodes:
                flow.close()
                self._title = nodes
                flow.out.extend(ctx.extra)
            elif lowered == "equation display" and (code := self._plain_text(el).strip()):
                body, env = split_math_env(code)
                flow.leaf(Equation(code=body, inline=False, env=env))
            elif _HEADING.match(name) and nodes:
                flow.leaf(Heading(level=min(int(_HEADING.match(name).group(1)), 6), children=nodes), ctx.extra)
            elif lowered in _QUOTE_STYLES and nodes:
                flow.group("quote", Paragraph(children=nodes), ctx.extra)
            elif lowered == "abstract" and nodes:
                flow.group("abstract", Paragraph(children=nodes), ctx.extra)
            elif lowered in _CODE_STYLES or is_code(nodes):
                flow.group("code", self._plain_text(el, keep_tabs=True).rstrip(), ctx.extra)
            elif nodes:
                flow.leaf(Paragraph(children=nodes), ctx.extra)
            else:
                flow.close()
                if el.find(f"{w('pPr')}/{w('pBdr')}/{w('bottom')}") is not None:
                    flow.out.append(HorizontalRule())
                flow.out.extend(ctx.extra)
        flow.close()
        return flow.out

    def _flatten(self, nodes: list[Node], ctx: Inline) -> list[Node]:
        """The inline nodes of a paragraph that cannot hold blocks: display equations stay in the text."""
        extras = []
        for node in ctx.extra:
            if isinstance(node, Equation):
                extras.append(replace(node, inline=True))
            else:
                self.dropped["text box"] += 1
        return [*nodes, *extras]

    def _plain_text(self, p: etree._Element, keep_tabs: bool = False) -> str:
        """The text of a paragraph's runs, ``\\n`` for a line break; tabs stay when ``keep_tabs``."""
        parts = []
        for run in p.iter(w("r")):
            if any(a.tag == w("del") for a in run.iterancestors()):
                continue
            for child in run:
                tag = local(child)
                if tag == "t":
                    parts.append(child.text or "")
                elif tag == "tab":
                    parts.append("\t" if keep_tabs else " ")
                elif tag in ("br", "cr") and child.get(w("type")) not in ("page", "column"):
                    parts.append("\n")
        return "".join(parts)

    # ---- tables ---------------------------------------------------------

    def _table(self, tbl: etree._Element) -> Table:
        rows = []
        for tr in tbl.findall(w("tr")):
            cells: list[TableCell] = []
            for tc in tr.findall(w("tc")):
                props = tc.find(w("tcPr"))
                merge = props.find(w("vMerge")) if props is not None else None
                continued = merge is not None and val(merge, "continue") != "restart"
                span = int(val(props.find(w("gridSpan")), "1")) if props is not None else 1
                cells.append(TableCell(children=[] if continued else self._cell(tc)))
                cells.extend(TableCell() for _ in range(span - 1))
            rows.append((tr, cells))
        table = Table()
        if rows and self._has_header(tbl, rows[0][0]):
            table.headers = rows[0][1]
            rows = rows[1:]
            for cell in table.headers:
                # A header is already set apart; its bold text would be bold twice.
                cell.children = [replace(n, bold=False) if isinstance(n, Text) else n for n in cell.children]
        table.rows = [TableRow(cells=cells) for _, cells in rows]
        return table

    @staticmethod
    def _has_header(tbl: etree._Element, first_row: etree._Element) -> bool:
        """Whether the first row is a header: marked as a repeating row, or the table's Header Row option."""
        if first_row.find(f"{w('trPr')}/{w('tblHeader')}") is not None:
            return True
        look = tbl.find(f"{w('tblPr')}/{w('tblLook')}")
        if look is None:
            return False
        if look.get(w("firstRow")) is not None:
            return look.get(w("firstRow")).lower() in ("1", "true", "on")
        try:
            return bool(int(look.get(w("val"), "0"), 16) & 0x20)
        except ValueError:
            return False

    def _cell(self, tc: etree._Element) -> list[Node]:
        """A cell's content as inline nodes, one line per paragraph (a nested table is flattened)."""
        paragraphs = []
        for child in tc:
            if child.tag == w("p"):
                paragraphs.append(child)
            elif child.tag == w("tbl"):
                paragraphs.extend(child.iter(w("p")))
        out: list[Node] = []
        for p in paragraphs:
            nodes, ctx = self._inline_paragraph(p)
            nodes = self._flatten(nodes, ctx)
            if nodes:
                out.extend([LineBreak()] if out else [])
                out.extend(nodes)
        return out

    # ---- inline content -------------------------------------------------

    def _inline_paragraph(self, p: etree._Element) -> tuple[list[Node], Inline]:
        """A paragraph's inline nodes, with what it carries besides them (display equations, text boxes)."""
        ctx = Inline()
        self._inline_children(p, ctx)
        while ctx.stack:
            self._end_field(ctx)
        nodes = lift_macros(text_runs(ctx.out))
        return tidy(nodes), ctx

    def _inline_children(self, parent: etree._Element, ctx: Inline) -> None:
        previous_equation_run = False
        for child in parent:
            if not isinstance(child.tag, str):
                continue
            tag = child.tag
            was_equation_run = False
            if tag == w("r"):
                was_equation_run = self._run(child, ctx, previous_equation_run)
            elif tag == w("hyperlink"):
                self._hyperlink(child, ctx)
            elif tag in (w("ins"), w("smartTag"), w("customXml"), w("moveTo"), w("dir"), w("bdo")):
                self._inline_children(child, ctx)
            elif tag == w("sdt"):
                content = child.find(w("sdtContent"))
                if content is not None:
                    self._inline_children(content, ctx)
            elif tag == w("fldSimple"):
                ctx.stack.append(Field(instr=child.get(w("instr"), ""), separated=True))
                self._inline_children(child, ctx)
                self._end_field(ctx)
            elif tag == f"{{{M}}}oMath":
                ctx.emit(Equation(code=omml_to_latex(child), inline=True))
            elif tag == f"{{{M}}}oMathPara":
                ctx.extra.extend(display_equation(m) for m in child.findall(f"{{{M}}}oMath"))
            previous_equation_run = was_equation_run

    def _hyperlink(self, el: etree._Element, ctx: Inline) -> None:
        url = self._link_target(el.get(f"{{{R}}}id"))
        anchor = el.get(w("anchor"))
        if anchor:
            url = f"{url or ''}#{anchor}"
        ctx.stack.append(Field(link=url, separated=True))
        self._inline_children(el, ctx)
        self._end_field(ctx)

    def _link_target(self, rel_id: str | None) -> str | None:
        rel = self.part.rels.get(rel_id) if rel_id else None
        return rel.target_ref if rel is not None and rel.is_external else None

    def _format(self, run: etree._Element) -> _RunFormat:
        fmt = _RunFormat()
        props = run.find(w("rPr"))
        if props is None:
            return fmt
        fmt.bold = flag(props.find(w("b")))
        fmt.italic = flag(props.find(w("i")))
        fmt.strike = flag(props.find(w("strike"))) or flag(props.find(w("dstrike")))
        fmt.script = {"superscript": "sup", "subscript": "sub"}.get(val(props.find(w("vertAlign")), ""))
        underline = props.find(w("u"))
        fmt.underline = (underline is not None and val(underline, "single") != "none"
                         and run.getparent().tag != w("hyperlink"))
        fmt.highlight = val(props.find(w("highlight")), "none") != "none"
        fonts = props.find(w("rFonts"))
        if fonts is not None:
            names = (fonts.get(w(a)) for a in ("ascii", "hAnsi", "cs"))
            fmt.code = any(n and n.lower() in MONOSPACE for n in names)
        char_style = props.find(w("rStyle"))
        if char_style is not None:
            style = self._style(val(char_style), "CHARACTER")
            name = (style.name if style is not None else "") or ""
            fmt.equation = name == "Equation"
            fmt.bold = fmt.bold or name in ("Strong", "Intense Emphasis")
            fmt.italic = fmt.italic or name in ("Emphasis", "Intense Emphasis")
        return fmt

    def _run(self, run: etree._Element, ctx: Inline, after_equation: bool) -> bool:
        """Read a run into ``ctx``; True when it was an equation run (which the next one extends)."""
        fmt = self._format(run)
        text: list[str] = []

        def flush() -> None:
            if not text:
                return
            content = "".join(text)
            text.clear()
            if fmt.equation:
                last = (ctx.stack[-1].out if ctx.stack else ctx.out)
                if after_equation and last and isinstance(last[-1], Equation):
                    last[-1] = Equation(code=last[-1].code + content, inline=True)
                else:
                    ctx.emit(Equation(code=content, inline=True))
                return
            if content.strip() and fmt.underline:
                self.dropped["underlined text"] += 1
            if content.strip() and fmt.highlight:
                self.dropped["highlighted text"] += 1
            if fmt.code:
                ctx.emit(CodeInline(code=content))
            else:
                ctx.emit(Text(content=content.replace("\t", " "), bold=fmt.bold, italic=fmt.italic,
                              strikethrough=fmt.strike, script=fmt.script))

        self._run_children(run, ctx, text, flush)
        flush()
        return fmt.equation

    def _run_children(self, run: etree._Element, ctx: Inline, text: list[str], flush) -> None:
        for child in run:
            if not isinstance(child.tag, str):
                continue
            tag = local(child)
            if tag == "t":
                text.append(child.text or "")
            elif tag == "tab":
                text.append("\t")
            elif tag == "noBreakHyphen":
                text.append("-")
            elif tag in ("br", "cr"):
                if child.get(w("type")) not in ("page", "column"):
                    flush()
                    ctx.emit(LineBreak())
            elif tag == "fldChar":
                flush()
                self._field_char(child, ctx)
            elif tag == "instrText":
                if ctx.stack:
                    ctx.stack[-1].instr += child.text or ""
            elif tag in ("footnoteReference", "endnoteReference"):
                flush()
                note = self._note(child, "footnote" if tag == "footnoteReference" else "endnote")
                if note is not None:
                    ctx.emit(note)
            elif tag == "drawing":
                flush()
                self._drawing(child, ctx)
            elif tag == "pict":
                flush()
                self._pict(child, ctx)
            elif tag == "AlternateContent":
                flush()
                branch = child.find(f"{{{NS['mc']}}}Choice")
                if branch is None:
                    branch = child.find(f"{{{NS['mc']}}}Fallback")
                if branch is not None:
                    self._run_children(branch, ctx, text, flush)
            elif tag == "object":
                self.dropped["embedded object"] += 1

    # ---- fields ---------------------------------------------------------

    def _field_char(self, el: etree._Element, ctx: Inline) -> None:
        kind = el.get(w("fldCharType"))
        if kind == "begin":
            ctx.stack.append(Field())
        elif kind == "separate" and ctx.stack:
            ctx.stack[-1].separated = True
        elif kind == "end" and ctx.stack:
            self._end_field(ctx)

    def _end_field(self, ctx: Inline) -> None:
        """Close the innermost field: a hyperlink wraps its result, a SEQ number marks the caption label."""
        fld = ctx.stack.pop()
        instr = fld.instr.strip()
        kind = instr.split(None, 1)[0].upper() if instr else ""
        url = fld.link
        if kind == "HYPERLINK":
            m = _HYPERLINK_INSTR.match(instr)
            url = (m.group(1) or "") + (f"#{m.group(2)}" if m and m.group(2) else "") if m else None
        if url and fld.out:
            ctx.emit(Link(url=url, content=fld.out))
        else:
            for node in fld.out:
                ctx.emit(node)
        if kind == "SEQ" and not ctx.stack:
            ctx.seq_end = len(ctx.out)

    # ---- notes, images, text boxes --------------------------------------

    def _note(self, ref: etree._Element, kind: str) -> Footnote | None:
        if kind not in self._notes:
            rel = self._rt.FOOTNOTES if kind == "footnote" else self._rt.ENDNOTES
            try:
                part = self.document.part.part_related_by(rel)
                root = etree.fromstring(part.blob)
                self._notes[kind] = (part, {
                    n.get(w("id")): n for n in root.findall(w(kind)) if n.get(w("type")) not in _NOTE_LAYOUT
                })
            except KeyError:
                self._notes[kind] = (None, {})
        notes_part, notes = self._notes[kind]
        note = notes.get(ref.get(w("id")))
        if note is None:
            return None
        main_part, self.part = self.part, notes_part
        try:
            content: list[Node] = []
            for p in note.findall(w("p")):
                nodes, ctx = self._inline_paragraph(p)
                nodes = self._flatten(nodes, ctx)
                if nodes:
                    content.extend([LineBreak()] if content else [])
                    content.extend(nodes)
        finally:
            self.part = main_part
        return Footnote(content=content)

    def _image(self, rel_id: str | None, alt: str) -> Image | None:
        if not self.write_images:
            return None
        try:
            part = self.part.related_parts[rel_id]
        except KeyError:
            self.dropped["linked or missing image"] += 1
            return None
        return Image(src=self._store.save(part.blob, part.partname.ext), alt=alt)

    def _drawing(self, drawing: etree._Element, ctx: Inline) -> None:
        outer = "not(ancestor::w:txbxContent)"
        blips = xpath(drawing, f".//a:blip[@r:embed][{outer}]")
        boxes = xpath(drawing, f".//w:txbxContent[{outer}]")
        props = drawing.find(".//wp:docPr", NS)
        alt = (props.get("descr") or props.get("title") or "") if props is not None else ""
        for blip in blips:
            image = self._image(blip.get(f"{{{R}}}embed"), alt)
            if image is not None:
                ctx.emit(image)
        self._text_boxes(boxes, ctx)
        if not blips and not boxes:
            self.dropped["shape"] += 1

    def _pict(self, pict: etree._Element, ctx: Inline) -> None:
        images = xpath(pict, ".//v:imagedata[@r:id]")
        boxes = xpath(pict, ".//w:txbxContent[not(ancestor::w:txbxContent)]")
        for data in images:
            alt = data.getparent().get("alt") or data.get(f"{{{OFFICE}}}title") or ""
            image = self._image(data.get(f"{{{R}}}id"), alt)
            if image is not None:
                ctx.emit(image)
        self._text_boxes(boxes, ctx)
        if not images and not boxes and any(isinstance(c.tag, str) and local(c) != "shapetype" for c in pict):
            self.dropped["shape"] += 1

    def _text_boxes(self, boxes: list[etree._Element], ctx: Inline) -> None:
        for box in boxes:
            blocks = self._blocks(box)
            if blocks:
                ctx.extra.append(BlockQuote(children=blocks))


