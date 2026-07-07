from typing import List as TList, Optional, Union
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
    title: Optional[str] = None
    # A link can contain text or even images
    content: TList[Node] = field(default_factory=list)

@dataclass
class Image(Node):
    """An image node."""
    src: str
    alt: str = ""
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    extracted_text: Optional[str] = None
    render_metadata: bool = True

@dataclass
class CodeInline(Node):
    """Inline code snippet."""
    code: str

@dataclass
class LineBreak(Node):
    """A line break."""
    pass

# Helper type for inline elements
InlineElement = Union[Text, Link, Image, CodeInline, LineBreak]

@dataclass
class Paragraph(Node):
    """A paragraph of mixed text/children."""
    children: TList[InlineElement] = field(default_factory=list)

@dataclass
class Heading(Node):
    """A heading node."""
    level: int  # 1 to 6
    children: TList[InlineElement] = field(default_factory=list)

@dataclass
class CodeBlock(Node):
    """A block of code."""
    code: str
    language: Optional[str] = None

@dataclass
class BlockQuote(Node):
    """A block quote node containing other nodes."""
    children: TList[Node] = field(default_factory=list)
    alert_type: Optional[str] = None  # e.g., "NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION"

@dataclass
class HorizontalRule(Node):
    """A horizontal rule / thematic break (---)."""
    pass

@dataclass
class ListItem(Node):
    """An item within a list."""
    children: TList[Node] = field(default_factory=list)

@dataclass
class ListBlock(Node):
    """An ordered or unordered list."""
    ordered: bool
    items: TList[ListItem] = field(default_factory=list)

@dataclass
class TableCell(Node):
    """A cell in a table."""
    children: TList[InlineElement] = field(default_factory=list)

@dataclass
class TableRow(Node):
    """A row in a table."""
    cells: TList[TableCell] = field(default_factory=list)

@dataclass
class Table(Node):
    """A basic table."""
    headers: TList[TableCell] = field(default_factory=list)
    rows: TList[TableRow] = field(default_factory=list)

@dataclass
class Equation(Node):
    """A mathematical equation node."""
    code: str
    inline: bool = False

@dataclass
class Document(Node):
    """The root of the AST."""
    children: TList[Node] = field(default_factory=list)
