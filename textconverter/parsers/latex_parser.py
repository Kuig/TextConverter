import re
from typing import List

from ..ast import (
    Document, Paragraph, Heading, Text, Link, Image, CodeInline,
    CodeBlock, ListBlock, ListItem, Table, TableRow, TableCell, InlineElement
)

def parse_latex(text: str) -> Document:
    """Parses a basic subset of LaTeX into AST Document."""
    doc = Document()
    
    # Strip out preamble if document environment exists
    m_doc = re.search(r'\\begin\{document\}(.*?)\\end\{document\}', text, re.DOTALL)
    if m_doc:
        text = m_doc.group(1)
        
    # Strip comments (not extremely safe with escaped %, but enough for minimal deps)
    text = re.sub(r'(?<!\\)%.*$', '', text, flags=re.MULTILINE)
    
    # Match block elements
    env_pattern = re.compile(
        r'\\(section|subsection|subsubsection|paragraph)\{([^}]+)\}|'
        r'\\begin\{(itemize|enumerate)\}(.*?)\\end\{\3\}|'
        r'\\begin\{(verbatim|lstlisting)\}(.*?)\\end\{\5\}|'
        r'\\begin\{tabular\}\{[^}]*\}(.*?)\\end\{tabular\}',
        re.DOTALL
    )
    
    pos = 0
    while pos < len(text):
        m = env_pattern.search(text, pos)
        if not m:
            chunk = text[pos:].strip()
            if chunk:
                for p_text in re.split(r'\n\s*\n', chunk):
                    if p_text.strip():
                        doc.children.append(Paragraph(children=parse_inline_latex(p_text.strip())))
            break
            
        if m.start() > pos:
            chunk = text[pos:m.start()].strip()
            if chunk:
                for p_text in re.split(r'\n\s*\n', chunk):
                    if p_text.strip():
                        doc.children.append(Paragraph(children=parse_inline_latex(p_text.strip())))
                        
        groups = m.groups()
        if groups[0]: # section etc
            level = {'section': 1, 'subsection': 2, 'subsubsection': 3, 'paragraph': 4}.get(groups[0], 1)
            doc.children.append(Heading(level=level, children=parse_inline_latex(groups[1])))
        elif groups[2]: # list
            ordered = (groups[2] == 'enumerate')
            lb = ListBlock(ordered=ordered)
            items = re.split(r'\\item', groups[3])
            for item in items[1:]:
                lb.items.append(ListItem(children=[Paragraph(children=parse_inline_latex(item.strip()))]))
            doc.children.append(lb)
        elif groups[4]: # code
            doc.children.append(CodeBlock(code=groups[5].strip(), language=None))
        elif groups[6] is not None: # table
            doc.children.append(_parse_latex_table(groups[6].strip()))
            
        pos = m.end()
        
    return doc

def _parse_latex_table(content: str) -> Table:
    table = Table()
    rows = content.split('\\\\')
    
    for i, row in enumerate(rows):
        row = row.replace('\\hline', '').strip()
        if not row:
            continue
        cells = [c.strip() for c in row.split('&')]
        
        if i == 0:
            table.headers = [TableCell(children=parse_inline_latex(c)) for c in cells]
        else:
            table.rows.append(TableRow(cells=[TableCell(children=parse_inline_latex(c)) for c in cells]))
            
    return table

def parse_inline_latex(text: str) -> List[InlineElement]:
    elements = []
    
    # Match inline elements: bold, italic, href, url, includegraphics
    pattern = re.compile(
        r'\\textbf\{([^}]+)\}|'
        r'\\textit\{([^}]+)\}|'
        r'\\href\{([^}]+)\}\{([^}]+)\}|'
        r'\\url\{([^}]+)\}|'
        r'\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}|'
        r'\\texttt\{([^}]+)\}'
    )
    
    pos = 0
    while pos < len(text):
        m = pattern.search(text, pos)
        if not m:
            if pos < len(text):
                elements.append(Text(content=text[pos:]))
            break
            
        if m.start() > pos:
            elements.append(Text(content=text[pos:m.start()]))
            
        g = m.groups()
        if g[0]:
            elements.append(Text(content=g[0], bold=True))
        elif g[1]:
            elements.append(Text(content=g[1], italic=True))
        elif g[2]: # href
            elements.append(Link(url=g[2], title=None, content=parse_inline_latex(g[3])))
        elif g[4]: # url
            elements.append(Link(url=g[4], title=None, content=[Text(content=g[4])]))
        elif g[5]: # includegraphics
            elements.append(Image(src=g[5], alt="image"))
        elif g[6]: # texttt
            elements.append(CodeInline(code=g[6]))
            
        pos = m.end()
        
    return elements
