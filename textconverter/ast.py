from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class Node:
    """Base class for all AST nodes."""
    pass

@dataclass
class Text(Node):
    """A plain text node with optional formatting."""
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
    """A mathematical equation node."""
    code: str
    inline: bool = False

@dataclass
class Document(Node):
    """The root of the AST."""
    children: list[Node] = field(default_factory=list)
