from __future__ import annotations
import re
from ..ast import (
    Abstract, BlockQuote, Citation, CodeBlock, CodeInline, Document, Equation, Footnote, Heading,
    HorizontalRule, Image, Label, LineBreak, Link, ListBlock, Node, Paragraph, Reference, Table,
    TableCell, Text, walk,
)
from ._common import latex_reference_macro, table_grid

# A line break at the start or end of a paragraph is a LaTeX error ("There's no line here to end").
_EDGE_BREAKS = re.compile(r'^(?:\s*\\\\)+\s*|\s*(?:\\\\\s*)+$')


def render_latex(doc: Document) -> str:
    """Renders an AST Document to a compiling LaTeX document.

    The preamble loads only the packages the document needs: ``graphicx``
    (images), ``hyperref`` (links), ``amsmath``/``amssymb`` (equations),
    ``natbib`` (``\\citet``/``\\citep``) and ``ulem`` (strikethrough).
    """
    nodes = list(walk(doc))
    packages = ["\\usepackage[utf8]{inputenc}"]
    if any(isinstance(n, Image) for n in nodes):
        packages.append("\\usepackage{graphicx}")
    if any(isinstance(n, Link) for n in nodes):
        packages.append("\\usepackage{hyperref}")
    if any(isinstance(n, Equation) for n in nodes):
        packages += ["\\usepackage{amsmath}", "\\usepackage{amssymb}"]
    if any(isinstance(n, Citation) and n.style in ("citet", "citep") for n in nodes):
        packages.append("\\usepackage{natbib}")
    if any(isinstance(n, Text) and n.strikethrough for n in nodes):
        # normalem keeps \emph as italics instead of underlining
        packages.append("\\usepackage[normalem]{ulem}")

    preamble = "\\documentclass{article}\n" + "".join(f"{p}\n" for p in packages) + "\\begin{document}\n\n"

    body = [r for r in (_render_node(child) for child in doc.children) if r]
    return preamble + '\n\n'.join(body) + "\n\n\\end{document}\n"


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


def _escape_url(url: str) -> str:
    """Escape a URL for ``\\href``.

    ``~`` stays literal (hyperref reads it as is; ``\\textasciitilde{}`` broke
    the link), characters that only have a text-mode command (backslash,
    braces, caret) are percent-encoded, and the rest is escaped as in text so
    the link also survives inside a table cell or a section title.
    """
    for char, code in (('\\', '%5C'), ('{', '%7B'), ('}', '%7D'), ('^', '%5E')):
        url = url.replace(char, code)
    return _escape_latex(url.replace('~', '\x00')).replace('\x00', '~')


def _render_node(node: Node) -> str:
    render = _RENDERERS.get(type(node))
    return render(node) if render else ""


def _inline(nodes: list[Node]) -> str:
    return ''.join(_render_node(c) for c in nodes)


def _one_line(rendered: str) -> str:
    """Keep inline content on one line, for arguments that cannot hold a break (cells, titles)."""
    rendered = rendered.replace('\\\\', ' ').replace('\r', ' ').replace('\n', ' ')
    return re.sub(r'\s{2,}', ' ', rendered).strip()


def _heading(node: Heading) -> str:
    cmd = ["section", "subsection", "subsubsection", "paragraph", "subparagraph"][min(node.level-1, 4)]
    return f"\\{cmd}{{{_one_line(_inline(node.children))}}}"


def _paragraph(node: Paragraph) -> str:
    return _EDGE_BREAKS.sub('', _inline(node.children).strip())


def _code_block(node: CodeBlock) -> str:
    # verbatim needs no package
    return f"\\begin{{verbatim}}\n{node.code}\n\\end{{verbatim}}"


def _list(node: ListBlock) -> str:
    env = "enumerate" if node.ordered else "itemize"
    items = []
    for item in node.items:
        content = ' \n    '.join(_render_node(c) for c in item.children).strip()
        items.append(f"    \\item {content}")
    items_str = '\n'.join(items)
    return f"\\begin{{{env}}}\n{items_str}\n\\end{{{env}}}"


def _table(node: Table) -> str:
    headers, rows, ncols = table_grid(node)
    if not ncols:
        return ""
    lines = [f"\\begin{{tabular}}{{|{'|'.join(['c'] * ncols)}|}}", "\\hline"]
    for row in ([headers] if headers else []) + rows:
        lines.append(" & ".join(_render_node(c) for c in row) + " \\\\")
        lines.append("\\hline")
    lines.append("\\end{tabular}")
    return '\n'.join(lines)


def _text(node: Text) -> str:
    content = _escape_latex(node.content)
    if node.italic: content = f"\\textit{{{content}}}"
    if node.bold: content = f"\\textbf{{{content}}}"
    if node.strikethrough: content = f"\\sout{{{content}}}"
    return content


def _link(node: Link) -> str:
    return f"\\href{{{_escape_url(node.url)}}}{{{_inline(node.content)}}}"


def _block_quote(node: BlockQuote) -> str:
    content = '\n'.join(_render_node(c) for c in node.children)
    if node.alert_type:
        return f"\\begin{{quote}}\n\\textbf{{{_escape_latex(node.alert_type)}}}\\\\\n{content}\n\\end{{quote}}"
    return f"\\begin{{quote}}\n{content}\n\\end{{quote}}"


def _equation(node: Equation) -> str:
    if node.inline:
        return f"${node.code}$"
    if node.env:
        return f"\\begin{{{node.env}}}\n{node.code}\n\\end{{{node.env}}}"
    if '&' in node.code or '\\\\' in node.code:
        # Alignment points or several lines: only valid inside an alignment environment.
        return f"\\begin{{equation}}\n\\begin{{aligned}}\n{node.code}\n\\end{{aligned}}\n\\end{{equation}}"
    return f"\\begin{{equation}}\n{node.code}\n\\end{{equation}}"


def _abstract(node: Abstract) -> str:
    content = '\n'.join(_render_node(c) for c in node.children)
    return f"\\begin{{abstract}}\n{content}\n\\end{{abstract}}"


_RENDERERS = {
    Heading: _heading,
    Paragraph: _paragraph,
    CodeBlock: _code_block,
    ListBlock: _list,
    Table: _table,
    TableCell: lambda node: _one_line(_inline(node.children)),
    Text: _text,
    Link: _link,
    Image: lambda node: f"\\includegraphics{{{node.src}}}",
    CodeInline: lambda node: f"\\texttt{{{_escape_latex(node.code)}}}",
    LineBreak: lambda node: "\\\\",
    BlockQuote: _block_quote,
    HorizontalRule: lambda node: "\\noindent\\rule{\\textwidth}{0.4pt}",
    Equation: _equation,
    Abstract: _abstract,
    **{cls: lambda node: latex_reference_macro(node, _inline) for cls in (Footnote, Citation, Reference, Label)},
}
