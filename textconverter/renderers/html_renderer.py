from __future__ import annotations
import html
import urllib.parse

from ..ast import (
    Abstract, BlockQuote, Citation, CodeBlock, CodeInline, Document, Equation, Footnote, Heading,
    HorizontalRule, Image, Label, LineBreak, Link, ListBlock, ListItem, Node, Paragraph, Reference,
    Table, TableCell, Text,
)
from ._common import latex_reference_macro, plain_text, table_grid
from .templates import get_template

# Link schemes that run code when clicked; such links are rendered inert.
_UNSAFE_SCHEMES = ("javascript", "vbscript", "data")


def render_html(doc: Document, template_name: str = "plain") -> str:
    """Renders an AST Document to an HTML string."""
    parts = [_metadata(doc), *(_render_node(child) for child in doc.children)]
    body_str = '\n'.join(filter(bool, parts))
    return (get_template(template_name)
            .replace('{{title}}', html.escape(_page_title(doc)))
            .replace('{{content}}', body_str))


def _render_node(node: Node) -> str:
    render = _RENDERERS.get(type(node))
    return render(node) if render else ""


def _inline(nodes: list[Node]) -> str:
    return ''.join(_render_node(c) for c in nodes)


def _text_lines(nodes: list[Node]) -> str:
    """Inline nodes for a paragraph-like element: a newline in a text is a hard break."""
    return ''.join(_render_node(c).replace('\n', '<br />\n') for c in nodes)


def _page_title(doc: Document) -> str:
    """The text of the document title, else of the first level-1 heading, else "Document"."""
    source = doc.title or next(
        (n.children for n in doc.children if isinstance(n, Heading) and n.level == 1), [])
    return plain_text(source).strip() or "Document"


def _metadata(doc: Document) -> str:
    """The title block; ``tc-*`` classes let the HTML parser read the metadata back."""
    fields = [(doc.title, 'h1', 'tc-title'), (doc.author, 'p', 'tc-author'), (doc.date, 'p', 'tc-date')]
    lines = [f'<{tag} class="{cls}">{_text_lines(nodes)}</{tag}>' for nodes, tag, cls in fields if nodes]
    return '<div class="tc-meta">\n' + '\n'.join(lines) + '\n</div>' if lines else ""


def _safe_href(url: str) -> str:
    """The URL, or "#" when its scheme would run code (``javascript:`` and the like)."""
    scheme = urllib.parse.urlparse(url.strip()).scheme.lower()
    return "#" if scheme in _UNSAFE_SCHEMES else url


def _heading(node: Heading) -> str:
    return f"<h{node.level}>{_inline(node.children)}</h{node.level}>"


def _figure_image(node: Node) -> Image | None:
    """The captioned image a paragraph child shows as a figure (alone or as a link's content)."""
    if isinstance(node, Link) and len(node.content) == 1:
        node = node.content[0]
    return node if isinstance(node, Image) and (node.caption or node.label) else None


def _is_block(node: Node) -> bool:
    """A paragraph child that HTML only allows outside ``<p>``: a display formula or a figure."""
    return (isinstance(node, Equation) and not node.inline) or _figure_image(node) is not None


def _figure(node: Node) -> str:
    image = _figure_image(node)
    label = f' data-label="{html.escape(image.label)}"' if image.label else ''
    caption = f'\n<figcaption>{_text_lines(image.caption)}</figcaption>' if image.caption else ''
    return f'<figure{label}>\n{_render_node(node)}{caption}\n</figure>'


def _paragraph(node: Paragraph) -> str:
    """A paragraph; display formulas and figures split it, since ``<p>`` cannot hold them."""
    out: list[str] = []
    run: list[Node] = []

    def flush() -> None:
        text = _text_lines(run)
        if text.strip():
            out.append(f"<p>{text}</p>")
        run.clear()

    for child in node.children:
        if _is_block(child):
            flush()
            out.append(_figure(child) if _figure_image(child) else _render_node(child))
        else:
            run.append(child)
    flush()
    return '\n'.join(out)


def _code_block(node: CodeBlock) -> str:
    lang = f' class="language-{html.escape(node.language)}"' if node.language else ''
    return f"<pre><code{lang}>{html.escape(node.code)}</code></pre>"


def _list_item(item: ListItem) -> str:
    """A list item; a single paragraph is written without ``<p>``, as a tight list."""
    (first, *rest) = item.children or [Paragraph()]
    if not rest and isinstance(first, Paragraph) and not any(_is_block(c) for c in first.children):
        body = _text_lines(first.children)
    else:
        body = ''.join(_render_node(c) for c in item.children)
    if item.checked is not None:
        body = f'<input type="checkbox" disabled{" checked" if item.checked else ""} /> {body}'
    return f"<li>{body}</li>"


def _list(node: ListBlock) -> str:
    tag = "ol" if node.ordered else "ul"
    start = f' start="{node.start}"' if node.ordered and node.start != 1 else ''
    items = [_list_item(item) for item in node.items]
    return f"<{tag}{start}>\n" + "\n".join(items) + f"\n</{tag}>"


def _table(node: Table) -> str:
    headers, rows, ncols = table_grid(node)
    if not ncols:
        return ""
    label = f' data-label="{html.escape(node.label)}"' if node.label else ''
    lines = [f"<table{label}>"]
    if node.caption:
        lines.append(f"<caption>{_text_lines(node.caption)}</caption>")
    if headers:
        lines.append("<thead><tr>")
        lines.extend(f"<th>{_inline(h.children)}</th>" for h in headers)
        lines.append("</tr></thead>")
    if rows:
        lines.append("<tbody>")
        for row in rows:
            lines.append("<tr>")
            lines.extend(f"<td>{_inline(cell.children)}</td>" for cell in row)
            lines.append("</tr>")
        lines.append("</tbody>")
    lines.append("</table>")
    return '\n'.join(lines)


def _text(node: Text) -> str:
    content = html.escape(node.content)
    if node.italic: content = f"<i>{content}</i>"
    if node.bold: content = f"<b>{content}</b>"
    if node.strikethrough: content = f"<s>{content}</s>"
    if node.script: content = f"<{node.script}>{content}</{node.script}>"
    return content


def _link(node: Link) -> str:
    title_str = f' title="{html.escape(node.title)}"' if node.title else ''
    return f'<a href="{html.escape(_safe_href(node.url))}"{title_str}>{_inline(node.content)}</a>'


def _image(node: Image) -> str:
    title_str = f' title="{html.escape(node.title)}"' if node.title else ''
    return f'<img src="{html.escape(node.src)}" alt="{html.escape(node.alt)}"{title_str} />'


def _block_quote(node: BlockQuote) -> str:
    content = '\n'.join(_render_node(c) for c in node.children)
    if node.alert_type:
        alert_class = f"alert alert-{node.alert_type.lower()}"
        alert_header = f'<div class="alert-title">{node.alert_type}</div>'
        return f'<blockquote class="{alert_class}">\n{alert_header}\n{content}\n</blockquote>'
    return f"<blockquote>\n{content}\n</blockquote>"


def _abstract(node: Abstract) -> str:
    content = '\n'.join(_render_node(c) for c in node.children)
    return f'<blockquote class="alert-important">\n<div class="alert-title">Abstract</div>\n{content}\n</blockquote>'


def _equation(node: Equation) -> str:
    if node.inline:
        return f'<span class="math inline">\\({html.escape(node.code)}\\)</span>'
    if node.env:
        return f'<div class="math block">\\begin{{{node.env}}}\n{html.escape(node.code)}\n\\end{{{node.env}}}</div>'
    return f'<div class="math block">$$\n{html.escape(node.code)}\n$$</div>'


_RENDERERS = {
    Heading: _heading,
    Paragraph: _paragraph,
    CodeBlock: _code_block,
    ListBlock: _list,
    Table: _table,
    TableCell: lambda node: _inline(node.children),
    Text: _text,
    Link: _link,
    Image: _image,
    CodeInline: lambda node: f"<code>{html.escape(node.code)}</code>",
    LineBreak: lambda node: "<br />",
    BlockQuote: _block_quote,
    HorizontalRule: lambda node: "<hr />",
    Equation: _equation,
    Abstract: _abstract,
    # Reference macros stay visible as LaTeX; the span marks them for the HTML parser
    Footnote: lambda node: f'<span class="tc-footnote">\\footnote{{{_inline(node.content)}}}</span>',
    **{cls: lambda node: f'<span class="tc-ref">{latex_reference_macro(node, _inline, html.escape)}</span>'
       for cls in (Citation, Reference, Label)},
}
