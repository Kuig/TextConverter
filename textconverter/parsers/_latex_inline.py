"""Inline LaTeX as inline AST nodes: formatting commands, symbols, accents, math and references."""
from __future__ import annotations
import re
import unicodedata
from collections.abc import Callable
from contextvars import ContextVar

from ..ast import CodeInline, Equation, Footnote, Image, InlineElement, Label, LineBreak, Link, Node, Table, Text
from ._latex_macros import (
    REFERENCE_MACROS, extract_macro_args, find_balanced_braces, parse_reference_macro, strip_macro,
)
from ._latex_source import URL_PERCENT

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
UNKNOWN_MACROS: ContextVar[set[str] | None] = ContextVar("latex_unknown_macros", default=None)
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


def _is_blank(node: Node) -> bool:
    return isinstance(node, LineBreak) or (isinstance(node, Text) and not node.content.strip())


def clean_breaks(children: list[InlineElement]) -> list[InlineElement]:
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


def float_caption(content: str, target: Table | Image) -> None:
    """Give a figure's image or a table the float's ``\\caption`` and ``\\label`` (also one inside the caption)."""
    cap_args, _, _ = extract_macro_args(content, "\\caption")
    caption = parse_inline_latex(cap_args[0].strip()) if cap_args else []
    labels = [n.name for n in caption if isinstance(n, Label)]
    target.caption = clean_breaks([n for n in caption if not isinstance(n, Label)])
    label_args, _, _ = extract_macro_args(strip_macro(content, "\\caption"), "\\label")
    target.label = label_args[0].strip() if label_args else (labels[-1] if labels else None)


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
    unknown = UNKNOWN_MACROS.get()
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
