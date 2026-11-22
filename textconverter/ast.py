from __future__ import annotations
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

@dataclass
class Node:
    """Base class for all AST nodes."""
    pass

@dataclass
class Text(Node):
    """A plain text node with optional formatting.

    ``content`` is literal text. A ``\\n`` inside it is a hard line break;
    parsers turn soft line breaks of their source into spaces. ``script`` is
    ``"sup"`` or ``"sub"`` for superscript or subscript text.
    """
    content: str
    bold: bool = False
    italic: bool = False
    strikethrough: bool = False
    script: str | None = None

@dataclass
class Link(Node):
    """An hyperlink node."""
    url: str
    title: str | None = None
    # A link can contain text or even images
    content: list[Node] = field(default_factory=list)

@dataclass(frozen=True)
class BoxFrame:
    """Where a text box or a picture sits in its source; what is not known stays None.

    ``x``, ``y``, ``w`` and ``h`` are percentages of the slide or page, ``cells``
    the range of a sheet it covers, ``font`` the size of most of a text box's
    text in points.
    """
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None
    cells: str | None = None
    font: float | None = None

    @property
    def placed(self) -> bool:
        """Whether the frame gives a complete place on a slide or page."""
        return None not in (self.x, self.y, self.w, self.h)


# The word that opens a picture's frame in Markdown, ``<!--Picture (x 10%, w 30%)-->`` after the image.
PICTURE_FRAME = "Picture"

_PERCENT = re.compile(r"^([xywh]) (-?\d+)%$")
_FONT = re.compile(r"^font (\d+(?:\.\d+)?)pt$")
_CELLS = re.compile(r"^[A-Z]+\d+(?::[A-Z]+\d+)?$")


def frame_fields(frame: BoxFrame) -> str:
    """The frame as text, ``B2:D9, x 10%, y 20%, w 30%, h 40%, font 11pt``; what is None is left out."""
    fields = [frame.cells] if frame.cells else []
    fields.extend(f"{name} {getattr(frame, name)}%" for name in "xywh" if getattr(frame, name) is not None)
    if frame.font:
        fields.append(f"font {frame.font:g}pt")
    return ", ".join(fields)


def parse_frame_fields(text: str) -> BoxFrame | None:
    """The frame text written by ``frame_fields`` gives; None when any part of it is not a field."""
    values: dict[str, object] = {}
    for field_text in text.strip().split(", "):
        percent, font = _PERCENT.match(field_text), _FONT.match(field_text)
        if percent:
            values[percent.group(1)] = int(percent.group(2))
        elif font:
            values["font"] = float(font.group(1))
        elif _CELLS.match(field_text):
            values["cells"] = field_text
        else:
            return None
    return BoxFrame(**values)


@dataclass
class Image(Node):
    """An image node.

    ``caption`` and ``label`` make the image a figure (LaTeX ``figure``,
    HTML ``<figure>``). ``frame`` is where the picture sits in a slide, page
    or sheet, when the source tells it.
    """
    src: str
    alt: str = ""
    title: str | None = None
    description: str | None = None
    category: str | None = None
    extracted_text: str | None = None
    caption: list['InlineElement'] = field(default_factory=list)
    label: str | None = None
    frame: BoxFrame | None = None

@dataclass
class CodeInline(Node):
    """Inline code snippet."""
    code: str

@dataclass
class LineBreak(Node):
    """A line break; ``author_separator`` marks the one between two authors (LaTeX ``\\and``)."""
    author_separator: bool = False

@dataclass
class Footnote(Node):
    """An inline footnote containing other inline elements."""
    content: list['InlineElement'] = field(default_factory=list)

@dataclass
class Citation(Node):
    """A citation reference.

    ``style`` is the macro as written (``cite``, ``citet*``, ``parencite``, ...)
    and ``options`` its optional arguments (``\\citep[e.g.][p.~3]{key}`` gives
    ``["e.g.", "p.~3"]``). For ``\\cites`` each key is one ``{...}`` group.
    """
    keys: list[str]
    style: str = "cite"
    options: list[str] = field(default_factory=list)

@dataclass
class Reference(Node):
    """A cross-reference to a label.

    ``style`` is the macro as written (``ref``, ``eqref``, ``cref``, ...) and
    ``options`` its optional arguments. ``\\hyperref[target]{text}`` keeps
    ``text`` in ``label`` and the target in ``options``.
    """
    label: str
    style: str = "ref"
    options: list[str] = field(default_factory=list)

@dataclass
class Label(Node):
    """A target anchor label."""
    name: str

# Helper type for inline elements
InlineElement = Text | Link | Image | CodeInline | LineBreak | Footnote | Citation | Reference | Label

@dataclass
class Paragraph(Node):
    """A paragraph of mixed text/children."""
    children: list[InlineElement] = field(default_factory=list)

@dataclass
class Heading(Node):
    """A heading node; ``numbered`` is False for an unnumbered section (``\\section*``)."""
    level: int  # 1 to 6
    children: list[InlineElement] = field(default_factory=list)
    numbered: bool = True

@dataclass
class CodeBlock(Node):
    """A block of code."""
    code: str
    language: str | None = None

@dataclass
class BlockQuote(Node):
    """A block quote node containing other nodes."""
    children: list[Node] = field(default_factory=list)
    alert_type: str | None = None  # e.g., "NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION"

@dataclass
class Abstract(Node):
    """An abstract block containing other nodes."""
    children: list[Node] = field(default_factory=list)

@dataclass
class HorizontalRule(Node):
    """A horizontal rule / thematic break (---)."""
    pass

@dataclass
class Appendix(Node):
    """The start of the appendices (LaTeX ``\\appendix``); invisible in the other formats."""
    pass

@dataclass
class BibEntry(Node):
    """An entry of a ``thebibliography``: its key, the optional ``[label]`` and its text."""
    key: str
    children: list[InlineElement] = field(default_factory=list)
    label: str | None = None

@dataclass
class Bibliography(Node):
    """The bibliography of a document, kept so that citations can find it again in LaTeX.

    ``commands`` are the macros that point to it, as written
    (``\\bibliography{refs}``, ``\\printbibliography``, ...); ``entries`` the
    entries of a ``thebibliography``, whose argument is ``widest``.
    """
    commands: list[str] = field(default_factory=list)
    entries: list[BibEntry] = field(default_factory=list)
    widest: str = "9"

@dataclass
class ListItem(Node):
    """An item within a list; ``checked`` is True or False for a task list item."""
    children: list[Node] = field(default_factory=list)
    checked: bool | None = None

@dataclass
class ListBlock(Node):
    """An ordered or unordered list; ``start`` numbers an ordered list's first item."""
    ordered: bool
    items: list[ListItem] = field(default_factory=list)
    start: int = 1

@dataclass
class TableCell(Node):
    """A cell in a table."""
    children: list[InlineElement] = field(default_factory=list)

@dataclass
class TableRow(Node):
    """A row in a table."""
    cells: list[TableCell] = field(default_factory=list)

@dataclass
class Table(Node):
    """A basic table, with an optional caption and label."""
    headers: list[TableCell] = field(default_factory=list)
    rows: list[TableRow] = field(default_factory=list)
    caption: list[InlineElement] = field(default_factory=list)
    label: str | None = None

@dataclass
class Equation(Node):
    """A mathematical equation node.

    ``env`` names the display environment the equation came from (``equation``,
    ``align``, ``gather*``, ...); None means a plain, unnumbered display (or an
    inline) equation.
    """
    code: str
    inline: bool = False
    env: str | None = None

@dataclass
class Document(Node):
    """The root of the AST; ``title``, ``author`` and ``date`` are its metadata (empty when absent).

    ``section_root`` is the LaTeX command of a level 1 heading when it is not
    ``section`` (``chapter`` or ``part``).
    """
    children: list[Node] = field(default_factory=list)
    title: list[InlineElement] = field(default_factory=list)
    author: list[InlineElement] = field(default_factory=list)
    date: list[InlineElement] = field(default_factory=list)
    section_root: str | None = None


# The Document metadata fields, in the order the renderers write them.
METADATA_FIELDS = ("title", "author", "date")

# Every concrete node type by class name: the "type" key of the JSON form.
NODE_TYPES: dict[str, type[Node]] = {
    cls.__name__: cls
    for cls in (
        Text, Link, Image, CodeInline, LineBreak, Footnote, Citation, Reference, Label,
        Paragraph, Heading, CodeBlock, BlockQuote, Abstract, HorizontalRule, Appendix,
        ListItem, ListBlock, TableCell, TableRow, Table, Equation, Document, BibEntry, Bibliography,
    )
}

# The values a node field can hold that are not nodes, by class name: also a "type" key in JSON.
VALUE_TYPES: dict[str, type] = {BoxFrame.__name__: BoxFrame}

# Lines that frame an image description when it is rendered as text, so the
# Markdown parser can rebuild Image.description from a rendered document.
DESCRIPTION_START = "----- Start of picture description"
DESCRIPTION_END = "----- End of picture description -----"


def description_start(category: str | None) -> str:
    """The line that opens the description of an image of ``category``."""
    return f"{DESCRIPTION_START}{f' ({category})' if category else ''} -----"


# Every attribute through which a node can hold child nodes. A new container
# node type only needs its child attribute listed here. The main list comes
# first; captions and document metadata follow it.
_CHILD_ATTRS = ("children", "content", "items", "headers", "rows", "cells", "entries",
                "caption", "title", "author", "date")


def child_lists(node: Node) -> list[list[Node]]:
    """Return the node's lists of child nodes: the main list first, then captions and metadata.

    The lists are the node's own attributes, so callers may filter or replace
    their items in place (``lst[:] = ...``). String attributes (``Text.content``,
    ``Link.title``) are not included.
    """
    lists = (getattr(node, attr, None) for attr in _CHILD_ATTRS)
    return [lst for lst in lists if isinstance(lst, list)]


def walk(node: Node) -> Iterator[Node]:
    """Yield the node and all its descendants, depth-first (in ``child_lists`` order)."""
    yield node
    for lst in child_lists(node):
        for child in lst:
            yield from walk(child)


_ABSTRACT_PREFIX = re.compile(r'^\s*abstract\b[\s:.]*', re.IGNORECASE)


def abstract_from(children: list[Node]) -> Abstract | None:
    """Return an Abstract holding ``children`` when their text opens with the word "Abstract".

    Parsers call it on a block quote's content. The leading word (and a
    following colon) is removed from the first text node; "Abstraction ..."
    does not count.

    Returns:
        The Abstract, or None when the quote is not one.
    """
    holder = Document(children=children)
    for parent in walk(holder):
        for lst in child_lists(parent):
            for i, node in enumerate(lst):
                if not isinstance(node, Text) or not node.content.strip():
                    continue
                if not _ABSTRACT_PREFIX.match(node.content):
                    return None
                node.content = _ABSTRACT_PREFIX.sub('', node.content, count=1)
                if not node.content:
                    # The heading word alone (e.g. **Abstract**): drop it and the break after it
                    del lst[i]
                    if i < len(lst) and isinstance(lst[i], Text):
                        lst[i].content = lst[i].content.lstrip()
                    elif i < len(lst) and isinstance(lst[i], LineBreak):
                        del lst[i]
                return Abstract(children=children)
    return None
