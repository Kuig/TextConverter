from ..ast import Document, Paragraph, Heading, Text, Link, Image, CodeInline, CodeBlock, ListBlock, ListItem, Table, TableRow, TableCell, LineBreak, BlockQuote, HorizontalRule, Equation

def render_latex(doc: Document, image_handling: str = "auto") -> str:
    """Renders an AST Document to a compiling LaTeX document."""
    has_image = _has_type_in_doc(doc, Image)
    has_link = _has_type_in_doc(doc, Link)
    
    preamble = "\\documentclass{article}\n\\usepackage[utf8]{inputenc}\n"
    if has_image: preamble += "\\usepackage{graphicx}\n"
    if has_link: preamble += "\\usepackage{hyperref}\n"
    preamble += "\\begin{document}\n\n"
    
    body = []
    for child in doc.children:
        rendered = _render_node(child, image_handling)
        if rendered:
            body.append(rendered)
            
    return preamble + '\n\n'.join(body) + "\n\n\\end{document}\n"

def _has_type_in_doc(doc: Document, cls) -> bool:
    def _check(node):
        if isinstance(node, cls): return True
        if hasattr(node, "children"):
            for c in node.children:
                if _check(c): return True
        if hasattr(node, "items"):
            for c in node.items:
                if _check(c): return True
        if hasattr(node, "rows"):
            for r in node.rows:
                for c in r.cells:
                    if _check(c): return True
        return False
        
    for child in doc.children:
        if _check(child): return True
    return False

def _escape_latex(text: str) -> str:
    # Convert Unicode typographic quotes back to LaTeX notation
    text = text.replace('\u201c', '``').replace('\u201d', "''")   # " "  → `` ''
    text = text.replace('\u2018', '`').replace('\u2019', "'")    # ' '  → ` '
    # basic escapes
    chars = {
        '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_',
        '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}', '\\': r'\textbackslash{}'
    }
    return "".join(chars.get(c, c) for c in text)

def _render_node(node, image_handling: str = "auto") -> str:
    if isinstance(node, Heading):
        cmd = ["section", "subsection", "subsubsection", "paragraph", "subparagraph"][min(node.level-1, 4)]
        content = ''.join(_render_node(c, image_handling) for c in node.children)
        return f"\\{cmd}{{{content}}}"
        
    elif isinstance(node, Paragraph):
        return ''.join(_render_node(c, image_handling) for c in node.children).strip()
        
    elif isinstance(node, CodeBlock):
        # Fallback to verbatim for 0-dep plain latex
        return f"\\begin{{verbatim}}\n{node.code}\n\\end{{verbatim}}"
        
    elif isinstance(node, ListBlock):
        env = "enumerate" if node.ordered else "itemize"
        items = []
        for item in node.items:
            content = ' \n    '.join(_render_node(c, image_handling) for c in item.children).strip()
            items.append(f"    \\item {content}")
        items_str = '\n'.join(items)
        return f"\\begin{{{env}}}\n{items_str}\n\\end{{{env}}}"
        
    elif isinstance(node, Table):
        if not node.headers and not node.rows: return ""
        num_cols = len(node.headers) if node.headers else (len(node.rows[0].cells) if node.rows else 0)
        col_spec = "|" + "|".join(["c"] * num_cols) + "|" if num_cols else "c"
        
        lines = [f"\\begin{{tabular}}{{{col_spec}}}", "\\hline"]
        
        if node.headers:
            headers = [_render_node(h, image_handling) for h in node.headers]
            lines.append(" & ".join(headers) + " \\\\")
            lines.append("\\hline")
            
        for row in node.rows:
            cells = [_render_node(c, image_handling) for c in row.cells]
            while len(cells) < num_cols: cells.append("")
            lines.append(" & ".join(cells) + " \\\\")
            lines.append("\\hline")
            
        lines.append("\\end{tabular}")
        return '\n'.join(lines)
        
    elif isinstance(node, TableCell):
        return ''.join(_render_node(c, image_handling) for c in node.children).strip()
        
    elif isinstance(node, Text):
        content = _escape_latex(node.content)
        if node.italic: content = f"\\textit{{{content}}}"
        if node.bold: content = f"\\textbf{{{content}}}"
        return content
        
    elif isinstance(node, Link):
        # using hyperref
        content_str = ''.join(_render_node(c, image_handling) for c in node.content)
        url = _escape_latex(node.url)
        return f"\\href{{{url}}}{{{content_str}}}"
        
    elif isinstance(node, Image):
        if hasattr(node, 'description') and node.description:
            desc = _escape_latex(node.description)
            if not getattr(node, 'render_metadata', True) or image_handling == "auto_latex":
                return desc
            src = _escape_latex(node.src)
            cat_str = f" - Class: {_escape_latex(node.category)}" if getattr(node, 'category', None) else ""
            return f"\\textbf{{[Image Reference: {src}{cat_str}]}}\\\\\\textbf{{----- Start of picture description -----}}\\\\{desc}\\\\\\textbf{{----- End of picture description -----}}"
        return f"\\includegraphics{{{getattr(node, 'src', getattr(node, 'url', ''))}}}"
        
    elif isinstance(node, CodeInline):
        return f"\\texttt{{{_escape_latex(node.code)}}}"
        
    elif isinstance(node, LineBreak):
        return "\\\\"
        
    elif isinstance(node, BlockQuote):
        content = '\n'.join(_render_node(c, image_handling) for c in node.children)
        if node.alert_type:
            return f"\\begin{{quote}}\n\\textbf{{{_escape_latex(node.alert_type)}}}\\\\\n{content}\n\\end{{quote}}"
        else:
            return f"\\begin{{quote}}\n{content}\n\\end{{quote}}"
            
    elif isinstance(node, HorizontalRule):
        return "\\noindent\\rule{\\textwidth}{0.4pt}"
        
    elif isinstance(node, Equation):
        if node.inline:
            return f"${node.code}$"
        else:
            return f"\\begin{{equation}}\n{node.code}\n\\end{{equation}}"
            
    else:
        from ..ast import Abstract, Footnote, Citation, Reference, Label
        if isinstance(node, Abstract):
            content = '\n'.join(_render_node(c, image_handling) for c in node.children)
            return f"\\begin{{abstract}}\n{content}\n\\end{{abstract}}"
        elif isinstance(node, Footnote):
            return f"\\footnote{{{''.join(_render_node(c, image_handling) for c in node.content)}}}"
        elif isinstance(node, Citation):
            return f"\\{node.style}{{{','.join(node.keys)}}}"
        elif isinstance(node, Reference):
            return f"\\ref{{{node.label}}}"
        elif isinstance(node, Label):
            return f"\\label{{{node.name}}}"
            
    return ""
