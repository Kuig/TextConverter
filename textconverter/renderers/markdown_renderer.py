from ..ast import Document, Paragraph, Heading, Text, Link, Image, CodeInline, CodeBlock, ListBlock, ListItem, Table, TableRow, TableCell, LineBreak, BlockQuote, HorizontalRule, Equation

def render_markdown(doc: Document) -> str:
    """Renders an AST Document to a Markdown string."""
    lines = []
    for child in doc.children:
        rendered = _render_node(child)
        if rendered is not None:
            lines.append(rendered)
    return '\n\n'.join(filter(bool, lines)) + '\n'

def _render_node(node) -> str:
    if isinstance(node, Heading):
        return f"{'#' * node.level} {''.join(_render_node(c) for c in node.children)}"
        
    elif isinstance(node, Paragraph):
        content = ''.join(_render_node(c) for c in node.children).strip()
        return content.replace('\n', '  \n')
        
    elif isinstance(node, CodeBlock):
        lang = node.language or ''
        return f"```{lang}\n{node.code}\n```"
        
    elif isinstance(node, ListBlock):
        items = []
        for i, item in enumerate(node.items):
            prefix = f"{i+1}." if node.ordered else "-"
            
            rendered_parts = []
            for j, child in enumerate(item.children):
                rendered_child = _render_node(child)
                if not rendered_child.strip():
                    continue
                    
                if j == 0 and isinstance(child, Paragraph):
                    # Render the first paragraph inline with the list item bullet/number
                    rendered_parts.append(rendered_child)
                else:
                    # Render other blocks (or subsequent paragraphs) on new lines, indented by 4 spaces
                    lines = rendered_child.split('\n')
                    indented_lines = [f"    {line}" if line.strip() else "" for line in lines]
                    rendered_parts.append('\n'.join(indented_lines))
            
            item_content = '\n'.join(rendered_parts).strip()
            items.append(f"{prefix} {item_content}")
        return '\n'.join(items)
        
    elif isinstance(node, Table):
        if not node.headers and not node.rows: return ""
        headers = [_render_node(c) for c in node.headers] if node.headers else []
        if not headers and node.rows:
            headers = [""] * len(node.rows[0].cells)
            
        lines = []
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        
        for row in node.rows:
            cells = [_render_node(c) for c in row.cells]
            while len(cells) < len(headers):
                cells.append("")
            lines.append("| " + " | ".join(cells) + " |")
        return '\n'.join(lines)
        
    elif isinstance(node, TableCell):
        return ''.join(_render_node(c) for c in node.children).strip()
        
    elif isinstance(node, Text):
        content = node.content
        if node.italic: content = f"_{content}_"
        if node.bold: content = f"**{content}**"
        return content
        
    elif isinstance(node, Link):
        title_str = f' "{node.title}"' if node.title else ''
        content_str = ''.join(_render_node(c) for c in node.content)
        return f"[{content_str}]({node.url}{title_str})"
        
    elif isinstance(node, Image):
        if hasattr(node, 'description') and node.description:
            if not getattr(node, 'render_metadata', True):
                return node.description
            cat_str = f" - Class: {node.category}" if getattr(node, 'category', None) else ""
            return f"**[Image Reference: {node.src}{cat_str}]**  \n**----- Start of picture description -----**  \n{node.description}  \n**----- End of picture description -----**\n\n"
        title_str = f' "{node.title}"' if node.title else ''
        return f'![{node.alt}]({node.url if hasattr(node, "url") else node.src}{title_str})'
        
    elif isinstance(node, CodeInline):
        return f"`{node.code}`"
        
    elif isinstance(node, LineBreak):
        return "  \n"
        
    elif isinstance(node, BlockQuote):
        content = '\n'.join(_render_node(c) for c in node.children)
        lines = content.split('\n')
        if node.alert_type:
            lines.insert(0, f"[!{node.alert_type}]")
        
        bq_lines = []
        for line in lines:
            bq_lines.append(f"> {line}" if line.strip() else ">")
        return '\n'.join(bq_lines)
        
    elif isinstance(node, HorizontalRule):
        return "---"
        
    elif isinstance(node, Equation):
        if node.inline:
            return f"${node.code}$"
        else:
            return f"$$\n{node.code}\n$$"
            
    else:
        from ..ast import Abstract, Footnote, Citation, Reference, Label
        if isinstance(node, Abstract):
            content = '\n'.join(_render_node(c) for c in node.children)
            lines = content.split('\n')
            lines.insert(0, "[!IMPORTANT]")
            lines.insert(1, "**Abstract**")
            
            bq_lines = []
            for line in lines:
                bq_lines.append(f"> {line}" if line.strip() else ">")
            return '\n'.join(bq_lines)
        elif isinstance(node, Footnote):
            return f"\\footnote{{{''.join(_render_node(c) for c in node.content)}}}"
        elif isinstance(node, Citation):
            return f"\\{node.style}{{{','.join(node.keys)}}}"
        elif isinstance(node, Reference):
            return f"\\ref{{{node.label}}}"
        elif isinstance(node, Label):
            return f"\\label{{{node.name}}}"
        
    return ""
