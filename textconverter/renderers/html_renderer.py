from __future__ import annotations
import html
import urllib.parse

from ..ast import (
    Abstract, BlockQuote, Citation, CodeBlock, CodeInline, Document, Equation, Footnote, Heading,
    HorizontalRule, Image, Label, LineBreak, Link, ListBlock, Node, Paragraph, Reference, Table,
    TableCell, Text,
)
from ._common import latex_reference_macro, table_grid
from .templates import get_template

# Link schemes that run code when clicked; such links are rendered inert.
_UNSAFE_SCHEMES = ("javascript", "vbscript", "data")


def render_html(doc: Document, template_name: str = "plain") -> str:
    """Renders an AST Document to an HTML string."""
    body_str = '\n'.join(filter(bool, (_render_node(child) for child in doc.children)))
    return get_template(template_name).replace('{{content}}', body_str)


def _render_node(node: Node) -> str:
    render = _RENDERERS.get(type(node))
    return render(node) if render else ""


def _inline(nodes: list[Node]) -> str:
    return ''.join(_render_node(c) for c in nodes)


def _safe_href(url: str) -> str:
    """The URL, or "#" when its scheme would run code (``javascript:`` and the like)."""
    scheme = urllib.parse.urlparse(url.strip()).scheme.lower()
    return "#" if scheme in _UNSAFE_SCHEMES else url


def _heading(node: Heading) -> str:
    return f"<h{node.level}>{_inline(node.children)}</h{node.level}>"


def _paragraph(node: Paragraph) -> str:
    rendered = []
    for c in node.children:
        r = _render_node(c)
        if isinstance(c, Equation) and not c.inline:
            rendered.append(r)
        else:
            rendered.append(r.replace('\n', '<br />\n'))
    return f"<p>{''.join(rendered)}</p>"


def _code_block(node: CodeBlock) -> str:
    lang = f' class="language-{html.escape(node.language)}"' if node.language else ''
    return f"<pre><code{lang}>{html.escape(node.code)}</code></pre>"


def _list(node: ListBlock) -> str:
    tag = "ol" if node.ordered else "ul"
    items = [f"<li>{_inline(item.children)}</li>" for item in node.items]
    return f"<{tag}>\n" + "\n".join(items) + f"\n</{tag}>"


def _table(node: Table) -> str:
    headers, rows, ncols = table_grid(node)
    if not ncols:
        return ""
    lines = ["<table>"]
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
    **{cls: lambda node: latex_reference_macro(node, _inline, html.escape)
       for cls in (Footnote, Citation, Reference, Label)},
}
