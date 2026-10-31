from __future__ import annotations
import re
from contextvars import ContextVar
from ..ast import (
    METADATA_FIELDS, Abstract, Bibliography, BlockQuote, Citation, CodeBlock, CodeInline, Document, Equation, Footnote,
    Heading, HorizontalRule, Image, Label, LineBreak, Link, ListBlock, Node, Paragraph, Reference, Table,
    TableCell, Text,
)
from ..parsers._latex_macros import REFERENCE_MACROS
from ..parsers.markdown_parser import emphasis_flanking, trim_bare_url
from ._common import (
    EMPHASIS_STYLES, bibliography_paragraphs, caption_paragraphs, latex_reference_macro, split_spaces, style_extent,
    table_grid, text_runs, text_style,
)

# The footnotes met while rendering one document, numbered in order.
_FOOTNOTES: ContextVar[list[Footnote] | None] = ContextVar("markdown_footnotes", default=None)

# Characters of literal text that Markdown would read as markup (see _escape).
_MD_SPECIAL = re.compile(
    rf'\\(?=[!-/:-@\[-`{{-~]|(?:{"|".join(REFERENCE_MACROS)})(?![a-zA-Z])|$)'
    r'|[*`\[\]$]'
    r'|_+'
    r'|~(?=~)|(?<=~)~|^~|~$'
    r'|<(?=[A-Za-z/!?])'
    # What would read as an entity
    r'|&(?=#?[0-9A-Za-z]+;)'
    # What would start a bare URL (GFM) in text: "http://", "https://", "www."
    r'|(?<=http):(?=//)|(?<=https):(?=//)|(?<=(?<![\w.-])www)\.'
)
# Links the renderer can write as a bare URL or an autolink (<...>).
_BARE_URL = re.compile(r'(?:https?://|www\.)\w[^\s<>\\]*$')
_AUTOLINK = re.compile(r'[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*$')
_AUTOLINK_MAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
                            r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*$")
# A block marker at the start of a line: heading, quote, list item, rule or setext underline.
_LINE_START = re.compile(
    r'^([ \t]*)(#{1,6}(?=[ \t]|$)|>|[-+](?=[ \t])|-(?=--|-*[ \t]*$)|=(?==*[ \t]*$)|\d+\.(?=[ \t]))',
    re.MULTILINE)


def _escape_line_start(m: re.Match) -> str:
    indent, marker = m.groups()
    if marker[-1] == '.':  # "1." -> "1\."
        return f"{indent}{marker[:-1]}\\."
    return f"{indent}\\{marker}"


def _sanitize_table_cell(text: str) -> str:
    """Flatten a rendered cell so it can never break its one-line table row.

    Newlines / hard breaks become ``<br>`` (GFM renders it inside cells) and a
    literal ``|`` is escaped as ``\\|`` (understood back by the Markdown table
    parser's cell splitter and by GFM renderers).
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    text = re.sub(r'[ \t]*\n[ \t]*', '<br>', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.replace('|', r'\|')


def render_markdown(doc: Document) -> str:
    """Renders an AST Document to a Markdown string.

    Metadata becomes a YAML front matter block, footnotes GFM ``[^n]``
    references with their definitions at the end.
    """
    footnotes: list[Footnote] = []
    # The front matter is read before any [^n] definition: a note there stays a macro
    metadata = _front_matter(doc)
    token = _FOOTNOTES.set(footnotes)
    try:
        blocks = [metadata, *(_render_node(child) for child in doc.children)]
        definitions = []
        # A note's content may hold another note, numbered after it
        while len(definitions) < len(footnotes):
            n = len(definitions) + 1
            body = _paragraph(Paragraph(children=footnotes[n - 1].content))
            definitions.append(f"[^{n}]: " + body.replace('\n', '\n    '))
        blocks.append('\n'.join(definitions))
    finally:
        _FOOTNOTES.reset(token)
    return '\n\n'.join(filter(bool, blocks)) + '\n'


def _front_matter(doc: Document) -> str:
    """The document metadata as YAML front matter; values are double-quoted inline Markdown."""
    lines = []
    for name in METADATA_FIELDS:
        nodes = getattr(doc, name)
        if nodes:
            value = re.sub(r'[ \t]*\n', '  \n', _inline(nodes).strip())
            value = value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            lines.append(f'{name}: "{value}"')
    return '---\n' + '\n'.join(lines) + '\n---' if lines else ""


def _footnote(node: Footnote) -> str:
    footnotes = _FOOTNOTES.get(None)
    if footnotes is None:  # rendered outside render_markdown: keep the LaTeX form
        return latex_reference_macro(node, _inline)
    footnotes.append(node)
    return f"[^{len(footnotes)}]"


def _render_node(node: Node) -> str:
    render = _RENDERERS.get(type(node))
    return render(node) if render else ""


# Each emphasis style's marker forms in order of preference; the HTML form is valid
# wherever the others are not.
_MARKERS = {
    'strikethrough': (('~~', '~~'), ('<del>', '</del>')),
    'bold': (('**', '**'), ('<strong>', '</strong>')),
    'italic': (('_', '_'), ('*', '*'), ('<em>', '</em>')),
}


class _Marker:
    """One end of an emphasis pair; the pair's form is chosen once the text around both ends is known."""
    def __init__(self, style: str, opening: bool):
        self.style = style
        self.closing = _Marker(style, False) if opening else None  # an opening marker's partner


def _inline(nodes: list[Node]) -> str:
    """Inline nodes as Markdown, emphasis opened and closed as formatting changes.

    Consecutive texts share their markers (``*a **b** c*``), spaces stay outside
    them, and any other node closes them.
    """
    pieces: list[str | _Marker] = []
    stack: list[_Marker] = []  # the open markers, outermost first
    spaces = ""  # trailing whitespace, written after the markers that close
    runs = text_runs(nodes)

    def close(keep: int) -> None:
        nonlocal spaces
        for marker in reversed(stack[keep:]):
            pieces.append(marker.closing)
        del stack[keep:]
        pieces.append(spaces)
        spaces = ""

    for k, node in enumerate(runs):
        if not isinstance(node, Text):
            close(0)
            if isinstance(node, Link):
                # A bare URL needs a space (or nothing) on both sides to end where it should
                before = next((p for p in reversed(pieces) if p), ' ')
                after = runs[k + 1] if k + 1 < len(runs) else Text(content=' ')
                bare = (isinstance(before, str) and before[-1] in ' \t\n('
                        and isinstance(after, Text) and after.content[:1].isspace())
                pieces.append(_link(node, bare=bare))
            else:
                pieces.append(_render_node(node))
            continue
        lead, core, trail = split_spaces(node.content)
        if not core:
            spaces += node.content
            continue
        styles = [s for s in EMPHASIS_STYLES if getattr(node, s)]
        keep = 0
        while keep < len(stack) and stack[keep].style in styles:
            keep += 1
        close(keep)
        pieces.append(lead)
        open_styles = {m.style for m in stack}
        for style in sorted((s for s in styles if s not in open_styles), key=lambda s: -style_extent(runs, k, s)):
            marker = _Marker(style, opening=True)
            stack.append(marker)
            pieces.append(marker)
        pieces.append(_text(node, core))
        spaces = trail
    close(0)
    return _resolve_markers(pieces)


def _resolve_markers(pieces: list[str | _Marker]) -> str:
    """Join the pieces, each marker pair in the first form that opens and closes where it stands.

    A single ``*`` is not used next to another marker, where it would join a
    ``**`` into one longer run.
    """
    markers = {i for i, piece in enumerate(pieces) if isinstance(piece, _Marker)}

    def neighbour(i: int, step: int) -> tuple[str, bool]:
        """The character next to piece ``i`` and whether it belongs to a marker."""
        i += step
        while 0 <= i < len(pieces):
            if i in markers:
                return '*', True  # every marker form starts and ends with punctuation
            if pieces[i]:
                return pieces[i][-1 if step < 0 else 0], False
            i += step
        return ' ', False

    def fits(form: str, i: int, side: int) -> bool:
        (before, marker_before), (after, marker_after) = neighbour(i, -1), neighbour(i, 1)
        if form == '*' and (marker_before or marker_after):
            return False
        return form.startswith('<') or emphasis_flanking(form[0], before, after)[side]

    for i, piece in enumerate(pieces):
        if isinstance(piece, _Marker) and piece.closing is not None:
            j = pieces.index(piece.closing, i)
            opening, closing = next(f for f in _MARKERS[piece.style] if fits(f[0], i, 0) and fits(f[1], j, 1))
            pieces[i], pieces[j] = opening, closing
    return ''.join(pieces)


def _quote(lines: list[str]) -> str:
    """Prefix every line with "> " (a bare ">" for an empty one)."""
    return '\n'.join(f"> {line}" if line.strip() else ">" for line in lines)


def _heading(node: Heading) -> str:
    return f"{'#' * node.level} {_inline(node.children)}"


def _paragraph(node: Paragraph) -> str:
    # A line of the paragraph that starts like a block (heading, quote, item, rule) is escaped
    content = _LINE_START.sub(_escape_line_start, _inline(node.children).strip())
    blocks = [re.sub(r'[ \t]*\n', '  \n', content), *(_paragraph(p) for p in caption_paragraphs(node))]
    return '\n\n'.join(filter(None, blocks))


def _code_block(node: CodeBlock) -> str:
    # The fence must be longer than any backtick run in the code
    longest = max((len(run) for run in re.findall(r'`+', node.code)), default=0)
    fence = '`' * max(3, longest + 1)
    return f"{fence}{node.language or ''}\n{node.code}\n{fence}"


def _list(node: ListBlock) -> str:
    items = []
    # An item with a second paragraph makes the list loose: items apart by a blank line
    loose = any(isinstance(c, Paragraph) for item in node.items for c in item.children[1:])
    for i, item in enumerate(node.items):
        prefix = f"{node.start + i}." if node.ordered else "-"
        if item.checked is not None:
            prefix += " [x]" if item.checked else " [ ]"
        rendered_parts = []
        for j, child in enumerate(item.children):
            rendered_child = _render_node(child)
            if not rendered_child.strip():
                continue
            if j == 0 and isinstance(child, Paragraph):
                # The first paragraph goes on the bullet/number line
                rendered_parts.append(rendered_child)
            else:
                # Other blocks go on their own lines, indented by 4 spaces; a paragraph after a blank line
                lines = rendered_child.split('\n')
                indented = '\n'.join(f"    {line}" if line.strip() else "" for line in lines)
                rendered_parts.append(('\n' + indented) if isinstance(child, Paragraph) and j else indented)
        body = '\n'.join(rendered_parts).strip()
        items.append(f"{prefix} {body}")
    return ('\n\n' if loose else '\n').join(items)


def _table(node: Table) -> str:
    headers, rows, ncols = table_grid(node)
    if not ncols:
        return ""
    header_cells = [_sanitize_table_cell(_render_node(c)) for c in headers] or [""] * ncols
    lines = ["| " + " | ".join(header_cells) + " |", "|" + "|".join(["---"] * ncols) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(_sanitize_table_cell(_render_node(c)) for c in row) + " |")
    return '\n\n'.join([*(_paragraph(p) for p in caption_paragraphs(node)), '\n'.join(lines)])


def _table_cell(node: TableCell) -> str:
    return _inline(node.children).strip()


def _escape(text: str) -> str:
    """Backslash-escape what the Markdown parser would read as markup in literal text.

    Escapes ``*``, `````, ``[``, ``]``, ``$``, an underscore run that could
    open or close emphasis (one inside a word cannot), doubled ``~`` and one at
    either end, a ``<`` that would start a tag or an autolink, a ``&`` that
    would start an entity, and a backslash that would start an escape or a
    reference macro. Block markers at the start of a line are escaped per
    paragraph (see ``_paragraph``).
    """
    def escape(m: re.Match) -> str:
        run = m.group(0)
        if run[0] != '_':
            return '\\' + run
        # Past either end may come a marker: punctuation
        before = text[m.start() - 1] if m.start() else '*'
        after = text[m.end()] if m.end() < len(text) else '*'
        return run if emphasis_flanking('_', before, after) == (False, False) else '\\_' * len(run)
    return _MD_SPECIAL.sub(escape, text)


def _escape_title(title: str | None) -> str:
    return f' "{title.replace(chr(34), chr(92) + chr(34))}"' if title else ''


def _destination(url: str) -> str:
    """A link or image URL; in ``<...>`` when it has spaces or unbalanced parentheses."""
    depth = 0
    for ch in url:
        depth += {'(': 1, ')': -1}.get(ch, 0)
        if depth < 0:
            break
    if depth or re.search(r'\s', url) or not url:
        return f"<{url}>"
    return url


def _text(node: Text, core: str) -> str:
    """The escaped text of a run, without its emphasis markers."""
    content = _escape(core)
    if node.script:
        content = f"<{node.script}>{content}</{node.script}>"
    return content


def _link(node: Link, bare: bool = False) -> str:
    """A link; one showing its own URL is an autolink, or a bare URL when ``bare`` allows it."""
    shown = node.content[0].content if len(node.content) == 1 and isinstance(node.content[0], Text) else None
    if shown is not None and not node.title and text_style(node.content[0]) == (False, False, False, None):
        if bare and node.url in (shown, 'http://' + shown) and _BARE_URL.match(shown) and trim_bare_url(shown) == shown:
            return shown
        if shown == node.url and _AUTOLINK.match(shown):
            return f"<{shown}>"
        if node.url == 'mailto:' + shown and _AUTOLINK_MAIL.match(shown):
            return f"<{shown}>"
    return f"[{_inline(node.content)}]({_destination(node.url)}{_escape_title(node.title)})"


def _image(node: Image) -> str:
    alt = re.sub(r'([\\\[\]])', r'\\\1', node.alt)
    return f'![{alt}]({_destination(node.src)}{_escape_title(node.title)})'


def _code_inline(node: CodeInline) -> str:
    """A code span fenced by more backticks than the code holds in a row."""
    longest = max((len(run) for run in re.findall(r'`+', node.code)), default=0)
    fence = '`' * (longest + 1)
    pad = ' ' if node.code.startswith('`') or node.code.endswith('`') else ''
    return f"{fence}{pad}{node.code}{pad}{fence}"


def _quoted_blocks(children: list[Node]) -> list[str]:
    """The lines of a quote's blocks, a blank line between blocks (a line break alone would join them)."""
    return '\n\n'.join(filter(None, (_render_node(c) for c in children))).split('\n')


def _block_quote(node: BlockQuote) -> str:
    lines = _quoted_blocks(node.children)
    if node.alert_type:
        lines.insert(0, f"[!{node.alert_type}]")
    return _quote(lines)


def _abstract(node: Abstract) -> str:
    return _quote(["[!IMPORTANT]", "**Abstract**  ", *_quoted_blocks(node.children)])


def _equation(node: Equation) -> str:
    if node.inline:
        return f"${node.code}$"
    if node.env:  # the environment travels inside the formula, where MathJax/KaTeX read it too
        return f"$$\n\\begin{{{node.env}}}\n{node.code}\n\\end{{{node.env}}}\n$$"
    return f"$$\n{node.code}\n$$"


_RENDERERS = {
    Heading: _heading,
    Paragraph: _paragraph,
    CodeBlock: _code_block,
    ListBlock: _list,
    Table: _table,
    TableCell: _table_cell,
    Text: lambda node: _inline([node]),
    Link: _link,
    Image: _image,
    CodeInline: _code_inline,
    # The enclosing paragraph turns every "\n" into a hard break ("  \n")
    LineBreak: lambda node: " \\and " if node.author_separator else "\n",
    BlockQuote: _block_quote,
    HorizontalRule: lambda node: "---",
    Equation: _equation,
    Abstract: _abstract,
    Footnote: _footnote,
    # Commands and entries stay visible as LaTeX, one per paragraph
    Bibliography: lambda node: '\n\n'.join(_paragraph(p) for p in bibliography_paragraphs(node)),
    **{cls: lambda node: latex_reference_macro(node, _inline) for cls in (Citation, Reference, Label)},
}
