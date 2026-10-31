from __future__ import annotations
import re
from contextvars import ContextVar
from ..ast import (
    METADATA_FIELDS, Abstract, Appendix, Bibliography, BlockQuote, Citation, CodeBlock, CodeInline, Document, Equation,
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
# The sectioning commands by heading level.
_SECTIONS = ("part", "chapter", "section", "subsection", "subsubsection", "paragraph", "subparagraph")
_LEVELS: ContextVar[tuple[str, ...]] = ContextVar("latex_levels", default=_SECTIONS[2:])
# True while the document metadata is written: a note there is a \thanks.
_IN_METADATA: ContextVar[bool] = ContextVar("latex_in_metadata", default=False)
# The macros that need a package, by the package.
_NATBIB = frozenset({"citet", "citep", "citealt", "citealp", "citeauthor", "citeyear", "citeyearpar", "Citet", "Citep"})
_BIBLATEX = frozenset({"parencite", "Parencite", "autocite", "Autocite", "textcite", "Textcite", "footcite", "Cite",
                       "cites", "citetitle"})
_HYPERREF = frozenset({"autoref", "nameref", "hyperref"})
_CLEVEREF = frozenset({"cref", "Cref"})
_RESOURCE = "\\addbibresource"
_NESTED_ENV = re.compile(r'\\begin\{([^{}]*)\}(?:(?!\\begin\{).)*?\\end\{\1\}', re.DOTALL)


def render_latex(doc: Document) -> str:
    """Renders an AST Document to a compiling LaTeX document.

    The preamble loads only the packages the document needs: ``graphicx``
    (images), ``amsmath``/``amssymb`` (equations; the second also for task list
    boxes), ``natbib`` or ``biblatex`` (their citation macros), ``ulem``
    (strikethrough), ``varioref``, ``hyperref`` (links and its macros) and
    ``cleveref``. Document metadata becomes ``\\title``, ``\\author`` and
    ``\\date`` with ``\\maketitle``. The class is ``article``, or ``report`` for a
    document with ``\\chapter`` or ``\\part``.
    """
    root = _SECTIONS.index(doc.section_root) if doc.section_root in _SECTIONS else 2
    token = _LEVELS.set(_SECTIONS[root:])
    try:
        body = [r for r in (_render_node(child) for child in doc.children) if r]
        metadata = _metadata(doc)
    finally:
        _LEVELS.reset(token)
    if metadata:
        body.insert(0, "\\maketitle")
    preamble = (f"\\documentclass{{{'report' if doc.section_root else 'article'}}}\n"
                + "".join(f"{p}\n" for p in _packages(doc)) + metadata + "\\begin{document}\n\n")
    return preamble + '\n\n'.join(body) + "\n\n\\end{document}\n"


def _metadata(doc: Document) -> str:
    """The title block; all three are written, since without ``\\date`` ``\\maketitle`` prints today's date."""
    if not any(getattr(doc, name) for name in METADATA_FIELDS):
        return ""
    token = _IN_METADATA.set(True)
    try:
        return "".join(f"\\{name}{{{_EDGE_BREAKS.sub('', _inline(getattr(doc, name)).strip())}}}\n"
                       for name in METADATA_FIELDS)
    finally:
        _IN_METADATA.reset(token)


def _packages(doc: Document) -> list[str]:
    """The ``\\usepackage`` lines the document needs, ``hyperref`` and ``cleveref`` last as they require."""
    nodes = list(walk(doc))
    macros = {n.style.rstrip('*') for n in nodes if isinstance(n, (Citation, Reference))}
    commands = [c for n in nodes if isinstance(n, Bibliography) for c in n.commands]
    biblatex = macros & _BIBLATEX or any(c.startswith((_RESOURCE, "\\printbibliography")) for c in commands)
    packages = ["\\usepackage[utf8]{inputenc}"]
    if any(isinstance(n, Image) for n in nodes):
        packages.append("\\usepackage{graphicx}")
    if "eqref" in macros or any(isinstance(n, Equation) for n in nodes):
        packages.append("\\usepackage{amsmath}")
    if any(isinstance(n, Equation) or (isinstance(n, ListItem) and n.checked is not None) for n in nodes):
        packages.append("\\usepackage{amssymb}")
    if biblatex:
        packages.append("\\usepackage{biblatex}")
    elif macros & _NATBIB:
        packages.append("\\usepackage{natbib}")
    if any(isinstance(n, Text) and n.strikethrough for n in nodes):
        # normalem keeps \emph as italics instead of underlining
        packages.append("\\usepackage[normalem]{ulem}")
    if "vref" in macros:
        packages.append("\\usepackage{varioref}")
    if macros & _HYPERREF or any(isinstance(n, Link) for n in nodes):
        packages.append("\\usepackage{hyperref}")
    if macros & _CLEVEREF:
        packages.append("\\usepackage{cleveref}")
    # biblatex reads its data files in the preamble only
    return packages + [c for c in commands if c.startswith(_RESOURCE)]


def _escape_latex(text: str) -> str:
    # Double quotes go back to LaTeX notation; single ones stay: an apostrophe read as "'" would not come back
    text = text.replace('\u201c', '``').replace('\u201d', "''")
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


def _lines(nodes: list[Node]) -> list[list[Node]]:
    """Inline nodes split at their line breaks; a formula keeps its own."""
    lines: list[list[Node]] = [[]]
    for node in text_runs(nodes):
        if isinstance(node, LineBreak):
            lines.append([])
        elif isinstance(node, Text) and '\n' in node.content:
            first, *rest = node.content.split('\n')
            lines[-1].append(Text(first, node.bold, node.italic, node.strikethrough, node.script))
            lines.extend([Text(line, node.bold, node.italic, node.strikethrough, node.script)] for line in rest)
        else:
            lines[-1].append(node)
    return lines


def _flat(rendered: str) -> str:
    return re.sub(r'\s{2,}', ' ', rendered.replace('\r', ' ').replace('\n', ' ')).strip()


def _one_line(nodes: list[Node]) -> str:
    """Inline content on one line, for arguments that cannot hold a break (titles, captions)."""
    return _flat(' '.join(_inline(line) for line in _lines(nodes)))


def _table_cell(node: TableCell) -> str:
    """A cell; several lines take a nested tabular, which needs no package and keeps the table's rows."""
    lines = [_flat(_inline(line)) for line in _lines(node.children)]
    return lines[0] if len(lines) == 1 else f"\\begin{{tabular}}{{@{{}}c@{{}}}}{'\\\\'.join(lines)}\\end{{tabular}}"


def _heading(node: Heading) -> str:
    levels = _LEVELS.get()
    cmd = levels[min(node.level - 1, len(levels) - 1)]
    star = '' if node.numbered else '*'
    return f"\\{cmd}{star}{{{_one_line(node.children)}}}"


def _float_caption(target: Table | Image) -> list[str]:
    """The ``\\caption`` and ``\\label`` lines of a figure or table."""
    lines = [f"\\caption{{{_one_line(target.caption)}}}"] if target.caption else []
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
    # verbatim needs no package and, unlike listings, takes any character; the comment keeps the language
    language = f"% language: {node.language}\n" if node.language else ""
    return f"{language}\\begin{{verbatim}}\n{node.code}\n\\end{{verbatim}}"


def _list(node: ListBlock) -> str:
    env = "enumerate" if node.ordered else "itemize"
    depth = _ENUM_DEPTH.get()
    lines = [f"\\begin{{{env}}}"]
    if node.ordered and node.start != 1:
        lines.append(f"    \\setcounter{{{_COUNTERS[min(depth, 3)]}}}{{{node.start - 1}}}")
    token = _ENUM_DEPTH.set(depth + 1) if node.ordered else None
    try:
        for item in node.items:
            lines.append(f"    \\item{_TASK_MARKS.get(item.checked, '')} {_item_content(item)}")
    finally:
        if token is not None:
            _ENUM_DEPTH.reset(token)
    lines.append(f"\\end{{{env}}}")
    return '\n'.join(lines)


def _item_content(item: ListItem) -> str:
    """The blocks of a list item; a blank line keeps its paragraphs from merging."""
    out = ""
    for child in item.children:
        rendered = _render_node(child)
        if out:
            out += '\n\n    ' if isinstance(child, Paragraph) else ' \n    '
        out += rendered
    return out.strip()


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


def _blocks(children: list[Node]) -> str:
    """Block nodes in a row, a blank line between them: a line break alone would merge their paragraphs."""
    return '\n\n'.join(filter(None, (_render_node(c) for c in children)))


def _block_quote(node: BlockQuote) -> str:
    content = _blocks(node.children)
    if node.alert_type:
        return f"\\begin{{quote}}\n\\textbf{{{_escape_latex(node.alert_type)}}}\\\\\n{content}\n\\end{{quote}}"
    return f"\\begin{{quote}}\n{content}\n\\end{{quote}}"


def _equation(node: Equation) -> str:
    if node.inline:
        return f"${node.code}$"
    if node.env:
        return f"\\begin{{{node.env}}}\n{node.code}\n\\end{{{node.env}}}"
    body = f"\\begin{{aligned}}\n{node.code}\n\\end{{aligned}}" if _needs_alignment(node.code) else node.code
    # A label needs a number; any other plain display has none
    if '\\label' in node.code:
        return f"\\begin{{equation}}\n{body}\n\\end{{equation}}"
    return f"\\[\n{body}\n\\]"


def _needs_alignment(code: str) -> bool:
    """Alignment points or several lines outside any environment are only valid inside an alignment."""
    while True:
        outer = _NESTED_ENV.sub('', code)
        if outer == code:
            return bool(re.search(r'(?<!\\)&', outer)) or '\\\\' in outer
        code = outer


def _abstract(node: Abstract) -> str:
    return f"\\begin{{abstract}}\n{_blocks(node.children)}\n\\end{{abstract}}"


def _bibliography(node: Bibliography) -> str:
    lines = [c for c in node.commands if not c.startswith(_RESOURCE)]
    if node.entries:
        lines.append(f"\\begin{{thebibliography}}{{{node.widest}}}")
        for entry in node.entries:
            label = f"[{entry.label}]" if entry.label is not None else ""
            lines.append(f"\\bibitem{label}{{{entry.key}}} {_inline(entry.children)}".rstrip())
        lines.append("\\end{thebibliography}")
    return '\n'.join(lines)


def _footnote(node: Footnote) -> str:
    macro = latex_reference_macro(node, _inline)
    return macro.replace('\\footnote', '\\thanks', 1) if _IN_METADATA.get() else macro


_RENDERERS = {
    Heading: _heading,
    Paragraph: _paragraph,
    CodeBlock: _code_block,
    ListBlock: _list,
    Table: _table,
    TableCell: _table_cell,
    Text: lambda node: _inline([node]),
    Link: _link,
    Image: lambda node: f"\\includegraphics{{{node.src}}}",
    CodeInline: lambda node: f"\\texttt{{{_escape_latex(node.code)}}}",
    LineBreak: lambda node: " \\and " if node.author_separator else "\\\\\n",
    BlockQuote: _block_quote,
    HorizontalRule: lambda node: "\\noindent\\rule{\\textwidth}{0.4pt}",
    Equation: _equation,
    Abstract: _abstract,
    Appendix: lambda node: "\\appendix",
    Bibliography: _bibliography,
    Footnote: _footnote,
    **{cls: lambda node: latex_reference_macro(node, _inline) for cls in (Citation, Reference, Label)},
}
