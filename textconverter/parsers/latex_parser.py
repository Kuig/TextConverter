from __future__ import annotations
import re
from dataclasses import dataclass

from ..ast import (
    METADATA_FIELDS, Abstract, Appendix, BibEntry, Bibliography, BlockQuote, CodeBlock, Document, Equation, Heading,
    HorizontalRule, Image, InlineElement, Label, LineBreak, ListBlock, ListItem, Node, Paragraph, Table, Text,
)
from ..logger import log_warning
from ._latex_inline import UNKNOWN_MACROS, clean_breaks, float_caption, parse_inline_latex
from ._latex_macros import BIBLIOGRAPHY_COMMAND, ENV_BOUNDARY, extract_macro_args, find_balanced_braces, strip_macro
from ._latex_source import HiddenCode, prepare_source
from ._latex_tables import TABLE_ENVS, TABLE_FLOATS, TABLE_START, parse_latex_table
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
_BIB_ITEM = re.compile(r'\\bibitem(?:\[([^\]]*)\])?\s*\{([^{}]*)\}')
_ALERTS = ('NOTE', 'TIP', 'IMPORTANT', 'WARNING', 'CAUTION')
_THEOREM_ENVS = ('theorem', 'lemma', 'proposition', 'corollary', 'definition', 'remark', 'example', 'proof',
                 'claim', 'conjecture')


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
    token = UNKNOWN_MACROS.set(unknown)
    try:
        doc = _parse_source(text, source)
    finally:
        UNKNOWN_MACROS.reset(token)
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
        text = strip_macro(text, cmd)
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
            setattr(doc, name, clean_breaks(parse_inline_latex(args[0].strip())))
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
                if clean_breaks(run):
                    nodes.append(Paragraph(children=clean_breaks(run)))
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
                                    children=clean_breaks(parse_inline_latex(body.strip()))))
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
            float_caption(body, found[0])
        images.extend(found)
        rest = rest[:start] + rest[end:]
    if images:
        label_args, _, _ = extract_macro_args(strip_macro(rest, "\\caption"), "\\label")
        caption = _caption_paragraph(rest, "Figure")
        if caption and label_args:
            caption[0].children.extend([Text(content=" "), Label(name=label_args[0].strip())])
        return [Paragraph(children=images), *caption]
    images = _images(content)
    if not images:
        return _caption_paragraph(content, "Figure")
    float_caption(content, images[0])
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
    if env in TABLE_ENVS:
        return [parse_latex_table(content.strip())]
    if env in ('figure', 'figure*'):
        return _figure(content)
    if env in TABLE_FLOATS:
        tables = _float_tables(content)
        if not tables:
            return _caption_paragraph(content, "Table")
        float_caption(content, tables[0])
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
    while (start := TABLE_START.search(content, pos)) is not None:
        body, begin, end = _extract_environment(content, start.group(1), start.start())
        if begin == -1:  # unclosed: skip the \begin and read on
            pos = start.end()
            continue
        tables.append(parse_latex_table(body.strip()))
        pos = end
    return tables


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
        for boundary in ENV_BOUNDARY.finditer(content, pos, item.start()):
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
