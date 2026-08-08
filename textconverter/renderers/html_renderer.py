from __future__ import annotations
from ..ast import Document, Paragraph, Heading, Text, Link, Image, CodeInline, CodeBlock, ListBlock, ListItem, Table, TableRow, TableCell, LineBreak, BlockQuote, HorizontalRule, Equation
from .templates import get_template

import html

def render_html(doc: Document, template_name: str = "plain") -> str:
    """Renders an AST Document to an HTML string."""
    body_content = []
    for child in doc.children:
        rendered = _render_node(child)
        if rendered:
            body_content.append(rendered)
            
    body_str = '\n'.join(body_content)
    
    template = get_template(template_name)
    return template.replace('{{content}}', body_str)

def _render_node(node) -> str:
    if isinstance(node, Heading):
        content = ''.join(_render_node(c) for c in node.children)
        return f"<h{node.level}>{content}</h{node.level}>"
        
    elif isinstance(node, Paragraph):
        rendered = []
        for c in node.children:
            r = _render_node(c)
            if isinstance(c, Equation) and not c.inline:
                rendered.append(r)
            else:
                rendered.append(r.replace('\n', '<br />\n'))
        return f"<p>{''.join(rendered)}</p>"
        
    elif isinstance(node, CodeBlock):
        lang = f' class="language-{html.escape(node.language)}"' if node.language else ''
        return f"<pre><code{lang}>{html.escape(node.code)}</code></pre>"
        
    elif isinstance(node, ListBlock):
        tag = "ol" if node.ordered else "ul"
        items = []
        for item in node.items:
            content = ''.join(_render_node(c) for c in item.children)
            items.append(f"<li>{content}</li>")
        return f"<{tag}>\n" + "\n".join(items) + f"\n</{tag}>"
        
    elif isinstance(node, Table):
        if not node.headers and not node.rows: return ""
        lines = ["<table>"]
        if node.headers:
            lines.append("<thead><tr>")
            for h in node.headers:
                lines.append(f"<th>{_render_node(h) if isinstance(h, Text) else ''.join(_render_node(c) for c in h.children)}</th>")
            lines.append("</tr></thead>")
            
        if node.rows:
            lines.append("<tbody>")
            for row in node.rows:
                lines.append("<tr>")
                for cell in row.cells:
                    content = ''.join(_render_node(c) for c in cell.children)
                    lines.append(f"<td>{content}</td>")
                lines.append("</tr>")
            lines.append("</tbody>")
            
        lines.append("</table>")
        return '\n'.join(lines)
        
    elif isinstance(node, Text):
        content = html.escape(node.content)
        if node.italic: content = f"<i>{content}</i>"
        if node.bold: content = f"<b>{content}</b>"
        return content
        
    elif isinstance(node, Link):
        title_str = f' title="{html.escape(node.title)}"' if node.title else ''
        content_str = ''.join(_render_node(c) for c in node.content)
        return f'<a href="{html.escape(node.url)}"{title_str}>{content_str}</a>'
        
    elif isinstance(node, Image):
        if hasattr(node, 'description') and node.description:
            if not getattr(node, 'render_metadata', True):
                return html.escape(node.description).replace(chr(10), "<br />")
            cat_str = f" - Class: {html.escape(node.category)}" if getattr(node, 'category', None) else ""
            return f'<p><strong>[Image Reference: {html.escape(node.src)}{cat_str}]</strong><br /><strong>----- Start of picture description -----</strong><br />{html.escape(node.description).replace(chr(10), "<br />")}<br /><strong>----- End of picture description -----</strong></p>'
        title_str = f' title="{html.escape(node.title)}"' if node.title else ''
        return f'<img src="{html.escape(node.url if hasattr(node, "url") else node.src)}" alt="{html.escape(node.alt)}"{title_str} />'
        
    elif isinstance(node, CodeInline):
        return f"<code>{html.escape(node.code)}</code>"
        
    elif isinstance(node, LineBreak):
        return "<br />"
        
    elif isinstance(node, BlockQuote):
        content = '\n'.join(_render_node(c) for c in node.children)
        if node.alert_type:
            alert_class = f"alert alert-{node.alert_type.lower()}"
            alert_header = f'<div class="alert-title">{node.alert_type}</div>'
            return f'<blockquote class="{alert_class}">\n{alert_header}\n{content}\n</blockquote>'
        else:
            return f"<blockquote>\n{content}\n</blockquote>"
            
    elif isinstance(node, HorizontalRule):
        return "<hr />"
        
    elif isinstance(node, Equation):
        if node.inline:
            return f'<span class="math inline">\\({html.escape(node.code)}\\)</span>'
        else:
            return f'<div class="math block">$$\n{html.escape(node.code)}\n$$</div>'
            
    else:
        from ..ast import Abstract, Footnote, Citation, Reference, Label
        if isinstance(node, Abstract):
            content = '\n'.join(_render_node(c) for c in node.children)
            return f'<blockquote class="alert-important">\n<div class="alert-title">Abstract</div>\n{content}\n</blockquote>'
        elif isinstance(node, Footnote):
            # Using <sup> or just literal fallback
            return f"\\footnote{{{''.join(_render_node(c) for c in node.content)}}}"
        elif isinstance(node, Citation):
            return f"\\{node.style}{{{html.escape(','.join(node.keys))}}}"
        elif isinstance(node, Reference):
            return f"\\ref{{{html.escape(node.label)}}}"
        elif isinstance(node, Label):
            return f"\\label{{{html.escape(node.name)}}}"
        
    return ""
