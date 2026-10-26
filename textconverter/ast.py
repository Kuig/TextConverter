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
    parsers turn soft line breaks of their source into spaces.
    """
    content: str
    bold: bool = False
    italic: bool = False
    strikethrough: bool = False

@dataclass
class Link(Node):
    """An hyperlink node."""
    url: str
    title: str | None = None
    # A link can contain text or even images
    content: list[Node] = field(default_factory=list)

@dataclass
class Image(Node):
    """An image node."""
    src: str
    alt: str = ""
    title: str | None = None
    description: str | None = None
    category: str | None = None
    extracted_text: str | None = None
    render_metadata: bool = True

@dataclass
class CodeInline(Node):
    """Inline code snippet."""
    code: str

@dataclass
class LineBreak(Node):
    """A line break."""
    pass

@dataclass
class Footnote(Node):
    """An inline footnote containing other inline elements."""
    content: list['InlineElement'] = field(default_factory=list)

@dataclass
class Citation(Node):
    """A citation reference."""
    keys: list[str]
    style: str = "cite" # cite, citet, citep

@dataclass
class Reference(Node):
    """A cross-reference to a label."""
    label: str

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
    """A heading node."""
    level: int  # 1 to 6
    children: list[InlineElement] = field(default_factory=list)

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
class ListItem(Node):
    """An item within a list."""
    children: list[Node] = field(default_factory=list)

@dataclass
class ListBlock(Node):
    """An ordered or unordered list."""
    ordered: bool
    items: list[ListItem] = field(default_factory=list)

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
    """A basic table."""
    headers: list[TableCell] = field(default_factory=list)
    rows: list[TableRow] = field(default_factory=list)

@dataclass
class Equation(Node):
    """A mathematical equation node.

    ``env`` names the display environment the equation came from (``align``,
    ``gather*``, ...) when its body depends on it; None means a plain
    display (or inline) equation.
    """
    code: str
    inline: bool = False
    env: str | None = None

@dataclass
class Document(Node):
    """The root of the AST."""
    children: list[Node] = field(default_factory=list)


# Every concrete node type by class name: the "type" key of the JSON form.
NODE_TYPES: dict[str, type[Node]] = {
    cls.__name__: cls
    for cls in (
        Text, Link, Image, CodeInline, LineBreak, Footnote, Citation, Reference, Label,
        Paragraph, Heading, CodeBlock, BlockQuote, Abstract, HorizontalRule,
        ListItem, ListBlock, TableCell, TableRow, Table, Equation, Document,
    )
}

# Lines that frame an image description when it is rendered as text, so the
# Markdown parser can rebuild Image.description from a rendered document.
DESCRIPTION_START = "----- Start of picture description -----"
DESCRIPTION_END = "----- End of picture description -----"


# Every attribute through which a node can hold child nodes. A new container
# node type only needs its child attribute listed here.
_CHILD_ATTRS = ("children", "content", "items", "headers", "rows", "cells")


def child_lists(node: Node) -> list[list[Node]]:
    """Return the node's lists of child nodes, in document order.

    The lists are the node's own attributes, so callers may filter or replace
    their items in place (``lst[:] = ...``). ``Text.content`` is a string and
    is not included.
    """
    lists = (getattr(node, attr, None) for attr in _CHILD_ATTRS)
    return [lst for lst in lists if isinstance(lst, list)]


def walk(node: Node) -> Iterator[Node]:
    """Yield the node and all its descendants, depth-first in document order."""
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
    first = next((n for c in children for n in walk(c) if isinstance(n, Text) and n.content.strip()), None)
    if first is None or not _ABSTRACT_PREFIX.match(first.content):
        return None
    first.content = _ABSTRACT_PREFIX.sub('', first.content, count=1)
    return Abstract(children=children)
