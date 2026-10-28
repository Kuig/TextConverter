from __future__ import annotations
import re
from contextvars import ContextVar
from ..ast import (
    METADATA_FIELDS, Abstract, Appendix, BlockQuote, Citation, CodeBlock, CodeInline, Document, Equation,
    Footnote, Heading, HorizontalRule, Image, Label, LineBreak, Link, ListBlock, ListItem, Node, Paragraph,
    Reference, Table, TableCell, Text, walk,
)
from ._common import (
    EMPHASIS_STYLES, caption_paragraphs, figure_image, latex_reference_macro, split_spaces, style_extent,
    table_grid, text_runs,
)

# A line break at the start or end of a paragraph is a LaTeX error ("There's no line here to end").
_EDGE_BREAKS = re.compile(r'^(?:\s*\\\\)+\s*|\s*(?:\\\\\s*)+$')
_COMMANDS = {'strikethrough': '\\sout', 'bold': '\\textbf', 'italic': '\\textit'}
_SCRIPTS = {'sup': '\\textsuperscript', 'sub': '\\textsubscript'}
_TASK_MARKS = {False: '[$\\square$]', True: '[$\\boxtimes$]'}
_COUNTERS = ('enumi', 'enumii', 'enumiii', 'enumiv')
# How many ordered lists enclose the one being rendered (each level has its own counter).
_ENUM_DEPTH: ContextVar[int] = ContextVar("latex_enum_depth", default=0)


def render_latex(doc: Document) -> str:
    """Renders an AST Document to a compiling LaTeX document.

    The preamble loads only the packages the document needs: ``graphicx``
    (images), ``hyperref`` (links), ``amsmath``/``amssymb`` (equations; the
    second also for task list boxes), ``natbib`` (``\\citet``/``\\citep``) and
    ``ulem`` (strikethrough). Document metadata becomes ``\\title``,
    ``\\author`` and ``\\date`` with ``\\maketitle``.
    """
    nodes = list(walk(doc))
    packages = ["\\usepackage[utf8]{inputenc}"]
    if any(isinstance(n, Image) for n in nodes):
        packages.append("\\usepackage{graphicx}")
    if any(isinstance(n, Link) for n in nodes):
        packages.append("\\usepackage{hyperref}")
    if any(isinstance(n, Equation) for n in nodes):
        packages.append("\\usepackage{amsmath}")
    if any(isinstance(n, Equation) or (isinstance(n, ListItem) and n.checked is not None) for n in nodes):
        packages.append("\\usepackage{amssymb}")
    if any(isinstance(n, Citation) and n.style in ("citet", "citep") for n in nodes):
        packages.append("\\usepackage{natbib}")
    if any(isinstance(n, Text) and n.strikethrough for n in nodes):
        # normalem keeps \emph as italics instead of underlining
        packages.append("\\usepackage[normalem]{ulem}")

    metadata = ""
    body = [r for r in (_render_node(child) for child in doc.children) if r]
    if any(getattr(doc, name) for name in METADATA_FIELDS):
        # All three are written: without \date, \maketitle prints today's date
        metadata = "".join(f"\\{name}{{{_EDGE_BREAKS.sub('', _inline(getattr(doc, name)).strip())}}}\n"
                           for name in METADATA_FIELDS)
        body.insert(0, "\\maketitle")

    preamble = ("\\documentclass{article}\n" + "".join(f"{p}\n" for p in packages) + metadata
                + "\\begin{document}\n\n")
    return preamble + '\n\n'.join(body) + "\n\n\\end{document}\n"


def _escape_latex(text: str) -> str:
    # Convert Unicode typographic quotes back to LaTeX notation
    text = text.replace('\u201c', '``').replace('\u201d', "''")   # " "  → `` ''
    text = text.replace('\u2018', '`').replace('\u2019', "'")    # ' '  → ` '
    # basic escapes
    chars = {
        '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_',
        '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}', '\\': r'\textbackslash{}',
        # Characters that the default font encoding prints as other glyphs
        '<': r'\textless{}', '>': r'\textgreater{}', '|': r'\textbar{}',
        ' ': '~',  # no-break space
    }
    return "".join(chars.get(c, c) for c in text)


def _escape_url(url: str) -> str:
    """Escape a URL for ``\\href``.

    ``~``, ``<``, ``>`` and ``|`` stay literal (hyperref reads them as is; a
    text command such as ``\\textasciitilde{}`` broke the link), characters
    that only have a text-mode command (backslash, braces, caret) are
    percent-encoded, and the rest is escaped as in text so the link also
    survives inside a table cell or a section title.
    """
    for char, code in (('\\', '%5C'), ('{', '%7B'), ('}', '%7D'), ('^', '%5E')):
        url = url.replace(char, code)
    literal = '~<>|'
    hidden = url.translate({ord(c): 0xE000 + i for i, c in enumerate(literal)})
    return _escape_latex(hidden).translate({0xE000 + i: c for i, c in enumerate(literal)})


def _render_node(node: Node) -> str:
    render = _RENDERERS.get(type(node))
    return render(node) if render else ""


def _inline(nodes: list[Node]) -> str:
    """Inline nodes as LaTeX, formatting commands opened and closed as formatting changes.

    Consecutive texts share their commands (``\\textit{a \\textbf{b} c}``),
    spaces stay outside them, any other node closes them, and the spaces
    before a line break are dropped (LaTeX ignores them).
    """
    out: list[str] = []
    stack: list[str] = []  # the open styles, outermost first
    spaces = ""  # trailing whitespace, written after the commands that close
    runs = text_runs(nodes)

    def close(keep: int, before_break: bool = False) -> None:
        nonlocal spaces
        out.append('}' * (len(stack) - keep))
        del stack[keep:]
        out.append('' if before_break else _spaces(spaces))
        spaces = ""

    for k, node in enumerate(runs):
        if not isinstance(node, Text):
            close(0, before_break=isinstance(node, LineBreak))
            out.append(_render_node(node))
            continue
        lead, core, trail = split_spaces(node.content)
        if not core:
            spaces += node.content
            continue
        styles = [s for s in EMPHASIS_STYLES if getattr(node, s)]
        keep = 0
        while keep < len(stack) and stack[keep] in styles:
            keep += 1
        close(keep)
        out.append(_spaces(lead))
        if next((p for p in reversed(out) if p), '').endswith('\\\\\n') and core[0] in '[*':
            out.append('{}')  # "\\[" would read the text as the break's optional argument
        for style in sorted((s for s in styles if s not in stack), key=lambda s: -style_extent(runs, k, s)):
            out.append(_COMMANDS[style] + '{')
            stack.append(style)
        out.append(_text(node, core))
        spaces = trail
    close(0)
    return ''.join(out)


def _spaces(text: str) -> str:
    """Whitespace between formatted runs; a ``\\n`` in it is a hard break."""
    return re.sub(r'[ \t]*\n[ \t]*', '\\\\\\\\\n', _escape_latex(text))


def _text(node: Text, core: str) -> str:
    """The escaped text of a run, without its formatting commands."""
    # A "\n" in a Text node is a hard break (the parsers turn soft ones into spaces)
    content = re.sub(r'[ \t]*\n', '\\\\\\\\\n', _escape_latex(core))
    if node.script:
        content = f"{_SCRIPTS[node.script]}{{{content}}}"
    return content


def _one_line(rendered: str) -> str:
    """Keep inline content on one line, for arguments that cannot hold a break (cells, titles)."""
    rendered = rendered.replace('\\\\', ' ').replace('\r', ' ').replace('\n', ' ')
    return re.sub(r'\s{2,}', ' ', rendered).strip()


def _heading(node: Heading) -> str:
    cmd = ["section", "subsection", "subsubsection", "paragraph", "subparagraph"][min(node.level-1, 4)]
    star = '' if node.numbered else '*'
    return f"\\{cmd}{star}{{{_one_line(_inline(node.children))}}}"


def _float_caption(target: Table | Image) -> list[str]:
    """The ``\\caption`` and ``\\label`` lines of a figure or table."""
    lines = [f"\\caption{{{_one_line(_inline(target.caption))}}}"] if target.caption else []
    return lines + ([f"\\label{{{target.label}}}"] if target.label else [])


def _figure(node: Node) -> str:
    """A captioned image (or a link holding one) as a ``figure`` float."""
    return '\n'.join(["\\begin{figure}[h]", "\\centering", _render_node(node),
                      *_float_caption(figure_image(node)), "\\end{figure}"])


def _paragraph(node: Paragraph) -> str:
    """A paragraph; a captioned image in it becomes a figure between the text before and after it."""
    out: list[str] = []
    run: list[Node] = []

    def flush() -> None:
        content = _EDGE_BREAKS.sub('', _inline(run).strip())
        if content:
            out.append(content)
        run.clear()

    for child in node.children:
        if figure_image(child):
            flush()
            out.append(_figure(child))
        else:
            run.append(child)
    flush()
    # Captions of images nested deeper (in a link with other content) as "Figure: ..." paragraphs
    rest = Paragraph(children=[c for c in node.children if not figure_image(c)])
    out.extend(_paragraph(p) for p in caption_paragraphs(rest))
    return '\n\n'.join(out)


def _code_block(node: CodeBlock) -> str:
    # verbatim needs no package
    return f"\\begin{{verbatim}}\n{node.code}\n\\end{{verbatim}}"


def _list(node: ListBlock) -> str:
    env = "enumerate" if node.ordered else "itemize"
    depth = _ENUM_DEPTH.get()
    lines = [f"\\begin{{{env}}}"]
    if node.ordered and node.start != 1:
        lines.append(f"    \\setcounter{{{_COUNTERS[min(depth, 3)]}}}{{{node.start - 1}}}")
    token = _ENUM_DEPTH.set(depth + 1) if node.ordered else None
    try:
        for item in node.items:
            content = ' \n    '.join(_render_node(c) for c in item.children).strip()
            lines.append(f"    \\item{_TASK_MARKS.get(item.checked, '')} {content}")
    finally:
        if token is not None:
            _ENUM_DEPTH.reset(token)
    lines.append(f"\\end{{{env}}}")
    return '\n'.join(lines)


def _table(node: Table) -> str:
    headers, rows, ncols = table_grid(node)
    if not ncols:
        return ""
    lines = [f"\\begin{{tabular}}{{|{'|'.join(['c'] * ncols)}|}}", "\\hline"]
    for row in ([headers] if headers else []) + rows:
        lines.append(" & ".join(_render_node(c) for c in row) + " \\\\")
        lines.append("\\hline")
    lines.append("\\end{tabular}")
    if node.caption or node.label:
        lines = ["\\begin{table}[h]", "\\centering", *_float_caption(node), *lines, "\\end{table}"]
    return '\n'.join(lines)


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
    Text: lambda node: _inline([node]),
    Link: _link,
    Image: lambda node: f"\\includegraphics{{{node.src}}}",
    CodeInline: lambda node: f"\\texttt{{{_escape_latex(node.code)}}}",
    LineBreak: lambda node: "\\\\\n",
    BlockQuote: _block_quote,
    HorizontalRule: lambda node: "\\noindent\\rule{\\textwidth}{0.4pt}",
    Equation: _equation,
    Abstract: _abstract,
    Appendix: lambda node: "\\appendix",
    **{cls: lambda node: latex_reference_macro(node, _inline) for cls in (Footnote, Citation, Reference, Label)},
}
