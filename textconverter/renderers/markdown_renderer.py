from __future__ import annotations
import re
from ..ast import (
    Abstract, BlockQuote, Citation, CodeBlock, CodeInline, Document, Equation, Footnote, Heading,
    HorizontalRule, Image, Label, LineBreak, Link, ListBlock, Node, Paragraph, Reference, Table,
    TableCell, Text,
)
from ._common import latex_reference_macro, table_grid


def _sanitize_table_cell(text: str) -> str:
    """Flatten a rendered cell so it can never break its one-line table row.

    Newlines / hard breaks become ``<br>`` (GFM renders it inside cells) and a
    literal ``|`` is escaped as ``\\|`` (understood back by the Markdown table
    parser's cell splitter and by GFM renderers).
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    text = re.sub(r'[ \t]*\n[ \t]*', '<br>', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.replace('|', r'\|')


def render_markdown(doc: Document) -> str:
    """Renders an AST Document to a Markdown string."""
    lines = [_render_node(child) for child in doc.children]
    return '\n\n'.join(filter(bool, lines)) + '\n'


def _render_node(node: Node) -> str:
    render = _RENDERERS.get(type(node))
    return render(node) if render else ""


def _inline(nodes: list[Node]) -> str:
    return ''.join(_render_node(c) for c in nodes)


def _quote(lines: list[str]) -> str:
    """Prefix every line with "> " (a bare ">" for an empty one)."""
    return '\n'.join(f"> {line}" if line.strip() else ">" for line in lines)


def _heading(node: Heading) -> str:
    return f"{'#' * node.level} {_inline(node.children)}"


def _paragraph(node: Paragraph) -> str:
    return _inline(node.children).strip().replace('\n', '  \n')


def _code_block(node: CodeBlock) -> str:
    return f"```{node.language or ''}\n{node.code}\n```"


def _list(node: ListBlock) -> str:
    items = []
    for i, item in enumerate(node.items):
        prefix = f"{i+1}." if node.ordered else "-"
        rendered_parts = []
        for j, child in enumerate(item.children):
            rendered_child = _render_node(child)
            if not rendered_child.strip():
                continue
            if j == 0 and isinstance(child, Paragraph):
                # The first paragraph goes on the bullet/number line
                rendered_parts.append(rendered_child)
            else:
                # Other blocks go on their own lines, indented by 4 spaces
                lines = rendered_child.split('\n')
                rendered_parts.append('\n'.join(f"    {line}" if line.strip() else "" for line in lines))
        body = '\n'.join(rendered_parts).strip()
        items.append(f"{prefix} {body}")
    return '\n'.join(items)


def _table(node: Table) -> str:
    headers, rows, ncols = table_grid(node)
    if not ncols:
        return ""
    header_cells = [_sanitize_table_cell(_render_node(c)) for c in headers] or [""] * ncols
    lines = ["| " + " | ".join(header_cells) + " |", "|" + "|".join(["---"] * ncols) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(_sanitize_table_cell(_render_node(c)) for c in row) + " |")
    return '\n'.join(lines)


def _table_cell(node: TableCell) -> str:
    return _inline(node.children).strip()


def _text(node: Text) -> str:
    content = node.content
    if node.italic: content = f"_{content}_"
    if node.bold: content = f"**{content}**"
    if node.strikethrough: content = f"~~{content}~~"
    return content


def _link(node: Link) -> str:
    title_str = f' "{node.title}"' if node.title else ''
    return f"[{_inline(node.content)}]({node.url}{title_str})"


def _image(node: Image) -> str:
    title_str = f' "{node.title}"' if node.title else ''
    return f'![{node.alt}]({node.src}{title_str})'


def _block_quote(node: BlockQuote) -> str:
    lines = '\n'.join(_render_node(c) for c in node.children).split('\n')
    if node.alert_type:
        lines.insert(0, f"[!{node.alert_type}]")
    return _quote(lines)


def _abstract(node: Abstract) -> str:
    lines = '\n'.join(_render_node(c) for c in node.children).split('\n')
    return _quote(["[!IMPORTANT]", "**Abstract**", *lines])


def _equation(node: Equation) -> str:
    return f"${node.code}$" if node.inline else f"$$\n{node.code}\n$$"


_RENDERERS = {
    Heading: _heading,
    Paragraph: _paragraph,
    CodeBlock: _code_block,
    ListBlock: _list,
    Table: _table,
    TableCell: _table_cell,
    Text: _text,
    Link: _link,
    Image: _image,
    CodeInline: lambda node: f"`{node.code}`",
    # The enclosing paragraph turns every "\n" into a hard break ("  \n")
    LineBreak: lambda node: "\n",
    BlockQuote: _block_quote,
    HorizontalRule: lambda node: "---",
    Equation: _equation,
    Abstract: _abstract,
    **{cls: lambda node: latex_reference_macro(node, _inline) for cls in (Footnote, Citation, Reference, Label)},
}
