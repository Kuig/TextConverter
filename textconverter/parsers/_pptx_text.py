"""Text bodies of a slide: paragraphs, runs, bullets and equations, read into AST nodes."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import groupby

from lxml import etree

from ..ast import CodeInline, Equation, LineBreak, Link, Node, Paragraph, Text
from ..renderers._common import text_runs
from ._docx_blocks import Flow, ListRef, tidy
from ._latex_macros import lift_macros
from ._office import MONOSPACE, is_code
from ._omml import omml_to_latex
from ._pptx_xml import MC, NS, R, a, xpath
from .docx_parser import display_equation

_M = NS["m"]
_BULLET_KINDS = ("buNone", "buChar", "buBlip", "buAutoNum")


@dataclass
class _Run:
    """The formatting of one run, from its properties and the text body's defaults."""
    bold: bool = False
    italic: bool = False
    strike: bool = False
    script: str | None = None
    code: bool = False


def level_properties(list_style: etree._Element | None, level: int) -> etree._Element | None:
    """The ``a:lvlNpPr`` of a list style for a 0-based paragraph level."""
    return list_style.find(a(f"lvl{level + 1}pPr")) if list_style is not None else None


def _typefaces(props: etree._Element | None) -> list[str]:
    if props is None:
        return []
    return [el.get("typeface", "").lower() for el in (props.find(a(n)) for n in ("latin", "ea", "cs"))
            if el is not None]


def _is_mono(props: etree._Element | None, default: bool) -> bool:
    """Whether run properties name a monospaced font; with no font named, ``default`` (the body's)."""
    faces = _typefaces(props)
    return any(f in MONOSPACE for f in faces) if faces else default


def _bullet_kind(props: etree._Element | None) -> str | None:
    """Which bullet element a paragraph's (or a level's) properties carry, None when they set none."""
    if props is None:
        return None
    return next((kind for kind in _BULLET_KINDS if props.find(a(kind)) is not None), None)


def _size(props: etree._Element | None) -> float | None:
    """The size in points that run properties set."""
    value = props.get("sz") if props is not None else None
    return int(value) / 100 if value and value.isdigit() else None


def dominant_font(body: etree._Element, defaults: list[etree._Element]) -> float | None:
    """The font size of most of a text body's characters, in points.

    A run tells its size, else the body's list style does, else ``defaults``
    (the list styles it inherits). None when none of them does.
    """
    styles = [body.find(a("lstStyle")), *defaults]
    sizes: Counter[float] = Counter()
    for paragraph in body.findall(a("p")):
        props = paragraph.find(a("pPr"))
        level = int(props.get("lvl", "0")) if props is not None else 0
        inherited = next((size for size in (_size(_level_defaults(style, level)) for style in styles) if size), None)
        for run in paragraph:
            if isinstance(run.tag, str) and run.tag in (a("r"), a("fld")):
                text = "".join(t.text or "" for t in run.findall(a("t"))).strip()
                size = _size(run.find(a("rPr"))) or inherited
                if text and size:
                    sizes[size] += len(text)
    return sizes.most_common(1)[0][0] if sizes else None


def _level_defaults(style: etree._Element | None, level: int) -> etree._Element | None:
    props = level_properties(style, level)
    return props.find(a("defRPr")) if props is not None else None


class TextReader:
    """Reads the text bodies of one part (a slide or its notes), whose relationships resolve the links.

    Args:
        part: The python-pptx part the text bodies belong to.
        dropped: Counts the features without a counterpart, for the parser's single warning.
        keep_indentation: Keep a paragraph's leading spaces, for code detection.
    """

    def __init__(self, part, dropped: Counter[str], keep_indentation: bool = False):
        self._part = part
        self._dropped = dropped
        self._keep_indentation = keep_indentation

    # ---- inline content -------------------------------------------------

    def inline(self, paragraph: etree._Element, default_mono: bool = False) -> tuple[list[Node], list[Node]]:
        """A paragraph's inline nodes, and the display equations it carries beside them."""
        out: list[tuple[Node, str | None]] = []
        extras: list[Node] = []
        for child in paragraph:
            if not isinstance(child.tag, str):
                continue
            tag = child.tag
            if tag in (a("r"), a("fld")):
                self._run(child, default_mono, out)
            elif tag == a("br"):
                out.append((LineBreak(), None))
            elif tag == f"{{{MC}}}AlternateContent":
                self._math(child, out, extras)
        nodes: list[Node] = []
        for url, group in groupby(out, key=lambda pair: pair[1]):
            members = [node for node, _ in group]
            nodes.extend([Link(url=url, content=members)] if url else members)
        return tidy(lift_macros(text_runs(nodes)), keep_indentation=self._keep_indentation), extras

    def _run(self, run: etree._Element, default_mono: bool, out: list[tuple[Node, str | None]]) -> None:
        text = "".join(t.text or "" for t in run.findall(a("t"))).replace("\t", " ").replace("\x0b", "\n")
        if not text:
            return
        props = run.find(a("rPr"))
        fmt = self._format(props, default_mono)
        url = self._link(props)
        if text.strip() and props is not None:
            if props.get("u", "none") != "none" and url is None:
                self._dropped["underlined text"] += 1
            if props.find(a("highlight")) is not None:
                self._dropped["highlighted text"] += 1
        node = CodeInline(code=text) if fmt.code else Text(
            content=text, bold=fmt.bold, italic=fmt.italic, strikethrough=fmt.strike, script=fmt.script)
        out.append((node, url))

    @staticmethod
    def _format(props: etree._Element | None, default_mono: bool) -> _Run:
        fmt = _Run(code=_is_mono(props, default_mono))
        if props is None:
            return fmt
        fmt.bold = props.get("b") in ("1", "true")
        fmt.italic = props.get("i") in ("1", "true")
        fmt.strike = props.get("strike", "noStrike") != "noStrike"
        baseline = int(props.get("baseline", "0") or 0)
        fmt.script = "sup" if baseline > 0 else "sub" if baseline < 0 else None
        return fmt

    def _link(self, props: etree._Element | None) -> str | None:
        """The external address of a run's hyperlink; a jump inside the presentation is dropped."""
        click = props.find(a("hlinkClick")) if props is not None else None
        if click is None:
            return None
        rel_id = click.get(f"{{{R}}}id")
        rel = self._part.rels.get(rel_id) if rel_id else None
        if rel is not None and rel.is_external:
            return rel.target_ref
        if click.get("action") or rel is not None:
            self._dropped["link to a slide"] += 1
        return None

    @staticmethod
    def _math(content: etree._Element, out: list[tuple[Node, str | None]], extras: list[Node]) -> None:
        for math in xpath(content, "mc:Choice//a14:m"):
            for display in math.findall(f"{{{_M}}}oMathPara"):
                extras.extend(display_equation(m) for m in display.findall(f"{{{_M}}}oMath"))
            out.extend((Equation(code=omml_to_latex(m), inline=True), None)
                       for m in math.findall(f"{{{_M}}}oMath"))

    # ---- blocks -----------------------------------------------------------

    def blocks(
        self,
        body: etree._Element,
        flow: Flow,
        key: object,
        inherited: list[etree._Element | None],
    ) -> None:
        """Read a ``p:txBody`` into ``flow``: paragraphs, bullet lists and code.

        Args:
            body: The text body.
            flow: Receives the blocks.
            key: Tells this body's lists from every other body's.
            inherited: List styles the body's own one falls back to for bullets (layout, master); a
                text box has none, so its paragraphs are plain unless they set a bullet themselves.
        """
        own = body.find(a("lstStyle"))
        styles = [own, *inherited]
        run = 0
        in_code = False
        for paragraph in body.findall(a("p")):
            props = paragraph.find(a("pPr"))
            level = int(props.get("lvl", "0")) if props is not None else 0
            defaults = level_properties(own, level)
            default_mono = _is_mono(defaults.find(a("defRPr")) if defaults is not None else None, False)
            nodes, extras = self.inline(paragraph, default_mono)
            if is_code(nodes):
                flow.group("code", _code_text(nodes), extras)
                in_code = True
                continue
            if not nodes and not extras:
                if in_code and _is_mono(paragraph.find(a("endParaRPr")), default_mono):
                    flow.group("code", "", [])
                else:
                    in_code = False
                    run += 1
                continue
            in_code = False
            bullet = self._bullet_of(props, styles, level)
            if bullet:
                flow.list_item(ListRef(key=(key, run), level=level, ordered=bullet[0], start=bullet[1]), nodes)
            else:
                run += 1
                if nodes:
                    flow.leaf(Paragraph(children=nodes))
            for display in extras:
                run += 1
                flow.leaf(display)

    @staticmethod
    def _bullet_of(props: etree._Element | None, styles: list[etree._Element | None], level: int):
        """``(ordered, start)`` when the paragraph is a list item, else None."""
        for source in (props, *(level_properties(style, level) for style in styles)):
            kind = _bullet_kind(source)
            if kind is None:
                continue
            if kind == "buNone":
                return None
            if kind == "buAutoNum":
                return True, int(source.find(a(kind)).get("startAt", "1"))
            return False, 1
        return None


def _code_text(nodes: list[Node]) -> str:
    """The text of a code paragraph, one line per line break."""
    return "".join("\n" if isinstance(n, LineBreak) else n.code if isinstance(n, CodeInline) else n.content
                   for n in nodes)


def plain_text(nodes: list[Node]) -> str:
    """The text of inline nodes without any formatting."""
    parts = []
    for node in nodes:
        if isinstance(node, Text):
            parts.append(node.content)
        elif isinstance(node, CodeInline):
            parts.append(node.code)
        elif isinstance(node, LineBreak):
            parts.append(" ")
        elif isinstance(node, Link):
            parts.append(plain_text(node.content))
    return "".join(parts)


def single_line(nodes: list[Node]) -> list[Node]:
    """Inline nodes with every line break turned into a space (a heading is one line)."""
    return [Text(content=" ") if isinstance(n, LineBreak) else n for n in nodes]
