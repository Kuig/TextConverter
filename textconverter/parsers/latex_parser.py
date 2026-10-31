from __future__ import annotations
import re
import unicodedata
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass

from ..ast import (
    METADATA_FIELDS, Abstract, Appendix, BibEntry, Bibliography, BlockQuote, CodeBlock, CodeInline, Document, Equation,
    Footnote, Heading, HorizontalRule, Image, InlineElement, Label, LineBreak, Link, ListBlock, ListItem, Node, Paragraph,
    Table, TableCell, TableRow, Text,
)
from ..logger import log_warning
from ._latex_macros import (
    BIBLIOGRAPHY_COMMAND, REFERENCE_MACROS, extract_macro_args, find_balanced_braces, parse_reference_macro,
)
from ._latex_source import URL_PERCENT, HiddenCode, prepare_source
from ._math import MATH_ENVS as _MATH_ENVS

# The sectioning commands, outermost first; the highest one in the document is level 1.
_SECTIONS = ('part', 'chapter', 'section', 'subsection', 'subsubsection', 'paragraph', 'subparagraph')
_SECTION_ROOT = re.compile(r'\\(part|chapter)\*?(?![a-zA-Z])')
_MAX_LEVEL = 6
# A section command, \appendix, a bibliography command, or the start of an environment.
_BLOCK_START = re.compile(rf'\\(?:(?P<sec>{"|".join(_SECTIONS)})(?![a-zA-Z])'
                          r'|(?P<appendix>appendix)(?![a-zA-Z])|begin\{(?P<env>[^}]+)\})'
                          rf'|(?P<bib>{BIBLIOGRAPHY_COMMAND.pattern})')
# Text the search for blocks must not look into: an escape, or a formula that is closed.
_MATH_SPAN = re.compile(r'\\[\\$]|\$\$.*?\$\$|\$(?:[^$\\\n]|\\.|\n(?![ \t]*\n))*?\$|\\\[.*?\\\]|\\\(.*?\\\)', re.DOTALL)
# An enumerate counter set before the first item: \setcounter{enumi}{2} starts the list at 3.
_SET_COUNTER = re.compile(r'\\setcounter\{enum(?:i|ii|iii|iv)\}\{\s*(-?\d+)\s*\}')
# The \item labels that mark a task list item, unchecked and checked.
_TASK_LABELS = {'$\\square$': False, '$\\Box$': False, '$\\boxtimes$': True, '$\\checkmark$': True}
_ITEM = re.compile(r'\\item(?![a-zA-Z])')
# A paragraph that is only a full-width rule (as the renderer writes a HorizontalRule).
_RULE = re.compile(r'^(?:\\rule\{\\(?:text|line)width\}\{[^}]*\}|\\hrule|\\hrulefill)$')
_ENV_BOUNDARY = re.compile(r'\\(begin|end)\{[^}]*\}')
# The environments that hold a table's rows, and the floats that wrap them.
_TABLE_ENVS = ('tabular', 'tabular*', 'tabularx', 'tabulary', 'longtable', 'longtable*', 'xltabular')
_TABLE_FLOATS = ('table', 'table*', 'sidewaystable', 'sidewaystable*', 'wraptable')
_TABLE_START = re.compile(r'\\begin\{(' + '|'.join(re.escape(env) for env in _TABLE_ENVS) + r')\}')
# Table commands that draw and hold no data: the optional arguments each one takes, right
# after its name (any further away they are the text of the next cell), and how many {...}.
_BRACKET = r'(?:\[[^\]]*\])?'
_TABLE_LAYOUT = {
    'hline': ('', 0), 'morecmidrules': ('', 0), 'toprule': (_BRACKET, 0), 'midrule': (_BRACKET, 0),
    'bottomrule': (_BRACKET, 0), 'addlinespace': (_BRACKET, 0), 'cline': ('', 1), 'hhline': ('', 1),
    'cmidrule': (_BRACKET + r'(?:\([^)]*\))?', 1), 'rowcolor': (_BRACKET, 1), 'cellcolor': (_BRACKET, 1),
    'specialrule': ('', 3),
}
_TABLE_LAYOUT_COMMAND = re.compile('|'.join(
    rf'\\{name}(?![a-zA-Z]){options}' + r'\s*\{[^{}]*\}' * arguments
    for name, (options, arguments) in _TABLE_LAYOUT.items()
))
# A cell of several lines, as the LaTeX renderer writes it.
_CELL_LINES = re.compile(r'\\begin\{tabular\}\{@\{\}c@\{\}\}(.*)\\end\{tabular\}', re.DOTALL)
_TABLE_ROW_END = re.compile(r'\\\\\*?(?:\[[^\]]*\])?|\\tabularnewline(?![a-zA-Z])')
# What stands before the text of a \multirow: the optional and the required arguments.
_MULTIROW = re.compile(r'\\multirow(?:\[[^\]]*\])?\s*\{[^{}]*\}(?:\[[^\]]*\])?\s*\{[^{}]*\}(?:\[[^\]]*\])?\s*')
# The end of a longtable's first head, repeated head and feet; the last two parts are not body.
_LONGTABLE_PART = re.compile(r'\\(endfirsthead|endhead|endfoot|endlastfoot)(?![a-zA-Z])')
_BIB_ITEM = re.compile(r'\\bibitem(?:\[([^\]]*)\])?\s*\{([^{}]*)\}')
_ALERTS = ('NOTE', 'TIP', 'IMPORTANT', 'WARNING', 'CAUTION')
_THEOREM_ENVS = ('theorem', 'lemma', 'proposition', 'corollary', 'definition', 'remark', 'example', 'proof',
                 'claim', 'conjecture')

# Accent commands followed by one letter, as combining marks.
_ACCENTS = {
    "'": '\u0301', '`': '\u0300', '^': '\u0302', '"': '\u0308', '~': '\u0303', '=': '\u0304',
    '.': '\u0307', 'u': '\u0306', 'v': '\u030C', 'H': '\u030B', 'c': '\u0327', 'k': '\u0328',
    'r': '\u030A', 'd': '\u0323', 'b': '\u0331',
}
# Argument-less macros that stand for a character or a word.
_SYMBOLS = {
    'ss': 'ß', 'o': 'ø', 'O': 'Ø', 'ae': 'æ', 'AE': 'Æ', 'oe': 'œ', 'OE': 'Œ', 'aa': 'å', 'AA': 'Å',
    'l': 'ł', 'L': 'Ł', 'i': 'ı', 'j': 'ȷ', 'ldots': '…', 'dots': '…', 'textendash': '–',
    'textemdash': '—', 'S': '§', 'P': '¶', 'copyright': '©', 'pounds': '£', 'euro': '€',
    'textasciitilde': '~', 'textasciicircum': '^', 'textbackslash': '\\',
    'textless': '<', 'textgreater': '>', 'textbar': '|', 'textcopyright': '©',
    'TeX': 'TeX', 'LaTeX': 'LaTeX', 'LaTeXe': 'LaTeX2ε', 'quad': '\u2003', 'qquad': '\u2003\u2003',
}
# Font declarations: the formatting they switch on or off for the rest of their group.
_DECLARATIONS = {
    **dict.fromkeys(('bfseries', 'bf'), {'is_bold': True}),
    **dict.fromkeys(('itshape', 'it', 'slshape', 'sl', 'em'), {'is_italic': True}),
    'mdseries': {'is_bold': False}, 'upshape': {'is_italic': False},
    'normalfont': {'is_bold': False, 'is_italic': False},
}
# Control symbols: "\," and the like, as the space they make.
_CONTROL_SPACES = {',': '\u2009', ';': ' ', ':': ' ', ' ': ' ', '!': '', '@': '', '/': '', '-': ''}
# Font declarations that make a group code.
_CODE_GROUP = re.compile(r'\s*\\(?:tt|ttfamily)(?![a-zA-Z])\s*')
# Commands whose text is one argument: its index; those before it are settings.
_CONTENT_ARGUMENT = {'textcolor': 1, 'colorbox': 1, 'fcolorbox': 2, 'foreignlanguage': 1, 'parbox': 1, 'raisebox': 1,
                     'resizebox': 2, 'scalebox': 1, 'rotatebox': 1}
# Commands with no text of their own.
_LAYOUT_COMMANDS = frozenset({
    'color', 'pagecolor', 'setlength', 'addtolength', 'setcounter', 'addtocounter', 'stepcounter', 'refstepcounter',
    'newlength', 'newcounter', 'pagestyle', 'pagenumbering', 'linespread', 'setstretch', 'enlargethispage',
    'fontfamily', 'fontseries', 'fontshape', 'rule', 'newtheorem', 'theoremstyle', 'lstset', 'graphicspath',
    'captionsetup', 'hypersetup', 'usetikzlibrary', 'geometry', 'definecolor', 'usepackage', 'documentclass',
})
# Commands that only style their argument: known, so not worth a warning.
_STYLE_COMMANDS = frozenset({
    'textsc', 'textrm', 'textsf', 'textup', 'textmd', 'textnormal', 'underline', 'uline', 'dotuline', 'mbox', 'hbox',
    'fbox', 'makebox', 'framebox', 'text', 'ensuremath', 'nolinkurl', 'si', 'num', 'tiny', 'small', 'large', 'Large',
    'huge', 'Huge', 'normalsize', 'footnotesize', 'scriptsize', 'mathbf', 'mathit', 'mathrm', 'makecell', 'caption',
    'centerline', 'subcaption', 'SI',
})
# The names of the unknown macros met while parsing one document.
_UNKNOWN: ContextVar[set[str] | None] = ContextVar("latex_unknown_macros", default=None)
_ESCAPED_CHARS = ('%', '&', '$', '_', '#', '{', '}')


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


def _plain_text(text: str) -> str:
    """Plain LaTeX source text as the text it typesets.

    Source line breaks and indentation are spaces (a ``\\n`` in a Text node is
    a hard break, which LaTeX writes ``\\\\``), ``~`` is a no-break space,
    ``---``/``--`` are dashes, and ``\u0060\u0060...''`` are curly quotes.
    """
    text = _normalize_latex_quotes(text)
    text = text.replace('---', '\u2014').replace('--', '\u2013').replace('~', '\u00a0')
    # Source whitespace only: no-break and thin spaces stay
    return re.sub(r'[ \t\r\n\f]+', ' ', text)


def _strip_macro(text: str, macro_name: str) -> str:
    """Remove every occurrence of a macro along with its arguments."""
    pos = 0
    while True:
        _, start, end = extract_macro_args(text, macro_name, pos)
        if start == -1:
            break
        text = text[:start] + text[end:]
        pos = start
    return text


def _extract_environment(text: str, env_name: str, start_pos: int = 0) -> tuple[str, int, int]:
    """Find the first ``\\begin{env_name}`` at or after ``start_pos`` and its matching ``\\end``.

    Nested environments of the same name are balanced, so an inner list does
    not end the outer one. Leading ``[...]`` and ``{...}`` arguments of the
    environment (``{p{4cm} p{4cm}}``, ``[t]``) are dropped from the content.

    Returns:
        ``(content, begin_index, end_index)``, or ``("", -1, -1)`` when the
        environment is missing or unclosed.
    """
    begin_str = f"\\begin{{{env_name}}}"
    end_str = f"\\end{{{env_name}}}"
    start_idx = text.find(begin_str, start_pos)
    if start_idx == -1:
        return "", -1, -1

    depth = 1
    pos = start_idx + len(begin_str)
    while depth:
        next_begin = text.find(begin_str, pos)
        end_idx = text.find(end_str, pos)
        if end_idx == -1:
            return "", -1, -1
        if next_begin != -1 and next_begin < end_idx:
            depth += 1
            pos = next_begin + len(begin_str)
        else:
            depth -= 1
            pos = end_idx + len(end_str)
    content = text[start_idx + len(begin_str):end_idx]

    idx = 0
    while True:
        while idx < len(content) and content[idx] in ' \t':
            idx += 1
        if idx < len(content) and content[idx] == '{':
            idx = find_balanced_braces(content, idx)[1]
        elif idx < len(content) and content[idx] == '[' and env_name not in ('lstlisting',):
            close = content.find(']', idx)
            if close == -1:
                break
            idx = close + 1
        else:
            break
    return content[idx:], start_idx, end_idx + len(end_str)


@dataclass
class _Context:
    """What the block parser needs from the whole document."""
    code: list[HiddenCode]
    first_section: int = _SECTIONS.index('section')  # the command that is level 1


def parse_latex(text: str, source: str | None = None) -> Document:
    """Parses a basic subset of LaTeX into an AST Document.

    Recognized: sectioning, title/author/date, abstract, lists (nested),
    code (verbatim, lstlisting, minted, Verbatim and the inline macros), tables
    (the tabular family and longtable, inside a float or alone), figures, display
    math environments, keywords, quotes and the bibliography; any other
    environment contributes its content. Inline: emphasis, links, code, math,
    footnotes, citations, cross-references, accents and the common symbols.
    The author's macros are expanded and hidden text is dropped (see
    ``_latex_source``). Commands it does not know keep their arguments as text
    and are reported in one warning.

    Args:
        text: The LaTeX source.
        source: Its path, the folder ``\\input`` reads from; None reads no file.
    """
    unknown: set[str] = set()
    token = _UNKNOWN.set(unknown)
    try:
        doc = _parse_source(text, source)
    finally:
        _UNKNOWN.reset(token)
    if unknown:
        names = ', '.join(sorted(f'\\{name}' for name in unknown))
        log_warning(f"LaTeX macros read as plain text: {names}.")
    return doc


def _parse_source(text: str, source: str | None) -> Document:
    text, code = prepare_source(text, source)

    # Strip custom two-column layouts and wrappers
    text = re.sub(r'\\twocolumn\s*\[', '', text)
    text = text.replace('\\begin{@twocolumnfalse}', '')
    text = re.sub(r'\\end\{@twocolumnfalse\}\s*\]', '', text)
    text = text.replace('\\end{@twocolumnfalse}', '')

    # Strip layout and styling commands first so they are cleaned from metadata too
    for cmd in ["\\fontsize", "\\thispagestyle", "\\pubyear", "\\pagerange", "\\vspace", "\\hspace",
                "\\sectionmark", "\\markboth", "\\markright"]:
        text = _strip_macro(text, cmd)
    for cmd in ["\\selectfont", "\\balance", "\\noindent", "\\raggedright", "\\justifying", "\\centering",
                "\\hfill", "\\maketitle"]:
        text = re.sub(re.escape(cmd) + r'(?![a-zA-Z])', '', text)

    doc = Document()
    for name in METADATA_FIELDS:
        args, start, end = extract_macro_args(text, f"\\{name}")
        # \title, not \titleformat
        while start != -1 and text[start + len(name) + 1:start + len(name) + 2].isalpha():
            args, start, end = extract_macro_args(text, f"\\{name}", start + 1)
        if args:
            setattr(doc, name, _clean_breaks(parse_inline_latex(args[0].strip())))
            text = text[:start] + text[end:]  # also when it stands in the body

    # Strip out preamble if document environment exists
    m_doc = re.search(r'\\begin\{document\}(.*?)\\end\{document\}', text, re.DOTALL)
    preamble = text[:m_doc.start()] if m_doc else ""
    if m_doc:
        text = m_doc.group(1)
    ctx = _Context(code)
    root = {m.group(1) for m in _SECTION_ROOT.finditer(text)}
    if root:
        doc.section_root = 'part' if 'part' in root else 'chapter'
        ctx.first_section = _SECTIONS.index(doc.section_root)
    doc.children.extend(_parse_blocks(text, ctx))
    _add_preamble_commands(doc, [m.group(0) for m in BIBLIOGRAPHY_COMMAND.finditer(preamble)])
    return doc


def _add_preamble_commands(doc: Document, commands: list[str]) -> None:
    """Give the bibliography the commands that stand in the preamble (``\\addbibresource``, a style)."""
    if not commands:
        return
    existing = next((n for n in doc.children if isinstance(n, Bibliography)), None)
    if existing is None:
        doc.children.append(Bibliography(commands=commands))
    else:
        existing.commands[:0] = commands


def _one_line(nodes: list[InlineElement]) -> list[InlineElement]:
    """A heading's content: line breaks become spaces."""
    return [Text(content=' ') if isinstance(n, LineBreak) else n for n in nodes]


def _is_blank(node: Node) -> bool:
    return isinstance(node, LineBreak) or (isinstance(node, Text) and not node.content.strip())


def _clean_breaks(children: list[InlineElement]) -> list[InlineElement]:
    """Drop line breaks at the paragraph's edges and collapse runs of them into one."""
    out: list[InlineElement] = []
    for child in children:
        if isinstance(child, LineBreak):
            last = next((n for n in reversed(out) if not _is_blank(n) or isinstance(n, LineBreak)), None)
            if last is None or isinstance(last, LineBreak):
                continue  # nothing on the line before it
        out.append(child)
    while out and _is_blank(out[-1]):
        out.pop()
    while out and _is_blank(out[0]):
        out.pop(0)
    return out


def _paragraphs(chunk: str) -> list[Node]:
    """The paragraphs of a run of text between blocks (split on blank lines)."""
    nodes: list[Node] = []
    for p_text in re.split(r'\n\s*\n', chunk.strip()):
        if _RULE.match(p_text.strip()):
            nodes.append(HorizontalRule())
            continue
        # A display formula ($$...$$, \[...\]) inside the text splits its paragraph
        run: list[InlineElement] = []
        for child in [*parse_inline_latex(p_text.strip()), None]:
            if child is None or (isinstance(child, Equation) and not child.inline):
                if _clean_breaks(run):
                    nodes.append(Paragraph(children=_clean_breaks(run)))
                if child is not None:
                    nodes.append(child)
                run = []
            else:
                run.append(child)
    return nodes


def _next_block(text: str, pos: int) -> re.Match | None:
    """The next block start at or after ``pos`` that is not inside a formula."""
    while (block := _BLOCK_START.search(text, pos)) is not None:
        for span in _MATH_SPAN.finditer(text, pos):
            if span.start() >= block.start():
                return block
            if span.end() > block.start():
                pos = span.end()
                break
        else:
            return block
    return None


def _parse_blocks(text: str, ctx: _Context) -> list[Node]:
    """Parse LaTeX body text into block nodes."""
    nodes: list[Node] = []
    pos = 0
    while True:
        m = _next_block(text, pos)
        if m is None:
            nodes.extend(_paragraphs(text[pos:]))
            return nodes
        nodes.extend(_paragraphs(text[pos:m.start()]))

        if m.group('appendix'):
            nodes.append(Appendix())
            pos = m.end()
            continue

        if m.group('bib'):
            if nodes and isinstance(nodes[-1], Bibliography):
                nodes[-1].commands.append(m.group('bib'))
            else:
                nodes.append(Bibliography(commands=[m.group('bib')]))
            pos = m.end()
            continue

        if m.group('sec'):
            starred = text.startswith('*', m.end())
            args, start, end = extract_macro_args(text, m.group(0) + ('*' if starred else ''), m.start())
            if start == m.start() and args:
                level = _SECTIONS.index(m.group('sec')) - ctx.first_section + 1
                nodes.append(Heading(level=min(level, _MAX_LEVEL), numbered=not starred,
                                     children=_one_line(parse_inline_latex(args[0]))))
                pos = end
            else:
                pos = m.end()
            continue

        env = m.group('env')
        content, start, end = _extract_environment(text, env, m.start())
        if start == -1:
            pos = m.end()  # unclosed: skip the \begin and read on
            continue
        if env == 'thebibliography':
            nodes.extend(_bibliography(text[m.end():end], content, nodes))
        elif env in _THEOREM_ENVS:
            title = re.match(r'\s*\[([^\]]*)\]', text[m.end():end])
            nodes.extend(_parse_blocks(f"\\textbf{{{title.group(1)}}} {content}" if title else content, ctx))
        else:
            nodes.extend(_environment(env, content, ctx))
        pos = end


def _bibliography(head: str, content: str, nodes: list[Node]) -> list[Node]:
    """A ``thebibliography``: added to the commands just before it, if any, else a node of its own."""
    previous = nodes[-1] if nodes and isinstance(nodes[-1], Bibliography) else None
    bib = previous or Bibliography()
    widest = re.match(r'\s*\{([^{}]*)\}', head)
    if widest:
        bib.widest = widest.group(1)
    items = list(_BIB_ITEM.finditer(content))
    for item, following in zip(items, [*items[1:], None]):
        body = content[item.end():following.start() if following else len(content)]
        bib.entries.append(BibEntry(key=item.group(2).strip(), label=item.group(1),
                                    children=_clean_breaks(parse_inline_latex(body.strip()))))
    return [] if previous else [bib]


def _code_environment(content: str, ctx: _Context) -> list[Node]:
    """A code environment; a listing's caption is a paragraph before it, as tables and figures have."""
    m = re.search(r'\x00(\d+)\x00', content)
    hidden = ctx.code[int(m.group(1))] if m else HiddenCode(code=content.strip('\n').rstrip())
    block = CodeBlock(code=hidden.code, language=hidden.language)
    if hidden.caption:
        return [Paragraph(children=parse_inline_latex(f"Listing: {hidden.caption.strip()}")), block]
    return [block]


def _images(content: str) -> list[Image]:
    """The images of a float's content."""
    images = []
    pos = 0
    while True:
        args, start, pos = extract_macro_args(content, "\\includegraphics", pos)
        if start == -1:
            return images
        if args:
            images.append(Image(src=args[0].strip(), alt="image"))


def _figure(content: str) -> list[Node]:
    """A figure float. The AST has no subfigures: each one's image keeps its own caption, the main caption follows."""
    images: list[Image] = []
    rest = content
    while True:
        body, start, end = _extract_environment(rest, 'subfigure')
        if start == -1:
            break
        found = _images(body)
        if found:
            _float_caption(body, found[0])
        images.extend(found)
        rest = rest[:start] + rest[end:]
    if images:
        label_args, _, _ = extract_macro_args(_strip_macro(rest, "\\caption"), "\\label")
        caption = _caption_paragraph(rest, "Figure")
        if caption and label_args:
            caption[0].children.extend([Text(content=" "), Label(name=label_args[0].strip())])
        return [Paragraph(children=images), *caption]
    images = _images(content)
    if not images:
        return _caption_paragraph(content, "Figure")
    _float_caption(content, images[0])
    return [Paragraph(children=images)]


def _quote(content: str, ctx: _Context) -> BlockQuote:
    """A quote; a first line that is only an alert's name in bold, as the renderer writes it, is that alert."""
    blocks = _parse_blocks(content, ctx)
    first = blocks[0].children if blocks and isinstance(blocks[0], Paragraph) else []
    if (len(first) > 1 and isinstance(first[0], Text) and first[0].bold and first[0].content in _ALERTS
            and isinstance(first[1], LineBreak)):
        alert = first[0].content
        del first[:2]
        return BlockQuote(children=blocks if first else blocks[1:], alert_type=alert)
    return BlockQuote(children=blocks)


def _environment(env: str, content: str, ctx: _Context) -> list[Node]:
    """The block nodes for one environment."""
    if env in _MATH_ENVS:
        return [Equation(code=content.strip(), inline=False, env=env)]
    if env == 'verbatim':
        return _code_environment(content, ctx)
    if env in ('itemize', 'enumerate', 'description'):
        return [_list(env, content, ctx)]
    if env in _TABLE_ENVS:
        return [_parse_latex_table(content.strip())]
    if env in ('figure', 'figure*'):
        return _figure(content)
    if env in _TABLE_FLOATS:
        tables = _float_tables(content)
        if not tables:
            return _caption_paragraph(content, "Table")
        _float_caption(content, tables[0])
        return tables
    if env == 'abstract':
        return [Abstract(children=_parse_blocks(content, ctx))]
    if env == 'keywords':
        return [Paragraph(children=[Text(content="Keywords: ", bold=True)] + parse_inline_latex(content.strip()))]
    if env in ('quote', 'quotation'):
        return [_quote(content, ctx)]
    # Layout environments (center, minipage, ...): their content
    return _parse_blocks(content, ctx)


def _float_tables(content: str) -> list[Table]:
    """Every table in a float's content, also inside subtables or a ``\\resizebox``."""
    tables = []
    pos = 0
    while (start := _TABLE_START.search(content, pos)) is not None:
        body, begin, end = _extract_environment(content, start.group(1), start.start())
        if begin == -1:  # unclosed: skip the \begin and read on
            pos = start.end()
            continue
        tables.append(_parse_latex_table(body.strip()))
        pos = end
    return tables


def _float_caption(content: str, target: Table | Image) -> None:
    """Give a figure's image or a table the float's ``\\caption`` and ``\\label`` (also one inside the caption)."""
    cap_args, _, _ = extract_macro_args(content, "\\caption")
    caption = parse_inline_latex(cap_args[0].strip()) if cap_args else []
    labels = [n.name for n in caption if isinstance(n, Label)]
    target.caption = _clean_breaks([n for n in caption if not isinstance(n, Label)])
    label_args, _, _ = extract_macro_args(_strip_macro(content, "\\caption"), "\\label")
    target.label = label_args[0].strip() if label_args else (labels[-1] if labels else None)


def _caption_paragraph(content: str, kind: str) -> list[Node]:
    """A float's caption as a ``Figure: ...`` / ``Table: ...`` paragraph, when it has nothing to attach to."""
    cap_args, _, _ = extract_macro_args(content, "\\caption")
    if not cap_args or not cap_args[0].strip():
        return []
    return [Paragraph(children=parse_inline_latex(f"{kind}: {cap_args[0].strip()}"))]


def _list(env: str, content: str, ctx: _Context) -> ListBlock:
    """An itemize, enumerate or description list; ``\\setcounter`` sets the start, box labels mark tasks."""
    first_item = _ITEM.search(content)
    counter = _SET_COUNTER.search(content, 0, first_item.start() if first_item else len(content))
    lst = ListBlock(ordered=env == 'enumerate', start=int(counter.group(1)) + 1 if counter else 1)
    for label, body in _items(content):
        checked = _TASK_LABELS.get(label.strip()) if label is not None and env != 'description' else None
        if label is not None and checked is None:  # \item[label]: the label leads the item, in bold
            body = f"\\textbf{{{label}}} {body}"
        lst.items.append(ListItem(children=_parse_blocks(body, ctx), checked=checked))
    return lst


def _items(content: str) -> list[tuple[str | None, str]]:
    """The ``[label]`` (or None) and text of each top-level ``\\item`` (nested lists stay inside it)."""
    starts: list[int] = []
    depth = 0
    pos = 0
    while True:
        item = _ITEM.search(content, pos)
        if item is None:
            break
        for boundary in _ENV_BOUNDARY.finditer(content, pos, item.start()):
            depth += 1 if boundary.group(1) == 'begin' else -1
        if depth == 0:
            starts.append(item.start())
        pos = item.end()
    items = []
    for i, start in enumerate(starts):
        body = content[start + len('\\item'):starts[i + 1] if i + 1 < len(starts) else len(content)]
        label = re.match(r'\s*\[([^\]]*)\]', body)
        items.append((label.group(1), body[label.end():].strip()) if label else (None, body.strip()))
    return items


def _longtable_rows(content: str) -> str:
    """The first head and the body of a longtable, without the repeated head and the feet."""
    parts = _LONGTABLE_PART.split(content)
    heads = dict(zip(parts[1::2], parts[0::2]))
    return heads.get('endfirsthead', heads.get('endhead', '')) + parts[-1]


def _table_cells(content: str, groups: bool = True) -> list[list[str]]:
    """The source of each cell, row by row.

    Rows and cells only end outside groups and nested environments, so
    ``\\multicolumn{2}{c}{a\\\\b}`` is one cell. ``\\&`` is a literal ampersand.
    With braces that do not balance the rows would run together, so they are
    read again with ``groups`` False, which ignores them.
    """
    rows: list[list[str]] = [[]]
    start = pos = depth = 0
    while pos < len(content):
        char = content[pos]
        if char == '\\':
            row_end = _TABLE_ROW_END.match(content, pos) if depth == 0 else None
            boundary = _ENV_BOUNDARY.match(content, pos)
            if row_end:
                rows[-1].append(content[start:pos])
                rows.append([])
                start = pos = row_end.end()
            elif boundary:
                depth += 1 if boundary.group(1) == 'begin' else -1
                pos = boundary.end()
            else:
                pos += 2
            continue
        if char == '{' and groups:
            depth += 1
        elif char == '}' and groups:
            depth -= 1
        elif char == '&' and depth == 0:
            rows[-1].append(content[start:pos])
            start = pos + 1
        pos += 1
    if groups and depth:
        return _table_cells(content, groups=False)
    rows[-1].append(content[start:])
    return rows


def _spanned_cell(source: str) -> tuple[str, int]:
    """A cell's source without ``\\multicolumn`` and ``\\multirow``, and the columns it spans."""
    source = source.strip()
    if source.startswith('\\multicolumn'):
        args, _, end = extract_macro_args(source, '\\multicolumn')
        if len(args) >= 3:
            text, _ = _spanned_cell(args[2])
            return text + source[end:], int(args[0]) if args[0].strip().isdigit() else 1
    multirow = _MULTIROW.match(source)
    if multirow and source.startswith('{', multirow.end()):
        text, end = find_balanced_braces(source, multirow.end())
        return _spanned_cell(text)[0] + source[end:], 1
    return source, 1


def _parse_latex_table(content: str) -> Table:
    """A table from the content of its environment.

    The first row is the header. As for HTML ``colspan``, the AST has no spans:
    a ``\\multicolumn`` is its text and blank cells, a ``\\multirow`` its text.
    """
    table = Table()
    content = _longtable_rows(content)
    if '\\caption' in content:  # a longtable holds its own caption
        _float_caption(content, table)
        content = _strip_macro(_strip_macro(content, '\\caption'), '\\label')

    for row in _table_cells(_TABLE_LAYOUT_COMMAND.sub('', content)):
        if len(row) == 1 and not row[0].strip():
            continue
        cells: list[TableCell] = []
        for source in row:
            text, span = _spanned_cell(source)
            lines = _CELL_LINES.fullmatch(text.strip())
            cells.append(TableCell(children=parse_inline_latex((lines.group(1) if lines else text).strip())))
            cells.extend(TableCell() for _ in range(span - 1))
        if table.headers or table.rows:
            table.rows.append(TableRow(cells=cells))
        else:
            table.headers = cells
    return table


def _accented(letter: str, accent: str) -> str:
    return unicodedata.normalize('NFC', letter + _ACCENTS[accent]) if letter else ''


def parse_inline_latex(
    text: str, is_bold: bool = False, is_italic: bool = False, is_strike: bool = False, script: str | None = None
) -> list[InlineElement]:
    """Parse inline LaTeX into inline AST nodes, with the given formatting in force.

    A ``{...}`` group is parsed with the same formatting, and a font
    declaration (``\\bfseries``, ``\\em``, ...) changes it up to the end of the
    group it stands in.
    """
    elements: list[InlineElement] = []

    def add_text(content: str) -> None:
        if elements and isinstance(elements[-1], LineBreak):
            content = content.lstrip()
        if content:
            elements.append(Text(content=content, bold=is_bold, italic=is_italic, strikethrough=is_strike,
                                 script=script))

    def inline(arg: str, **fmt) -> list[InlineElement]:
        return parse_inline_latex(arg, **{'is_bold': is_bold, 'is_italic': is_italic, 'is_strike': is_strike,
                                          'script': script, **fmt})

    pos = 0
    while pos < len(text):
        m = re.search(r'[\\${}]', text[pos:])
        idx = len(text) if m is None else pos + m.start()
        if idx > pos:
            add_text(_plain_text(text[pos:idx]))
            pos = idx
        if pos >= len(text):
            break

        if text[pos] == '$':
            pos = _math(text, pos, elements, add_text)
            continue
        if text[pos] == '{':
            group, pos = find_balanced_braces(text, pos)
            code = _CODE_GROUP.match(group)
            if code:
                elements.append(CodeInline(code=_unescape_latex(group[code.end():].strip())))
            else:
                elements.extend(inline(group))
            continue
        if text[pos] == '}':  # unbalanced: dropped, as the group it closes is already open
            pos += 1
            continue

        # text[pos] is a backslash
        if pos + 1 >= len(text):
            add_text('\\')
            break
        next_char = text[pos + 1]

        if next_char in '([':
            close = '\\)' if next_char == '(' else '\\]'
            end_idx = text.find(close, pos + 2)
            if end_idx != -1:
                elements.append(Equation(code=text[pos + 2:end_idx].strip(), inline=next_char == '('))
                pos = end_idx + 2
            else:
                add_text('\\' + next_char)
                pos += 2
            continue

        if next_char == '\\':  # Line break: \\ or \\[1ex]
            elements.append(LineBreak())
            pos += 2
            opt = re.match(r'\[[^\]]*\]', text[pos:])
            if opt:
                pos += opt.end()
            continue

        if next_char in _ESCAPED_CHARS:
            add_text(next_char)
            pos += 2
            continue

        if next_char in _CONTROL_SPACES:
            add_text(_CONTROL_SPACES[next_char])
            pos += 2
            continue

        if next_char in _ACCENTS and not next_char.isalpha():  # \'e, \'{e}, \"o, ...
            pos = _accent(text, pos + 2, next_char, add_text)
            continue

        m = re.match(r'\\([a-zA-Z]+)\*?', text[pos:])
        if not m:
            add_text('\\')
            pos += 1
            continue
        cmd_name, cmd_base = m.group(0), m.group(1)

        if cmd_base in _ACCENTS:  # \c{c}, \v{s}, \u{a}, ...
            pos = _accent(text, pos + len(cmd_name), cmd_base, add_text)
            continue
        if cmd_base in _SYMBOLS:
            add_text(_SYMBOLS[cmd_base])
            pos = _skip_spaces(text, pos + len(cmd_name))
            continue
        if cmd_base == 'and':  # between two authors
            if elements and isinstance(elements[-1], Text):
                elements[-1].content = elements[-1].content.rstrip()
                if not elements[-1].content:
                    elements.pop()
            elements.append(LineBreak(author_separator=True))
            pos = _skip_spaces(text, pos + len(cmd_name))
            continue
        if cmd_base in _DECLARATIONS:
            fmt = _DECLARATIONS[cmd_base]
            is_bold = fmt.get('is_bold', is_bold)
            is_italic = fmt.get('is_italic', is_italic)
            pos = _skip_spaces(text, pos + len(cmd_name))
            continue

        # Footnotes, citations and cross-references stay AST nodes
        if cmd_base in REFERENCE_MACROS:
            node, pos = parse_reference_macro(text, pos, cmd_name, lambda arg: inline(arg))
            if node is None:
                add_text(cmd_name)
            else:
                elements.append(node)
            continue

        args, start, end = extract_macro_args(text, cmd_name, pos)
        if start != pos or not args:
            pos = _skip_spaces(text, pos + len(cmd_name))  # argument-less command: dropped
            continue
        pos = end
        handler = _INLINE_COMMANDS.get(cmd_base)
        if handler is not None:
            elements.extend(handler(args, inline, is_bold, is_italic, is_strike))
            # Keep \texttt{...} apart from a word glued to it
            if cmd_base == 'texttt' and end < len(text) and text[end].isalnum():
                add_text(' ')
        elif cmd_base in _CONTENT_ARGUMENT:
            elements.extend(inline(args[min(_CONTENT_ARGUMENT[cmd_base], len(args) - 1)]))
        elif cmd_base not in _LAYOUT_COMMANDS:
            elements.extend(_all_arguments(cmd_base, args, inline))

    return _collapse_spaces(elements)


def _all_arguments(name: str, args: list[str], inline: Callable[[str], list[InlineElement]]) -> list[InlineElement]:
    """Any other command: the content of its arguments, in order, so that none is lost."""
    unknown = _UNKNOWN.get()
    if unknown is not None and name not in _STYLE_COMMANDS:
        unknown.add(name)
    out: list[InlineElement] = []
    for i, arg in enumerate(args):
        out.extend([*([Text(content=' ')] if i else []), *inline(arg)])
    return out


def _collapse_spaces(nodes: list[InlineElement]) -> list[InlineElement]:
    """Adjacent texts of the same formatting as one, and spaces that meet across texts as one, as in LaTeX."""
    out: list[InlineElement] = []
    for node in nodes:
        prev = out[-1] if out else None
        if isinstance(node, Text) and isinstance(prev, Text):
            if prev.content.endswith(' '):
                node.content = node.content.lstrip(' ')
            if not node.content:
                continue
            if (node.bold, node.italic, node.strikethrough, node.script) == \
                    (prev.bold, prev.italic, prev.strikethrough, prev.script):
                prev.content += node.content
                continue
        out.append(node)
    return out


def _skip_spaces(text: str, pos: int) -> int:
    """The position after the spaces a command named with letters eats ("\\ss e"); ``{}`` ends it ("\\LaTeX{} is")."""
    if text.startswith('{}', pos):
        return pos + 2
    while pos < len(text) and text[pos] in ' \t':
        pos += 1
    return pos


def _math(text: str, pos: int, elements: list, add_text: Callable[[str], None]) -> int:
    """Parse ``$...$`` or ``$$...$$`` at ``pos``; return the position after it."""
    if text.startswith('$$', pos):
        end_idx = text.find('$$', pos + 2)
        if end_idx == -1:
            add_text('$$')
            return pos + 2
        elements.append(Equation(code=text[pos + 2:end_idx].strip(), inline=False))
        return end_idx + 2
    end_idx = text.find('$', pos + 1)
    while end_idx != -1 and text[end_idx - 1] == '\\':  # not \$
        end_idx = text.find('$', end_idx + 1)
    if end_idx == -1:
        add_text('$')
        return pos + 1
    elements.append(Equation(code=text[pos + 1:end_idx].strip(), inline=True))
    return end_idx + 1


def _accent(text: str, pos: int, accent: str, add_text: Callable[[str], None]) -> int:
    """Parse the letter an accent applies to (``e``, ``{e}``, ``{\\i}``); return the position after it."""
    while pos < len(text) and text[pos] == ' ' and accent.isalpha():
        pos += 1
    if text.startswith('{', pos):
        arg, end = find_balanced_braces(text, pos)
        letter = _SYMBOLS.get(arg.strip().lstrip('\\'), arg.strip()) if arg.strip().startswith('\\') else arg.strip()
        add_text(_accented(letter[:1], accent) + letter[1:])
        return end
    if accent == '~' and (pos >= len(text) or not text[pos].isalpha()):
        add_text('~')  # \~{} or a lone \~: the tilde itself
        return pos
    if pos < len(text):
        add_text(_accented(text[pos], accent))
        return pos + 1
    return pos


_LITERAL_NAMES = {'textbackslash': '\\', 'textasciitilde': '~', 'textasciicircum': '^', 'textless': '<',
                  'textgreater': '>', 'textbar': '|'}
_LITERAL_ESCAPES = re.compile(rf'\\(?:([%&$_#{{}}~^])|{"|".join(_LITERAL_NAMES)})(?:\{{\}})?')


def _unescape_latex(text: str) -> str:
    """Literal text (code, URLs) from its LaTeX spelling: ``a\\_b`` -> ``a_b``."""
    def repl(m: re.Match) -> str:
        if m.group(1):
            return m.group(1)
        return _LITERAL_NAMES[m.group(0).lstrip('\\').removesuffix('{}')]
    return _LITERAL_ESCAPES.sub(repl, text)


def _link(args, inline, *fmt) -> list[InlineElement]:
    url = _unescape_latex(args[0].replace(URL_PERCENT, '%'))
    text = inline(args[1]) if len(args) >= 2 else [Text(content=url, bold=fmt[0], italic=fmt[1], strikethrough=fmt[2])]
    return [Link(url=url, title=None, content=text)]


_INLINE_COMMANDS: dict[str, Callable[..., list[InlineElement]]] = {
    'textbf': lambda args, inline, *fmt: inline(args[0], is_bold=True),
    'textit': lambda args, inline, *fmt: inline(args[0], is_italic=True),
    'emph': lambda args, inline, *fmt: inline(args[0], is_italic=True),
    'textsl': lambda args, inline, *fmt: inline(args[0], is_italic=True),
    'sout': lambda args, inline, *fmt: inline(args[0], is_strike=True),
    'st': lambda args, inline, *fmt: inline(args[0], is_strike=True),
    'textsuperscript': lambda args, inline, *fmt: inline(args[0], script='sup'),
    'textsubscript': lambda args, inline, *fmt: inline(args[0], script='sub'),
    'texttt': lambda args, inline, *fmt: [CodeInline(code=_unescape_latex(args[0]))],
    'tcverbatim': lambda args, inline, *fmt: [CodeInline(code=bytes.fromhex(args[0]).decode('utf-8'))],
    'thanks': lambda args, inline, *fmt: [Footnote(content=inline(args[0]))],
    'href': _link,
    'url': lambda args, inline, *fmt: _link(args[:1], inline, *fmt),
    'includegraphics': lambda args, inline, *fmt: [Image(src=args[0], alt="image")],
}
