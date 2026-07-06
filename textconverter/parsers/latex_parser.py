import re
from typing import List

from ..ast import (
    Document, Paragraph, Heading, Text, Link, Image, CodeInline,
    CodeBlock, ListBlock, ListItem, Table, TableRow, TableCell, InlineElement,
    BlockQuote
)

def _normalize_latex_quotes(text: str) -> str:
    """Convert LaTeX typographic quote sequences to Unicode curly quotes.

    Handles double quotes (``...'' → "...") and single quotes (`...' → '...').
    Applied only to plain text chunks, never to code/inline-command arguments.
    """
    # Double quotes: ``text'' → "text"
    text = re.sub(r"``(.*?)''", lambda m: '\u201c' + m.group(1) + '\u201d', text, flags=re.DOTALL)
    # Single quotes: `text' → 'text'
    text = re.sub(r"`(.*?)'", lambda m: '\u2018' + m.group(1) + '\u2019', text, flags=re.DOTALL)
    return text

def parse_latex(text: str) -> Document:
    """Parses a basic subset of LaTeX into AST Document."""
    doc = Document()

    # Extract \title{...} from the preamble before stripping it
    title_text = None
    m_title = re.search(r'\\title\{([^}]+)\}', text)
    if m_title:
        title_text = m_title.group(1).strip()

    # Strip out preamble if document environment exists
    m_doc = re.search(r'\\begin\{document\}(.*?)\\end\{document\}', text, re.DOTALL)
    if m_doc:
        text = m_doc.group(1)

    # Strip \maketitle command (already handled via \title{} above)
    text = re.sub(r'\\maketitle\b', '', text)

    # Strip comments (not extremely safe with escaped %, but enough for minimal deps)
    text = re.sub(r'(?<!\\)%.*$', '', text, flags=re.MULTILINE)

    # If a title was found, prepend it as a level-1 bold heading
    if title_text:
        doc.children.append(Heading(level=1, children=[Text(content=title_text, bold=True)]))

    # Match block elements (including abstract environment)
    env_pattern = re.compile(
        r'\\(section|subsection|subsubsection|paragraph)\*?\{([^}]+)\}|'
        r'\\begin\{(abstract)\}(.*?)\\end\{abstract\}|'
        r'\\begin\{(itemize|enumerate)\}(.*?)\\end\{\5\}|'
        r'\\begin\{(verbatim|lstlisting)\}(.*?)\\end\{\7\}|'
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
        if groups[0]:  # section/subsection/etc (with optional *)
            level = {'section': 1, 'subsection': 2, 'subsubsection': 3, 'paragraph': 4}.get(groups[0], 1)
            doc.children.append(Heading(level=level, children=parse_inline_latex(groups[1])))
        elif groups[2]:  # abstract environment
            abstract_bq = BlockQuote()
            abstract_bq.children.append(Heading(level=2, children=[Text(content="Abstract")]))
            for p_text in re.split(r'\n\s*\n', groups[3].strip()):
                if p_text.strip():
                    abstract_bq.children.append(Paragraph(children=parse_inline_latex(p_text.strip())))
            doc.children.append(abstract_bq)
        elif groups[4]:  # list (itemize/enumerate)
            ordered = (groups[4] == 'enumerate')
            lb = ListBlock(ordered=ordered)
            items = re.split(r'\\item', groups[5])
            for item in items[1:]:
                lb.items.append(ListItem(children=[Paragraph(children=parse_inline_latex(item.strip()))]))
            doc.children.append(lb)
        elif groups[6]:  # verbatim/lstlisting
            doc.children.append(CodeBlock(code=groups[7].strip(), language=None))
        elif groups[8] is not None:  # tabular
            doc.children.append(_parse_latex_table(groups[8].strip()))

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

    # Match inline elements: bold, italic, href, url, includegraphics, texttt
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
                # Normalize typographic quotes only in plain text residuals
                plain = _normalize_latex_quotes(text[pos:])
                elements.append(Text(content=plain))
            break

        if m.start() > pos:
            # Normalize typographic quotes only in plain text between commands
            plain = _normalize_latex_quotes(text[pos:m.start()])
            elements.append(Text(content=plain))

        g = m.groups()
        if g[0]:
            elements.append(Text(content=g[0], bold=True))
        elif g[1]:
            elements.append(Text(content=g[1], italic=True))
        elif g[2]:  # href
            elements.append(Link(url=g[2], title=None, content=parse_inline_latex(g[3])))
        elif g[4]:  # url
            elements.append(Link(url=g[4], title=None, content=[Text(content=g[4])]))
        elif g[5]:  # includegraphics
            elements.append(Image(src=g[5], alt="image"))
        elif g[6]:  # texttt — code inline: quotes NOT normalized here
            elements.append(CodeInline(code=g[6]))

        pos = m.end()

    return elements

