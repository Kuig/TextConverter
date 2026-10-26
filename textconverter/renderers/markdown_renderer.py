from __future__ import annotations
import re
from ..ast import (
    Abstract, BlockQuote, Citation, CodeBlock, CodeInline, Document, Equation, Footnote, Heading,
    HorizontalRule, Image, Label, LineBreak, Link, ListBlock, Node, Paragraph, Reference, Table,
    TableCell, Text,
)
from ._common import latex_reference_macro, table_grid

# Characters of literal text that Markdown would read as markup (see _escape).
_MD_SPECIAL = re.compile(
    r'\\(?=[!-/:-@\[-`{-~]|(?:footnote|citet|citep|cite|ref|label)(?![a-zA-Z])|$)'
    r'|[*`\[\]$]'
    r'|(?<!\w)_|_(?!\w)'
    r'|~(?=~)|(?<=~)~'
    r'|<(?=br\b)'
)
# A block marker at the start of a line: heading, quote, list item or rule.
_LINE_START = re.compile(r'^([ \t]*)(#{1,6}(?=[ \t]|$)|>|[-+](?=[ \t])|-(?=--)|\d+\.(?=[ \t]))',
                         re.MULTILINE)


def _escape_line_start(m: re.Match) -> str:
    indent, marker = m.groups()
    if marker[-1] == '.':  # "1." -> "1\."
        return f"{indent}{marker[:-1]}\\."
    return f"{indent}\\{marker}"


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
    # A line of the paragraph that starts like a block (heading, quote, item, rule) is escaped
    content = _LINE_START.sub(_escape_line_start, _inline(node.children).strip())
    return content.replace('\n', '  \n')


def _code_block(node: CodeBlock) -> str:
    # The fence must be longer than any backtick run in the code
    longest = max((len(run) for run in re.findall(r'`+', node.code)), default=0)
    fence = '`' * max(3, longest + 1)
    return f"{fence}{node.language or ''}\n{node.code}\n{fence}"


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


def _escape(text: str) -> str:
    """Backslash-escape what the Markdown parser would read as markup in literal text.

    Escapes ``*``, `````, ``[``, ``]``, ``$``, an underscore at a word edge,
    doubled ``~``, ``<br``, and a backslash that would start an escape or a
    reference macro. Block markers at the start of a line are escaped per
    paragraph (see ``_paragraph``).
    """
    return _MD_SPECIAL.sub(lambda m: '\\' + m.group(0), text)


def _escape_title(title: str | None) -> str:
    return f' "{title.replace(chr(34), chr(92) + chr(34))}"' if title else ''


def _destination(url: str) -> str:
    """A link or image URL; in ``<...>`` when it has spaces or unbalanced parentheses."""
    depth = 0
    for ch in url:
        depth += {'(': 1, ')': -1}.get(ch, 0)
        if depth < 0:
            break
    if depth or re.search(r'\s', url) or not url:
        return f"<{url}>"
    return url


def _text(node: Text) -> str:
    content = _escape(node.content)
    if node.italic: content = f"_{content}_"
    if node.bold: content = f"**{content}**"
    if node.strikethrough: content = f"~~{content}~~"
    return content


def _link(node: Link) -> str:
    return f"[{_inline(node.content)}]({_destination(node.url)}{_escape_title(node.title)})"


def _image(node: Image) -> str:
    alt = re.sub(r'([\\\[\]])', r'\\\1', node.alt)
    return f'![{alt}]({_destination(node.src)}{_escape_title(node.title)})'


def _code_inline(node: CodeInline) -> str:
    """A code span fenced by more backticks than the code holds in a row."""
    longest = max((len(run) for run in re.findall(r'`+', node.code)), default=0)
    fence = '`' * (longest + 1)
    pad = ' ' if node.code.startswith('`') or node.code.endswith('`') else ''
    return f"{fence}{pad}{node.code}{pad}{fence}"


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
    CodeInline: _code_inline,
    # The enclosing paragraph turns every "\n" into a hard break ("  \n")
    LineBreak: lambda node: "\n",
    BlockQuote: _block_quote,
    HorizontalRule: lambda node: "---",
    Equation: _equation,
    Abstract: _abstract,
    **{cls: lambda node: latex_reference_macro(node, _inline) for cls in (Footnote, Citation, Reference, Label)},
}
