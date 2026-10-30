"""Block assembly for the Word parser: paragraph and field state, list numbering, and the flow
that groups paragraphs into quotes, code, lists, tables and captions."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace

from lxml import etree

from ..ast import (
    Abstract, BlockQuote, CodeBlock, CodeInline, Image, Label, LineBreak, ListBlock, ListItem, Node,
    Paragraph, Table, Text, abstract_from,
)
from ..renderers._common import text_runs
from ._docx_xml import val, w
from ._latex_macros import lift_macros

_TASK = {"☐": False, "☑": True}
_LABEL_SEPARATOR = re.compile(r"^\s*[:.\-\u2013\u2014]?\s*")


def tidy(nodes: list[Node]) -> list[Node]:
    """Merge adjacent code and trim the paragraph's edges."""
    merged: list[Node] = []
    for node in nodes:
        if isinstance(node, CodeInline) and merged and isinstance(merged[-1], CodeInline):
            merged[-1] = CodeInline(code=merged[-1].code + node.code)
        else:
            merged.append(node)
    while merged and isinstance(merged[0], LineBreak):
        del merged[0]
    while merged and isinstance(merged[-1], LineBreak):
        del merged[-1]
    if merged and isinstance(merged[0], Text):
        merged[0] = replace(merged[0], content=merged[0].content.lstrip())
    if merged and isinstance(merged[-1], Text):
        merged[-1] = replace(merged[-1], content=merged[-1].content.rstrip())
    return [n for n in merged if not (isinstance(n, Text) and not n.content)]


@dataclass
class Field:
    """A field (or a hyperlink) being read: the nodes of its result collect in ``out``."""
    instr: str = ""
    separated: bool = False
    link: str | None = None
    out: list[Node] = field(default_factory=list)


@dataclass
class Inline:
    """The state of reading one paragraph's inline content."""
    out: list[Node] = field(default_factory=list)
    stack: list[Field] = field(default_factory=list)
    extra: list[Node] = field(default_factory=list)
    seq_end: int | None = None

    def emit(self, node: Node) -> None:
        (self.stack[-1].out if self.stack else self.out).append(node)


@dataclass
class ListRef:
    """Where a list paragraph sits: the list it belongs to (``key``), its level and kind."""
    key: object
    level: int
    ordered: bool
    start: int = 1


class Numbering:
    """The list definitions of ``numbering.xml``: kind and first number of each list level."""

    def __init__(self, root: etree._Element | None):
        self._levels: dict[str, dict[int, tuple[str, int]]] = {}
        self._nums: dict[str, tuple[str, dict[int, tuple[str | None, int | None]]]] = {}
        if root is None:
            return
        for abstract in root.findall(w("abstractNum")):
            self._levels[abstract.get(w("abstractNumId"))] = {
                int(lvl.get(w("ilvl"), 0)): (val(lvl.find(w("numFmt")), "decimal"),
                                              int(val(lvl.find(w("start")), "1")))
                for lvl in abstract.findall(w("lvl"))
            }
        for num in root.findall(w("num")):
            overrides = {}
            for over in num.findall(w("lvlOverride")):
                lvl = over.find(w("lvl"))
                fmt = val(lvl.find(w("numFmt"))) if lvl is not None else None
                start = val(over.find(w("startOverride")))
                if start is None and lvl is not None:
                    start = val(lvl.find(w("start")))
                overrides[int(over.get(w("ilvl"), 0))] = (fmt, int(start) if start else None)
            self._nums[num.get(w("numId"))] = (val(num.find(w("abstractNumId")), ""), overrides)

    def level(self, num_id: str, level: int) -> tuple[bool, int]:
        """``(ordered, first number)`` of a list level; an unknown list is a bullet list."""
        abstract_id, overrides = self._nums.get(num_id, ("", {}))
        fmt, start = self._levels.get(abstract_id, {}).get(level, ("bullet", 1))
        over_fmt, over_start = overrides.get(level, (None, None))
        fmt = over_fmt or fmt
        return fmt not in ("bullet", "none"), over_start if over_start is not None else start


class Flow:
    """Collects the blocks of a body: groups consecutive quote, abstract and code paragraphs, builds lists."""

    def __init__(self):
        self.out: list[Node] = []
        self._group: tuple[str, list] | None = None
        self._lists: list[tuple[ListBlock, object, int]] = []
        self._seen: Counter = Counter()
        self._caption: tuple[list[Node], str | None] | None = None

    def close(self) -> None:
        """End the open group or list."""
        if self._group is not None:
            kind, items = self._group
            self._group = None
            if kind == "code":
                code = "\n".join(items).strip("\n")
                if code.strip():
                    self.out.append(CodeBlock(code=code))
            elif kind == "quote":
                self.out.append(BlockQuote(children=items))
            else:
                self.out.append(abstract_from(items) or Abstract(children=items))
        self._lists = []

    def group(self, kind: str, item, extra: list[Node]) -> None:
        if self._group is not None and self._group[0] != kind:
            self.close()
        self._lists = []
        if self._group is None:
            self._group = (kind, [])
        self._group[1].append(item)
        if extra:
            self.close()
            self.out.extend(extra)

    def leaf(self, node: Node, extra: list[Node] = ()) -> None:
        self.close()
        self.out.append(node)
        self.out.extend(extra)

    def table(self, table: Table) -> None:
        self.close()
        if self._caption is not None:
            table.caption, table.label = self._caption[0], self._caption[1]
            self._caption = None
        self.out.append(table)

    def caption(self, nodes: list[Node], ctx: Inline, before_table: bool) -> None:
        """A caption belongs to the table that follows it, else to the table or figure just before it."""
        self.close()
        text = nodes
        if ctx.seq_end:
            text = tidy(lift_macros(text_runs(ctx.out[ctx.seq_end:])))
            if text and isinstance(text[0], Text):
                text[0] = replace(text[0], content=_LABEL_SEPARATOR.sub("", text[0].content, count=1))
        label = next((n.name for n in text if isinstance(n, Label)), None)
        text = tidy([n for n in text if not isinstance(n, Label)])
        previous = self.out[-1] if self.out else None
        figure = self._lone_image(previous)
        if before_table:
            self._caption = (text, label)
        elif isinstance(previous, Table) and not previous.caption:
            previous.caption, previous.label = text, label
        elif figure is not None and not figure.caption:
            figure.caption, figure.label = text, label
        else:
            self.out.append(Paragraph(children=nodes))
        self.out.extend(ctx.extra)

    @staticmethod
    def _lone_image(node: Node | None) -> Image | None:
        """The image a paragraph holds on its own, else None."""
        if not isinstance(node, Paragraph):
            return None
        content = [n for n in node.children if not (isinstance(n, Text) and not n.content.strip())]
        return content[0] if len(content) == 1 and isinstance(content[0], Image) else None

    def list_item(self, ref: ListRef, content: list[Node]) -> None:
        if self._group is not None:
            self.close()
        while self._lists and self._lists[-1][2] > ref.level:
            self._lists.pop()
        if self._lists and self._lists[-1][2] == ref.level and self._lists[-1][1] != ref.key:
            self._lists.pop()
        for key in [k for k in self._seen if k[0] == ref.key and k[1] > ref.level]:
            del self._seen[key]
        checked = None
        if content and isinstance(content[0], Text) and content[0].content[:1] in _TASK:
            checked = _TASK[content[0].content[0]]
            content[0] = replace(content[0], content=content[0].content[1:].lstrip())
        if self._lists and self._lists[-1][2] == ref.level:
            block = self._lists[-1][0]
        else:
            seen = self._seen[(ref.key, ref.level)]
            block = ListBlock(ordered=ref.ordered, start=ref.start + seen if ref.ordered else 1)
            if self._lists and self._lists[-1][0].items:
                self._lists[-1][0].items[-1].children.append(block)
            else:
                self.out.append(block)
            self._lists.append((block, ref.key, ref.level))
        block.items.append(ListItem(children=[Paragraph(children=content)], checked=checked))
        self._seen[(ref.key, ref.level)] += 1
