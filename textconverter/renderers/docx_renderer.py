"""Word (.docx) renderer: writes a Document AST with python-docx.

The built-in python-docx template supplies the styles; the few it lacks
(code, abstract, equation, footnotes) are added. Equations stay LaTeX text,
marked by a style the Word parser reads back; footnotes are real Word
footnotes, written to their own part.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass

from ..ast import (
    Abstract, Appendix, BlockQuote, CodeBlock, CodeInline, Document, Equation, Footnote, Heading, HorizontalRule,
    Image, LineBreak, Link, ListBlock, Node, Paragraph, Table, Text,
)
from ..logger import log_warning
from lxml import etree

from ..parsers._office import BoxFrame, parse_box_preamble
from ..parsers._omml import M_NS
from ..parsers.docx_parser import LANGUAGE_TAG
from ._common import figure_image, latex_reference_macro, lower_bibliography, plain_text, safe_href, table_grid, text_runs
from ._office import image_bytes, write_properties
from ._omml import UnsupportedMath, latex_to_omml

_CODE_FONT = "Consolas"
_LINK_COLOR = "0563C1"
_LIST_LEVELS = 9
_BULLETS = ("\u2022", "o", "\u25aa")
_NUMBER_FORMATS = ("decimal", "lowerLetter", "lowerRoman")
_FOOTNOTES_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_DEFAULT_DPI = 72
# A floating text box, the form Word itself writes.
_TEXT_BOX = (
    '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
    '<mc:Choice xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" Requires="wps"><w:drawing>'
    '<wp:anchor xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" distT="45720" '
    'distB="45720" distL="114300" distR="114300" simplePos="0" relativeHeight="{order}" behindDoc="0" locked="0" '
    'layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/>'
    '<wp:positionH relativeFrom="{from_x}"><wp:posOffset>{x}</wp:posOffset></wp:positionH>'
    '<wp:positionV relativeFrom="{from_y}"><wp:posOffset>{y}</wp:posOffset></wp:positionV>'
    '<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapSquare wrapText="bothSides"/>'
    '<wp:docPr id="{id}" name="Text Box {id}"/><wp:cNvGraphicFramePr/>'
    '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    '<a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"><wps:wsp>'
    '<wps:cNvSpPr txBox="1"/><wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>'
    '<a:ln w="9525"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln></wps:spPr>'
    '<wps:txbx><w:txbxContent/></wps:txbx><wps:bodyPr rot="0" vert="horz" wrap="square" lIns="91440" tIns="45720" '
    'rIns="91440" bIns="45720" anchor="t" anchorCtr="0"><a:spAutoFit/></wps:bodyPr></wps:wsp></a:graphicData>'
    '</a:graphic></wp:anchor></w:drawing></mc:Choice></mc:AlternateContent></w:r>'
)


@dataclass(frozen=True)
class _Fmt:
    """Formatting inherited by the text being written (a table header is bold)."""
    bold: bool = False
    italic: bool = False


class _NotesParent:
    """The parent python-docx wants for paragraphs of the footnotes part."""

    def __init__(self, part):
        self.part = part


def render_docx(doc: Document, output_path: str, base_dir: str | None = None) -> None:
    """Write the document as a Word file.

    Args:
        doc: The document to render.
        output_path: Where to write the ``.docx`` file.
        base_dir: Directory that relative local image paths resolve against
            (the current directory when None).
    """
    import docx
    lower_bibliography(doc)
    _Writer(docx.Document(), base_dir or os.getcwd()).write(doc, output_path)


class _Writer:
    """Builds one python-docx document from an AST."""

    def __init__(self, document, base_dir: str):
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
        from docx.oxml import OxmlElement, parse_xml
        from docx.oxml.ns import nsdecls, qn
        self.document = document
        self.base_dir = base_dir
        self._rt = RT
        self._new = OxmlElement
        self._parse = parse_xml
        self._nsdecls = nsdecls
        self._qn = qn
        self._notes: list[list[Node]] = []
        self._numbers = {"Table": 0, "Figure": 0}
        self._abstract_ids: dict[bool, str] = {}
        section = document.sections[0]
        from docx.shared import Cm
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        section.left_margin = section.right_margin = section.top_margin = section.bottom_margin = Cm(2.5)
        self._text_width = section.page_width - section.left_margin - section.right_margin
        self._add_styles()

    # ---- document -------------------------------------------------------

    def write(self, doc: Document, output_path: str) -> None:
        self._metadata(doc)
        if doc.title:
            self._inline(self.document.add_paragraph(style="Title"), doc.title)
        for node in doc.children:
            self._block(node)
        if self._notes:
            self._write_notes()
        self.document.save(output_path)

    def _metadata(self, doc: Document) -> None:
        write_properties(self.document.core_properties, doc)

    def _add_styles(self) -> None:
        from docx.enum.style import WD_STYLE_TYPE as T
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Cm, Pt, RGBColor
        styles = self.document.styles

        def add(name: str, kind, base: str | None = "Normal"):
            style = styles.add_style(name, kind)
            if base:
                style.base_style = styles[base]
            return style

        code = add("Code", T.PARAGRAPH)
        code.font.name, code.font.size = _CODE_FONT, Pt(10)
        code.paragraph_format.space_after = Pt(0)
        shading = self._new("w:shd")
        for key, value in (("val", "clear"), ("color", "auto"), ("fill", "F2F2F2")):
            shading.set(self._qn(f"w:{key}"), value)
        code.element.get_or_add_pPr().append(shading)

        abstract = add("Abstract", T.PARAGRAPH)
        abstract.font.italic = True
        abstract.paragraph_format.left_indent = abstract.paragraph_format.right_indent = Cm(1)

        display = add("Equation Display", T.PARAGRAPH)
        display.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add("Equation", T.CHARACTER, None).font.name = _CODE_FONT

        add("Footnote Text", T.PARAGRAPH).font.size = Pt(10)
        reference = add("Footnote Reference", T.CHARACTER, None)
        reference.font.superscript = True
        self._link_color = RGBColor.from_string(_LINK_COLOR)

    # ---- blocks ---------------------------------------------------------

    def _block(self, node: Node, depth: int = 0) -> None:
        """Write a block; ``depth`` is the quote nesting, which indents paragraphs."""
        if isinstance(node, Heading):
            self._inline(self.document.add_paragraph(style=f"Heading {min(node.level, 6)}"), node.children)
        elif isinstance(node, Paragraph):
            self._paragraph(node, depth)
        elif isinstance(node, CodeBlock):
            self._code(node)
        elif isinstance(node, BlockQuote):
            self._quote(node, depth)
        elif isinstance(node, Abstract):
            self._abstract(node)
        elif isinstance(node, HorizontalRule):
            self._rule()
        elif isinstance(node, ListBlock):
            self._list(node, 0)
        elif isinstance(node, Table):
            self._table(node)
        elif isinstance(node, Equation):
            self._equation(self.document.add_paragraph(), node, None, display=True)
        elif not isinstance(node, Appendix):
            self._paragraph(Paragraph(children=[node]), depth)

    def _paragraph(self, node: Paragraph, depth: int = 0, style: str | None = None) -> None:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        figures = [f for f in (figure_image(c) for c in node.children) if f is not None]
        p = self.document.add_paragraph(style=style or ("Quote" if depth else None))
        if depth:
            from docx.shared import Cm
            p.paragraph_format.left_indent = Cm(depth)
        self._inline(p, node.children)
        content = [c for c in node.children if not (isinstance(c, Text) and not c.content.strip())]
        if len(content) == 1 and isinstance(figure_image(content[0]) or content[0], Image):
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for image in figures:
            self._caption("Figure", image.caption, image.label)

    def _code(self, node: CodeBlock) -> None:
        paragraphs = [self.document.add_paragraph(line, style="Code")._p for line in node.code.split("\n")]
        if not node.language:
            return
        control = self._parse(f'<w:sdt {self._nsdecls("w")}><w:sdtPr><w:tag w:val=""/></w:sdtPr><w:sdtContent/></w:sdt>')
        control.find(self._qn("w:sdtPr")).find(self._qn("w:tag")).set(self._qn("w:val"), LANGUAGE_TAG + node.language)
        paragraphs[0].addprevious(control)
        content = control.find(self._qn("w:sdtContent"))
        for paragraph in paragraphs:
            content.append(paragraph)

    def _box_frame(self, node: BlockQuote) -> BoxFrame | None:
        """The frame of a quote that is a text box; a range of cells or a frame without a size is not a place here."""
        first = node.children[0] if node.children else None
        frame = parse_box_preamble(plain_text(first.children)) if isinstance(first, Paragraph) else None
        return frame if frame is not None and None not in (frame.x, frame.w, frame.h) else None

    def _text_box(self, node: BlockQuote, frame: BoxFrame) -> None:
        """A floating text box: its blocks are written in the body like any others, then moved into the box."""
        body = self.document.element.body
        first_new = len(body) - 1  # the last child is the section properties
        for child in node.children[1:]:
            self._block(child)
        blocks = list(body)[first_new:-1]
        if frame.font:
            self._set_font(blocks, frame.font)
        section = self.document.sections[0]
        anchor = self.document.add_paragraph()
        drawing = self._parse(_TEXT_BOX.format(
            order=251659264 + first_new, id=self.document.part.next_id,
            from_x="page", x=round(frame.x / 100 * section.page_width),
            from_y="page" if frame.y is not None else "paragraph",
            y=round((frame.y or 0) / 100 * section.page_height),
            cx=round(frame.w / 100 * section.page_width), cy=round(frame.h / 100 * section.page_height)))
        anchor._p.append(drawing)
        content = next(drawing.iter(self._qn("w:txbxContent")))
        for block in blocks:
            content.append(block)
        if not blocks:
            content.append(self._new("w:p"))

    @staticmethod
    def _set_font(blocks: list, size: float) -> None:
        from docx.shared import Pt
        from docx.text.run import Run
        for block in blocks:
            for run in block.iter("{" + _W + "}r"):
                Run(run, None).font.size = Pt(size)

    def _quote(self, node: BlockQuote, depth: int) -> None:
        frame = self._box_frame(node) if not depth and not node.alert_type else None
        if frame is not None:
            self._text_box(node, frame)
            return
        if node.alert_type:
            from docx.shared import Cm
            p = self.document.add_paragraph(style="Quote")
            p.paragraph_format.left_indent = Cm(depth + 1)
            self._add_run(p, node.alert_type.capitalize(), bold=True)
        for child in node.children:
            if isinstance(child, BlockQuote):
                self._quote(child, depth + 1)
            elif isinstance(child, Paragraph):
                self._paragraph(child, depth + 1)
            else:
                self._block(child, depth + 1)

    def _abstract(self, node: Abstract) -> None:
        children = list(node.children)
        first = children[0] if children and isinstance(children[0], Paragraph) else None
        p = self.document.add_paragraph(style="Abstract")
        self._add_run(p, "Abstract", bold=True)
        if first is not None:
            p.add_run().add_break()
            self._inline(p, first.children)
            children = children[1:]
        for child in children:
            if isinstance(child, Paragraph):
                self._inline(self.document.add_paragraph(style="Abstract"), child.children)
            else:
                self._block(child)

    def _rule(self) -> None:
        p = self.document.add_paragraph()
        border = self._new("w:pBdr")
        bottom = self._new("w:bottom")
        for key, value in (("val", "single"), ("sz", "6"), ("space", "1"), ("color", "808080")):
            bottom.set(self._qn(f"w:{key}"), value)
        border.append(bottom)
        p._p.get_or_add_pPr().append(border)

    # ---- lists ----------------------------------------------------------

    def _abstract_id(self, ordered: bool) -> str:
        """The id of the multilevel list definition for bullets or numbers (added on first use)."""
        if ordered in self._abstract_ids:
            return self._abstract_ids[ordered]
        root = self.document.part.numbering_part.element
        ids = [int(a.get(self._qn("w:abstractNumId"))) for a in root.findall(self._qn("w:abstractNum"))]
        abstract_id = str(max(ids, default=-1) + 1)
        levels = []
        for i in range(_LIST_LEVELS):
            fmt = _NUMBER_FORMATS[i % 3] if ordered else "bullet"
            text = f"%{i + 1}." if ordered else _BULLETS[i % 3]
            levels.append(
                f'<w:lvl w:ilvl="{i}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/>'
                f'<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="{720 * (i + 1)}" w:hanging="360"/></w:pPr></w:lvl>')
        abstract = self._parse(
            f'<w:abstractNum {self._nsdecls("w")} w:abstractNumId="{abstract_id}">'
            f'<w:multiLevelType w:val="hybridMultilevel"/>{"".join(levels)}</w:abstractNum>')
        first_num = root.find(self._qn("w:num"))
        if first_num is not None:
            first_num.addprevious(abstract)
        else:
            root.append(abstract)
        self._abstract_ids[ordered] = abstract_id
        return abstract_id

    def _new_list(self, ordered: bool, level: int, start: int) -> str:
        """A new numbering instance, so that every list counts from its own start."""
        root = self.document.part.numbering_part.element
        ids = [int(n.get(self._qn("w:numId"))) for n in root.findall(self._qn("w:num"))]
        num_id = str(max(ids, default=0) + 1)
        override = (f'<w:lvlOverride w:ilvl="{level}"><w:startOverride w:val="{start}"/></w:lvlOverride>'
                    if ordered else "")
        root.append(self._parse(
            f'<w:num {self._nsdecls("w")} w:numId="{num_id}"><w:abstractNumId w:val="{self._abstract_id(ordered)}"/>'
            f'{override}</w:num>'))
        return num_id

    def _list(self, node: ListBlock, depth: int) -> None:
        from docx.shared import Cm
        level = min(depth, _LIST_LEVELS - 1)
        num_id = self._new_list(node.ordered, level, node.start)
        for item in node.items:
            p = self.document.add_paragraph(style="List Paragraph")
            num_pr = p._p.get_or_add_pPr().get_or_add_numPr()
            num_pr.get_or_add_ilvl().val = level
            num_pr.get_or_add_numId().val = int(num_id)
            children = list(item.children)
            if item.checked is not None:
                self._add_run(p, "\u2611 " if item.checked else "\u2610 ")
            if children and isinstance(children[0], Paragraph):
                self._inline(p, children.pop(0).children)
            for child in children:
                if isinstance(child, ListBlock):
                    self._list(child, depth + 1)
                elif isinstance(child, Paragraph):
                    self._paragraph(child)
                    self.document.paragraphs[-1].paragraph_format.left_indent = Cm(1.27 * (level + 1))
                else:
                    self._block(child)

    # ---- tables and captions -------------------------------------------

    def _table(self, node: Table) -> None:
        headers, rows, ncols = table_grid(node)
        if not ncols:
            return
        if node.caption or node.label:
            self._caption("Table", node.caption, node.label).paragraph_format.keep_with_next = True
        grid = ([headers] if headers else []) + rows
        table = self.document.add_table(rows=len(grid), cols=ncols)
        table.style = "Table Grid"
        look = table._tbl.tblPr.find(self._qn("w:tblLook"))
        if look is not None:
            look.set(self._qn("w:firstRow"), "1" if headers else "0")
            look.set(self._qn("w:val"), "04A0" if headers else "0480")
        for r, cells in enumerate(grid):
            is_header = bool(headers) and r == 0
            if is_header:
                row_pr = table.rows[0]._tr.get_or_add_trPr()
                row_pr.append(self._new("w:tblHeader"))
            for c, cell in enumerate(cells):
                self._inline(table.cell(r, c).paragraphs[0], cell.children, _Fmt(bold=is_header))
        self.document.add_paragraph()

    def _caption(self, label: str, caption: list[Node], name: str | None):
        """A Caption paragraph: ``label``, an auto-numbered SEQ field, then the caption and its ``\\label``."""
        self._numbers[label] += 1
        p = self.document.add_paragraph(style="Caption")
        self._add_run(p, f"{label} ")
        self._field(p, f"SEQ {label} \\* ARABIC", str(self._numbers[label]))
        if caption or name:
            self._add_run(p, ": ")
        self._inline(p, caption)
        if name:
            self._add_run(p, (" " if caption else "") + f"\\label{{{name}}}")
        return p

    def _field(self, paragraph, instruction: str, result: str) -> None:
        def mark(kind: str) -> None:
            el = self._new("w:fldChar")
            el.set(self._qn("w:fldCharType"), kind)
            paragraph.add_run()._r.append(el)

        mark("begin")
        code = self._new("w:instrText")
        code.set(self._qn("xml:space"), "preserve")
        code.text = f" {instruction} "
        paragraph.add_run()._r.append(code)
        mark("separate")
        paragraph.add_run(result)
        mark("end")

    # ---- inline content -------------------------------------------------

    def _equation(self, paragraph, node: Equation, container, display: bool) -> None:
        """A Word equation; a formula that cannot be translated stays LaTeX text in the Equation style."""
        try:
            math = latex_to_omml(node.code, node.env)
        except UnsupportedMath as exc:
            log_warning(f"Equation kept as LaTeX text, not translated to a Word equation ({exc}): "
                        f"{node.code[:60]}")
            code = f"\\begin{{{node.env}}}\n{node.code}\n\\end{{{node.env}}}" if node.env else node.code
            if display:
                paragraph.style = "Equation Display"
            self._add_run(paragraph, code, container, style="Equation")
            return
        if display:
            wrapper = etree.SubElement(paragraph._p, f"{{{M_NS}}}oMathPara")
            wrapper.append(math)
        else:
            (container if container is not None else paragraph._p).append(math)

    def _add_run(self, paragraph, text: str, container=None, *, bold=False, italic=False, strike=False,
                 script: str | None = None, style: str | None = None, font: str | None = None):
        run = paragraph.add_run()
        if container is not None:
            container.append(run._r)
        if text:
            run.text = text
        run.font.bold = bold or None
        run.font.italic = italic or None
        run.font.strike = strike or None
        if script:
            run.font.superscript = script == "sup"
            run.font.subscript = script == "sub"
        if style:
            run._r.get_or_add_rPr().get_or_add_rStyle().val = style.replace(" ", "")
        if font:
            run.font.name = font
        return run

    def _inline(self, paragraph, nodes: list[Node], fmt: _Fmt = _Fmt(), container=None) -> None:
        for node in text_runs(nodes):
            if isinstance(node, Text):
                lines = node.content.split("\n")
                for i, line in enumerate(lines):
                    if i:
                        self._add_run(paragraph, "", container).add_break()
                    if line:
                        self._add_run(paragraph, line, container, bold=node.bold or fmt.bold,
                                      italic=node.italic or fmt.italic, strike=node.strikethrough,
                                      script=node.script)
            elif isinstance(node, CodeInline):
                self._add_run(paragraph, node.code, container, font=_CODE_FONT)
            elif isinstance(node, LineBreak):
                self._add_run(paragraph, "", container).add_break()
            elif isinstance(node, Link):
                self._link(paragraph, node, fmt, container)
            elif isinstance(node, Image):
                self._picture(paragraph, node, container)
            elif isinstance(node, Equation):
                self._equation(paragraph, node, container, display=False)
            elif isinstance(node, Footnote):
                self._footnote(paragraph, node, container)
            else:
                macro = latex_reference_macro(node, plain_text)
                if macro:
                    self._add_run(paragraph, macro, container)

    def _link(self, paragraph, node: Link, fmt: _Fmt, container) -> None:
        url = safe_href(node.url)
        if url == "#" or not node.content:
            self._inline(paragraph, node.content, fmt, container)
            return
        link = self._new("w:hyperlink")
        if url.startswith("#"):
            link.set(self._qn("w:anchor"), url[1:])
        else:
            rel_id = paragraph.part.relate_to(url, self._rt.HYPERLINK, is_external=True)
            link.set(self._qn("r:id"), rel_id)
        if node.title:
            link.set(self._qn("w:tooltip"), node.title)
        (container if container is not None else paragraph._p).append(link)
        before = len(link)
        self._inline(paragraph, node.content, fmt, link)
        from docx.text.run import Run
        for r in link[before:]:
            if r.tag == self._qn("w:r"):
                run = Run(r, paragraph)
                run.font.color.rgb = self._link_color
                run.font.underline = True

    # ---- images ---------------------------------------------------------

    def _picture_size(self, info) -> tuple[int, int]:
        """The size of a picture on the page, its own unless wider than the text; a JPEG may tell 0 dpi."""
        from docx.shared import Inches
        width = Inches(info.px_width / (info.horz_dpi or _DEFAULT_DPI))
        height = Inches(info.px_height / (info.vert_dpi or _DEFAULT_DPI))
        scale = min(1.0, self._text_width / width) if width else 1.0
        return round(width * scale), round(height * scale)

    @staticmethod
    def _picture_info(blob: bytes):
        """The blob and python-docx's view of it; formats it cannot embed (WebP) are converted to PNG."""
        from docx.image.image import Image as DocxImage
        try:
            return blob, DocxImage.from_blob(blob)
        except Exception:
            from PIL import Image as PilImage
            out = io.BytesIO()
            with PilImage.open(io.BytesIO(blob)) as picture:
                picture.convert("RGBA" if picture.mode in ("RGBA", "LA", "P") else "RGB").save(out, "PNG")
            return out.getvalue(), DocxImage.from_blob(out.getvalue())

    def _picture(self, paragraph, node: Image, container) -> None:
        blob = image_bytes(node.src, self.base_dir)
        run = None
        if blob is not None and hasattr(paragraph.part, "new_pic_inline"):
            try:
                blob, info = self._picture_info(blob)
                run = self._add_run(paragraph, "", container)
                width, height = self._picture_size(info)
                run.add_picture(io.BytesIO(blob), width=width, height=height)
            except Exception as exc:
                log_warning(f"Image not embedded in the Word file ({exc}): {node.src[:80]}")
                if run is not None:
                    run._r.getparent().remove(run._r)
                run = None
        if run is None:
            fallback = node.alt or (node.src if not node.src.startswith("data:") else "image")
            self._add_run(paragraph, f"[{fallback}]", container)
            return
        for props in run._r.iter(self._qn("wp:docPr")):
            props.set("descr", node.alt or "")

    # ---- footnotes ------------------------------------------------------

    def _footnote(self, paragraph, node: Footnote, container) -> None:
        self._notes.append(node.content)
        run = self._add_run(paragraph, "", container)
        ref = self._new("w:footnoteReference")
        ref.set(self._qn("w:id"), str(len(self._notes)))
        run._r.append(ref)
        run._r.get_or_add_rPr().get_or_add_rStyle().val = "FootnoteReference"

    def _write_notes(self) -> None:
        """Add the footnotes part: the two separators Word expects, then one footnote per reference."""
        from docx.opc.packuri import PackURI
        from docx.opc.part import XmlPart
        from docx.text.paragraph import Paragraph as DocxParagraph
        separator = lambda kind, number, tag: (  # noqa: E731
            f'<w:footnote w:type="{kind}" w:id="{number}"><w:p><w:pPr><w:spacing w:after="0" w:line="240" '
            f'w:lineRule="auto"/></w:pPr><w:r><w:{tag}/></w:r></w:p></w:footnote>')
        root = self._parse(
            f'<w:footnotes {self._nsdecls("w", "r")}>{separator("separator", -1, "separator")}'
            f'{separator("continuationSeparator", 0, "continuationSeparator")}</w:footnotes>')
        part = XmlPart(PackURI("/word/footnotes.xml"), _FOOTNOTES_TYPE, root, self.document.part.package)
        self.document.part.relate_to(part, self._rt.FOOTNOTES)
        for number, content in enumerate(self._notes, 1):
            note = self._new("w:footnote")
            note.set(self._qn("w:id"), str(number))
            p = self._new("w:p")
            note.append(p)
            root.append(note)
            paragraph = DocxParagraph(p, _NotesParent(part))
            p.get_or_add_pPr().get_or_add_pStyle().val = "FootnoteText"
            mark = self._add_run(paragraph, "", style="Footnote Reference")
            mark._r.append(self._new("w:footnoteRef"))
            self._add_run(paragraph, " ")
            self._inline(paragraph, [n for n in content if not isinstance(n, Footnote)])
