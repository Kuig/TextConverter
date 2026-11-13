"""Parse plain text into the AST: the block structure of ``_text_format``, and no inline markup.

Blocks are told by their lines: an underlined heading, ``-``/``1.`` list
items, ``>`` quotes, code indented by four spaces, ``+---+`` grid tables,
``$$`` formulas and rules. Inline text stays literal (``*word*`` keeps its
asterisks): only bare URLs become links and reference macros nodes, as in
every text format. A paragraph keeps its line breaks unless the whole text is
wrapped at a fixed width (see ``_Parser.fill_paragraphs``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from ..ast import (
    BlockQuote, CodeBlock, Document, Equation, Footnote, Heading, HorizontalRule, LineBreak, Link, ListBlock,
    ListItem, Node, Paragraph, Table, TableCell, TableRow, Text, abstract_from, child_lists,
)
from ._latex_macros import lift_macros
from ._markdown_inline import trim_bare_url
from ._text_format import (
    CODE_INDENT, METADATA_LABELS, NOTE_DEFINITION, NOTE_MARKER, TITLE_RULE, UNDERLINES, char_width, display_width,
)
from .markdown_parser import attach_captions, split_authors

_BULLET = re.compile(r'( {0,3})[-*+•](?: +|$)')
_ORDERED = re.compile(r'( {0,3})(\d{1,9})[.)](?: +|$)')
_TASK = re.compile(r'\[([ xX])\](?: |$)')
_ALERT = re.compile(r'\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]$', re.IGNORECASE)
_UNDERLINE = re.compile(rf'([{re.escape(UNDERLINES)}])\1{{2,}}$')
_RULE_LINE = re.compile(r'([-*_=])(?: ?\1){2,}$')
_TABLE_BORDER = re.compile(r'\+(?:[-=]+\+)+$')
_DISPLAY_MATH = re.compile(r'\$\$(.+)\$\$$')
_MATH_ENV = re.compile(r'\\begin\{([A-Za-z]+\*?)\}\n(.*)\n\\end\{\1\}', re.DOTALL)
_URL = re.compile(r'https?://[^\s<>"]+')
# The widths a text can be wrapped at: shorter lines are verses or addresses, longer ones not wrapped.
_MIN_WRAP = 50
_MAX_WRAP = 100
# A text is wrapped at a fixed width when this share of its paragraph lines, at least
# _MIN_WRAPPED of them, end where the next word would not have fitted.
_WRAPPED_SHARE = 0.5
_MIN_WRAPPED = 3


@dataclass
class _Marker:
    """A list item's marker: its kind, the column its content starts at and its number."""
    ordered: bool
    column: int
    number: int = 1


def parse_text(text: str) -> Document:
    """Parses plain text into an AST Document.

    A title between two rules of ``=`` and the ``Author:``/``Date:`` lines
    under it (or opening a text without a title) are the metadata; ``[n]``
    markers become footnotes when the text ends with their ``[n] ...``
    paragraphs, numbered from 1.
    """
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    doc = Document()
    start = _read_metadata(lines, doc)
    parser = _Parser()
    doc.children = parser.blocks(lines[start:])
    parser.fill_paragraphs()
    _lift_abstracts(doc)
    _lift_footnotes(doc)
    attach_captions(doc.children)
    return doc


def _indent_of(line: str) -> int:
    """The columns of a line's indentation, a tab reaching the next multiple of four."""
    return len(line[:len(line) - len(line.lstrip(' \t'))].expandtabs(CODE_INDENT))


def _dedent(line: str, columns: int) -> str:
    """The line without ``columns`` columns of indentation; a tab past them is content, as in code."""
    column = k = 0
    while k < len(line) and column < columns and line[k] in ' \t':
        column = column + 1 if line[k] == ' ' else (column // CODE_INDENT + 1) * CODE_INDENT
        k += 1
    return ' ' * (column - columns) + line[k:]


def _inline(text: str) -> list[Node]:
    """Literal text, a ``\\n`` a line break; bare URLs become links and reference macros nodes."""
    nodes: list[Node] = []
    for k, line in enumerate(text.split('\n')):
        if k:
            nodes.append(LineBreak())
        pos = 0
        for m in _URL.finditer(line):
            url = trim_bare_url(m.group(0))
            if m.start() > pos:
                nodes.append(Text(content=line[pos:m.start()]))
            nodes.append(Link(url=url, content=[Text(content=url)]))
            pos = m.start() + len(url)
        if pos < len(line):
            nodes.append(Text(content=line[pos:]))
    return lift_macros(nodes)


def _is_title_rule(line: str) -> bool:
    line = line.strip()
    return len(line) >= 3 and line == TITLE_RULE * len(line)


def _label(line: str) -> tuple[str, str] | None:
    """``(field, value)`` of a metadata line."""
    for name, label in METADATA_LABELS.items():
        if line == label or line.startswith(label + ' '):
            return name, line[len(label):].strip()
    return None


def _read_metadata(lines: list[str], doc: Document) -> int:
    """Read the title block and the labelled lines into ``doc``; return the index of the first line after them.

    A line under a labelled one that has no label continues its value after a line break.
    """
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and _is_title_rule(lines[i]):
        j = i + 1
        while j < len(lines) and lines[j].strip() and not _is_title_rule(lines[j]):
            j += 1
        if j > i + 1 and j < len(lines) and _is_title_rule(lines[j]):
            doc.title = _inline('\n'.join(line.strip() for line in lines[i + 1:j]))
            i = j + 1
    if i < len(lines) and _label(lines[i]):
        values: dict[str, list[str]] = {}
        name = ""
        while i < len(lines) and lines[i].strip():
            labelled = _label(lines[i])
            if labelled:
                name, value = labelled
                values[name] = [value]
            else:
                values[name].append(lines[i].strip())
            i += 1
        for name, value in values.items():
            nodes = _inline('\n'.join(value))
            setattr(doc, name, split_authors(nodes) if name == "author" else nodes)
    return i


def _marker(line: str) -> _Marker | None:
    """The list item marker the line opens with; a rule (``* * *``) has none."""
    if _RULE_LINE.match(line.strip()):
        return None
    m = _BULLET.match(line)
    if m:
        return _Marker(ordered=False, column=_content_column(line, m))
    m = _ORDERED.match(line)
    if m:
        return _Marker(ordered=True, column=_content_column(line, m), number=int(m.group(2)))
    return None


def _content_column(line: str, m: re.Match) -> int:
    """Where an item's text starts; one space past the marker when it has none."""
    return m.end() if m.end() < len(line) else len(line.rstrip()) + 1


def _interrupts(line: str) -> bool:
    """Whether a line ends the paragraph above it and starts a block of its own."""
    stripped = line.strip()
    marker = _marker(line)
    return (bool(marker and (not marker.ordered or marker.number == 1)) or stripped.startswith('>')
            or bool(_TABLE_BORDER.match(stripped)) or stripped.startswith('$$') or stripped == "* * *")


class _Parser:
    """Reads blocks; paragraphs get their text once the whole document is read (see ``fill_paragraphs``)."""

    def __init__(self) -> None:
        self.paragraphs: list[tuple[Paragraph, list[str]]] = []

    def blocks(self, lines: list[str]) -> list[Node]:
        """The blocks of a run of lines, a container's lines without its indentation or ``>``."""
        out: list[Node] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                i += 1
            elif _indent_of(line) >= CODE_INDENT:
                i = self._code(lines, i, out)
            elif _RULE_LINE.match(stripped):
                out.append(HorizontalRule())
                i += 1
            elif i + 1 < len(lines) and _UNDERLINE.match(lines[i + 1].strip()):
                level = UNDERLINES.index(lines[i + 1].strip()[0]) + 1
                out.append(Heading(level=level, children=_inline(stripped)))
                i += 2
            elif _TABLE_BORDER.match(stripped) and (table := self._table(lines, i)) is not None:
                i = table[1]
                out.append(table[0])
            elif stripped.startswith('>'):
                i = self._quote(lines, i, out)
            elif stripped.startswith('$$') and (math := self._math(lines, i)) is not None:
                i = math[1]
                out.append(math[0])
            elif _marker(line):
                i = self._list(lines, i, out)
            else:
                i = self._paragraph(lines, i, out)
        return out

    def _code(self, lines: list[str], i: int, out: list[Node]) -> int:
        """An indented block, blank lines included up to the last indented line."""
        body = []
        while i < len(lines) and (not lines[i].strip() or _indent_of(lines[i]) >= CODE_INDENT):
            body.append(_dedent(lines[i], CODE_INDENT))
            i += 1
        while body and not body[-1].strip():
            body.pop()
        out.append(CodeBlock(code='\n'.join(body)))
        return i

    def _table(self, lines: list[str], i: int) -> tuple[Table, int] | None:
        """A grid table from its top border; cells are cut at the columns of the border's ``+``."""
        indent = _indent_of(lines[i])
        bounds = [k for k, ch in enumerate(lines[i].strip()) if ch == '+']
        rows: list[list[str]] = []
        current: list[str] = []
        header = False
        i += 1
        while i < len(lines):
            stripped = lines[i].strip()
            if _TABLE_BORDER.match(stripped):
                header = header or (not rows and '=' in stripped)
                rows.append(current)
                current = []
            elif stripped.startswith('|'):
                current.append(_dedent(lines[i], indent))
            else:
                break
            i += 1
        rows = [row for row in rows + [current] if row]
        if not rows:
            return None
        cells = [[TableCell(children=_inline('\n'.join(filter(None, column)))) for column in
                  zip(*(_cut(line, bounds) for line in row))] for row in rows]
        table = Table(headers=cells[0] if header else [], rows=[TableRow(cells=row) for row in cells[int(header):]])
        return table, i

    def _quote(self, lines: list[str], i: int, out: list[Node]) -> int:
        body = []
        while i < len(lines) and lines[i].lstrip().startswith('>'):
            content = lines[i].lstrip()[1:]
            body.append(content[1:] if content.startswith(' ') else content)
            i += 1
        alert = _ALERT.match(body[0].strip())
        if alert:
            body = body[1:]
        out.append(BlockQuote(children=self.blocks(body), alert_type=alert.group(1).upper() if alert else None))
        return i

    def _math(self, lines: list[str], i: int) -> tuple[Equation, int] | None:
        """A ``$$`` formula: on one line, or between two ``$$`` lines; an environment written in it is kept."""
        one_line = _DISPLAY_MATH.match(lines[i].strip())
        if one_line:
            return Equation(code=one_line.group(1).strip()), i + 1
        if lines[i].strip() != '$$':
            return None
        end = next((j for j in range(i + 1, len(lines)) if lines[j].strip() == '$$'), None)
        if end is None:
            return None
        code = '\n'.join(lines[i + 1:end])
        env = _MATH_ENV.fullmatch(code)
        return (Equation(code=env.group(2), env=env.group(1)) if env else Equation(code=code)), end + 1

    def _list(self, lines: list[str], i: int, out: list[Node]) -> int:
        """A list: the items with the kind of marker of the first, apart by blank lines or not.

        Numbers that do not follow on start another list.

        After a blank line, an item goes on with lines indented to its text, or
        by four spaces more (code); without one, with any indented line and with
        a text line that starts no block.
        """
        first = _marker(lines[i])
        node = ListBlock(ordered=first.ordered, start=first.number)
        while i < len(lines):
            marker = _marker(lines[i])
            if marker is None or marker.ordered != first.ordered:
                break
            if marker.ordered and marker.number != node.start + len(node.items):
                break  # numbering that starts again is another list
            col = marker.column
            content = [lines[i][col:]]
            i += 1
            while i < len(lines):
                line = lines[i]
                after_blank = not content[-1].strip()
                if not line.strip():
                    content.append("")
                elif _indent_of(line) == col or _indent_of(line) >= col + CODE_INDENT:
                    content.append(_dedent(line, col))
                elif after_blank:
                    break
                elif _indent_of(line) > col:
                    content.append(_dedent(line, col))
                elif _marker(line) is None and not _interrupts(line):
                    content.append(line.strip())
                else:
                    break
                i += 1
            while content and not content[-1].strip():
                content.pop()
            task = _TASK.match(content[0]) if content else None
            if task:
                content[0] = content[0][task.end():]
            node.items.append(ListItem(children=self.blocks(content),
                                       checked=task.group(1) != ' ' if task else None))
            while i < len(lines) and not lines[i].strip():
                i += 1
        out.append(node)
        return i

    def _paragraph(self, lines: list[str], i: int, out: list[Node]) -> int:
        """Lines up to a blank one, a line that starts a block, or a heading's text line."""
        body = [lines[i].strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not _interrupts(lines[i]):
            if i + 1 < len(lines) and _UNDERLINE.match(lines[i + 1].strip()):
                break
            body.append(lines[i].strip())
            i += 1
        paragraph = Paragraph()
        self.paragraphs.append((paragraph, body))
        out.append(paragraph)
        return i

    def fill_paragraphs(self) -> None:
        """Give each paragraph its text, its lines joined by line breaks, or by spaces in a wrapped text.

        The width is the longest line that a line of the same paragraph
        follows, up to ``_MAX_WRAP``. A text is wrapped at it when it is at
        least ``_MIN_WRAP`` and half of those lines, three at least, end where
        the next word would not have fitted; then only those join, so the
        lines of an address or a signature stay.
        """
        pairs = [(a, b) for _, body in self.paragraphs for a, b in zip(body, body[1:])]
        width = max((display_width(a) for a, _ in pairs if display_width(a) <= _MAX_WRAP), default=0)

        def wrapped(a: str, b: str) -> bool:
            return display_width(a) + 1 + display_width(b.split()[0]) > width

        count = sum(wrapped(a, b) for a, b in pairs)
        joined = width >= _MIN_WRAP and count >= _MIN_WRAPPED and count >= _WRAPPED_SHARE * len(pairs)
        for paragraph, body in self.paragraphs:
            text = body[0]
            for a, b in zip(body, body[1:]):
                text += (' ' if joined and wrapped(a, b) else '\n') + b
            paragraph.children = _inline(text)


def _cut(line: str, bounds: list[int]) -> list[str]:
    """The text of each cell of a table line, cut at the display columns of the border's ``+``."""
    cells: list[list[str]] = [[] for _ in bounds[1:]]
    column = 0
    for ch in line:
        for k in range(len(cells)):
            if bounds[k] < column < bounds[k + 1]:
                cells[k].append(ch)
                break
        column += char_width(ch)
    return [''.join(cell).strip() for cell in cells]


def _lift_abstracts(node: Node) -> None:
    """Turn each quote that opens with "Abstract" into an Abstract, without that word."""
    for lst in child_lists(node):
        for k, child in enumerate(lst):
            if isinstance(child, BlockQuote) and child.alert_type is None:
                abstract = abstract_from(child.children)
                if abstract is not None:
                    abstract.children[:] = [c for c in abstract.children
                                            if not (isinstance(c, Paragraph) and not c.children)]
                    lst[k] = abstract
            _lift_abstracts(lst[k])


def _lift_footnotes(doc: Document) -> None:
    """Turn ``[n]`` markers into the notes the document ends with, when every note has its marker.

    The notes are the last paragraphs, ``[1] ...`` to ``[N] ...``. A marker
    takes the first unused note of its number, in document order, then in the
    notes' own order (a note in a note is numbered after the others).
    """
    start = len(doc.children)
    while start and _definition(doc.children[start - 1]) is not None:
        start -= 1
    numbers = [_definition(p) for p in doc.children[start:]]
    if 1 not in numbers:
        return
    start += len(numbers) - 1 - numbers[::-1].index(1)
    numbers = [_definition(p) for p in doc.children[start:]]
    if numbers != list(range(1, len(numbers) + 1)):
        return
    notes = {}
    for n, paragraph in zip(numbers, doc.children[start:]):
        first = paragraph.children[0]
        rest = first.content[NOTE_DEFINITION.match(first.content).end():]
        notes[n] = [*([replace(first, content=rest)] if rest else []), *paragraph.children[1:]]
    body = doc.children[:start]
    marked = {int(m.group(1)) for holder in (Document(children=body), *(Paragraph(children=c) for c in notes.values()))
              for node in _texts(holder) for m in NOTE_MARKER.finditer(node.content)}
    if not set(notes) <= marked:
        return
    used: set[int] = set()
    holder = Document(children=body)
    _place_notes(holder, notes, used)
    for n in sorted(notes):
        if n in used:
            _place_notes(Paragraph(children=notes[n]), notes, used)
    doc.children = holder.children + [paragraph for n, paragraph in zip(numbers, doc.children[start:])
                                      if n not in used]


def _definition(block: Node) -> int | None:
    """The number of a ``[n] ...`` paragraph."""
    if not isinstance(block, Paragraph) or not block.children or not isinstance(block.children[0], Text):
        return None
    m = NOTE_DEFINITION.match(block.children[0].content)
    return int(m.group(1)) if m else None


def _texts(node: Node):
    """The Text nodes under ``node``, not looking into notes."""
    for lst in child_lists(node):
        for child in lst:
            if isinstance(child, Text):
                yield child
            elif not isinstance(child, Footnote):
                yield from _texts(child)


def _place_notes(node: Node, notes: dict[int, list[Node]], used: set[int]) -> None:
    """Replace the markers under ``node`` with their notes, each note once; notes are not looked into."""
    for lst in child_lists(node):
        out: list[Node] = []
        for child in lst:
            if not isinstance(child, Text):
                out.append(child)
                if not isinstance(child, Footnote):
                    _place_notes(child, notes, used)
                continue
            pos = 0
            for m in NOTE_MARKER.finditer(child.content):
                n = int(m.group(1))
                if n in notes and n not in used:
                    used.add(n)
                    if m.start() > pos:
                        out.append(replace(child, content=child.content[pos:m.start()]))
                    out.append(Footnote(content=notes[n]))
                    pos = m.end()
            if pos < len(child.content):
                out.append(replace(child, content=child.content[pos:]) if pos else child)
        lst[:] = out
