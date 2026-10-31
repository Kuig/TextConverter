"""Inline Markdown as inline AST nodes: escapes, CommonMark emphasis, links, images, code and math."""
from __future__ import annotations
import base64
import html
import html.entities
import re
import unicodedata
from dataclasses import dataclass, field, replace

from ..ast import CodeInline, Equation, Footnote, Image, InlineElement, LineBreak, Link, Text, walk
from ._latex_macros import REFERENCE_MACROS, parse_reference_macro

_ENTITY = re.compile(r'&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[a-zA-Z][a-zA-Z0-9]*);')

# Backslash escapes: each escapable ASCII punctuation character stands in a
# private-use code point while inline syntax is matched, so "\*" or "\[" is
# never read as markup; the character comes back as plain text afterwards.
_PUNCTUATION = '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'
_ESCAPE_RE = re.compile(r'\\([!-/:-@\[-`{-~])')
_TO_SENTINEL = {c: chr(0xE000 + i) for i, c in enumerate(_PUNCTUATION)}
_FROM_SENTINEL = {v: k for k, v in _TO_SENTINEL.items()}
_SENTINEL_RE = re.compile('[' + ''.join(_FROM_SENTINEL) + ']')
# Stands for a hard line break while soft ones become spaces.
_HARD_BREAK = ''


def protect_escapes(text: str) -> str:
    return _ESCAPE_RE.sub(lambda m: _TO_SENTINEL[m.group(1)], text)


def _decode_entity(m: re.Match) -> str:
    """The character of an entity; an unknown name stays as written."""
    name = m.group(0)
    return html.unescape(name) if name[1] == '#' or name[1:] in html.entities.html5 else name


def unescape(text: str) -> str:
    """Literal text: entities decoded and escaped characters back (an escaped ``&`` opens no entity)."""
    return _SENTINEL_RE.sub(lambda m: _FROM_SENTINEL[m.group(0)], _ENTITY.sub(_decode_entity, text))


def _restore_raw(text: str) -> str:
    """Escaped characters back with their backslash (code and math keep the source)."""
    return _SENTINEL_RE.sub(lambda m: '\\' + _FROM_SENTINEL[m.group(0)], text)


def _is_punctuation(ch: str) -> bool:
    """Unicode punctuation or symbol, as CommonMark counts it (an escaped character too)."""
    return ch in _PUNCTUATION or ch in _FROM_SENTINEL or unicodedata.category(ch)[0] in 'PS'


def emphasis_flanking(char: str, before: str, after: str) -> tuple[bool, bool]:
    """Whether a run of ``char`` (``*``, ``_`` or ``~``) between ``before`` and ``after`` can open, close.

    CommonMark's flanking rules; the start or end of the text counts as a
    space, so pass ``" "`` there. An underscore inside a word neither opens
    nor closes. Shared with the Markdown renderer, which picks its markers by it.
    """
    left = not after.isspace() and (not _is_punctuation(after) or before.isspace() or _is_punctuation(before))
    right = not before.isspace() and (not _is_punctuation(before) or after.isspace() or _is_punctuation(after))
    if char == '_':
        return left and (not right or _is_punctuation(before)), right and (not left or _is_punctuation(after))
    return left, right


@dataclass
class _Delimiter:
    """A run of ``*``, ``_`` or ``~~`` that may open or close emphasis."""
    char: str
    count: int    # the characters not yet matched
    length: int   # the run's length in the source (CommonMark's "rule of 3")
    can_open: bool
    can_close: bool
    styles: dict[str, bool] = field(default_factory=dict)  # the emphasis around it, if it stays literal


_DELIMITER_RUN = re.compile(r'\*+|_+|~+')
_EMPHASIS_STYLE = {'~': 'strikethrough'}


def _scan_text(text: str, start: int, end: int, items: list) -> None:
    """Append ``text[start:end]`` to ``items`` as Text nodes and emphasis delimiters."""
    pos = start
    for m in _DELIMITER_RUN.finditer(text, start, end):
        run = m.group()
        if run[0] == '~' and len(run) != 2:  # only "~~" is strikethrough
            continue
        if m.start() > pos:
            items.append(Text(content=unescape(text[pos:m.start()])))
        before = text[m.start() - 1] if m.start() else ' '
        after = text[m.end()] if m.end() < len(text) else ' '
        items.append(_Delimiter(run[0], len(run), len(run), *emphasis_flanking(run[0], before, after)))
        pos = m.end()
    if end > pos:
        items.append(Text(content=unescape(text[pos:end])))


def _style(item, attr: str, value=True) -> None:
    """Set one formatting attribute on an item: a delimiter, a Text, or a link's texts."""
    if isinstance(item, _Delimiter):
        item.styles[attr] = value
    for node in walk(item) if isinstance(item, (Text, Link)) else ():
        if isinstance(node, Text):
            setattr(node, attr, value)


def _rule_of_three(opener: _Delimiter, closer: _Delimiter) -> bool:
    """CommonMark: runs that can both open and close match only if their lengths do not sum to a multiple of 3."""
    return (opener.char != '~' and (opener.can_close or closer.can_open)
            and (opener.length + closer.length) % 3 == 0
            and not (opener.length % 3 == 0 and closer.length % 3 == 0))


def _resolve_emphasis(items: list) -> list[InlineElement]:
    """Match emphasis delimiters (CommonMark's algorithm) and style what they enclose.

    Each closer takes the nearest opener of the same character; two characters
    on both sides make bold, one makes italic, ``~~`` strikethrough. The
    delimiters between them, and those left unmatched, are literal text.
    """
    i = 0
    while i < len(items):
        closer = items[i]
        if not (isinstance(closer, _Delimiter) and closer.can_close and closer.count):
            i += 1
            continue
        j = next((j for j in range(i - 1, -1, -1)
                  if isinstance(items[j], _Delimiter) and items[j].char == closer.char and items[j].can_open
                  and items[j].count and not _rule_of_three(items[j], closer)), None)
        if j is None:
            i += 1
            continue
        opener = items[j]
        used = 2 if opener.count >= 2 and closer.count >= 2 else 1
        style = _EMPHASIS_STYLE.get(closer.char, 'bold' if used == 2 else 'italic')
        for item in items[j + 1:i]:
            _style(item, style)
            if isinstance(item, _Delimiter):
                item.can_open = item.can_close = False
        opener.count -= used
        closer.count -= used
        if not closer.count:
            i += 1

    nodes: list[InlineElement] = []
    for item in items:
        if isinstance(item, _Delimiter):
            if not item.count:
                continue
            item = Text(content=item.char * item.count, **item.styles)
        prev = nodes[-1] if nodes else None
        if isinstance(item, Text) and isinstance(prev, Text) and _text_style(item) == _text_style(prev):
            nodes[-1] = replace(prev, content=prev.content + item.content)
        else:
            nodes.append(item)
    return nodes


def _text_style(node: Text) -> tuple:
    return node.bold, node.italic, node.strikethrough, node.script


def _url_pattern(name: str) -> str:
    """A link destination: ``<...>`` (may hold spaces), or a URL with balanced parentheses."""
    return rf'(?:<(?P<{name}_b>[^<>\n]*)>|(?P<{name}>(?:[^\s()]|\([^\s()]*\))*))'


# Inline HTML read as formatting; any other tag is dropped and what it encloses stays.
_HTML_STYLES = {'sup': ('script', 'sup'), 'sub': ('script', 'sub'), 'strong': ('bold', True), 'b': ('bold', True),
                'em': ('italic', True), 'i': ('italic', True), 'del': ('strikethrough', True),
                's': ('strikethrough', True)}

_INLINE = re.compile(
    # Footnotes, citations, cross-references (kept as LaTeX macros)
    rf'(?P<latexmacro>\\(?:{"|".join(REFERENCE_MACROS)})\*?(?![a-zA-Z]))|'
    # GFM footnote reference: [^id]
    r'(?P<fnref>\[\^(?P<fn_id>[^\]\s]+)\])|'
    # Reference-style image: ![alt][id] (must come before reflink and inline-image)
    r'(?P<refimg>!\[(?P<ri_alt>[^\]]*)\]\[(?P<ri_id>[^\]]*)\])|'
    # Reference-style link: [content][id]; content may include inline images
    # Uses .*? (non-greedy) so it stops at the first ][id] after the opening [
    r'(?P<reflink>(?<!!)(?<!\])\[(?P<rl_text>.*?)\]\[(?P<rl_id>[^\]]*)\])|'
    # Inline image: ![alt](url "title") with optional OCR block
    rf'(?P<inlineimg>!\[(?P<img_alt>[^\]]*)\]\({_url_pattern("img_url")}(?:\s+"(?P<img_title>[^"]*)")?\)'
    r'(?:<!--OCR:(?P<ocr_b64>[A-Za-z0-9+/=]+)-->)?)|'
    # Linked image: [![alt](imgurl "imgtitle")](linkurl "linktitle"), an inline image
    # used as the entire content of an inline link. Must come before inlinelink, whose
    # link_text ([^\]]+) cannot span the nested image's own closing bracket/paren and
    # would otherwise misparse the image's URL as the link's URL.
    rf'(?P<linkedimg>\[!\[(?P<li_alt>[^\]]*)\]\({_url_pattern("li_img_url")}(?:\s+"(?P<li_img_title>[^"]*)")?\)\]'
    rf'\({_url_pattern("li_link_url")}(?:\s+"(?P<li_link_title>[^"]*)")?\))|'
    # Inline link: [text](url "title")
    rf'(?P<inlinelink>(?<!!)(?<!\])\[(?P<link_text>[^\]]+)\]\({_url_pattern("link_url")}(?:\s+"(?P<link_title>[^"]*)")?\))|'
    # Shortcut reference: [id] (literal text when the id is not defined)
    r'(?P<shortcut>(?<![!\]])\[(?P<sc_text>[^\[\]]+)\](?![\[(]))|'
    # Code span: as many backticks to close as to open
    r'(?P<codeinline>(?P<ticks>`+)(?P<code_content>.+?)(?<!`)(?P=ticks)(?!`))|'
    r'(?P<mathinline>(?<!\\)\$(?!\s)(?P<math_content>[^$]+?)(?<!\s)(?<!\\)\$)|'
    # Autolinks: <scheme:...> and <user@host>
    r'(?P<autolink><(?P<auto_url>[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*)>)|'
    r'(?P<automail><(?P<mail>[\w.!#$%&\'*+/=?^`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?'
    r'(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*)>)|'
    # A bare URL (GFM): after a space, "(" or an emphasis character; trailing punctuation is trimmed
    r'(?P<bareurl>(?<![^\s*_~(])(?:https?://|www\.)[^\s<]+)|'
    r'(?P<linebreak><br\s*/?>)|'
    rf'(?P<html>(?i:<(?P<tag>{"|".join(_HTML_STYLES)}|kbd)>)(?P<html_content>.*?)(?i:</(?P=tag)>))|'
    # Any other tag; "a < b" and "<3" are not tags
    r'(?P<anytag></?[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z_:][\w:.-]*(?:\s*=\s*(?:"[^"]*"|\x27[^\x27]*\x27|[^\s"\x27=<>`]+))?)*\s*/?>)'
)


def _title(value: str | None) -> str | None:
    return unescape(value) if value else value


def _url(g: dict, name: str) -> str:
    return unescape(g[f'{name}_b'] if g[f'{name}_b'] is not None else g[name] or '')


def trim_bare_url(url: str) -> str:
    """A bare URL without the trailing punctuation and unbalanced ``)`` that GFM leaves out of it."""
    while True:
        trimmed = url.rstrip('?!.,:*_~\'";')
        if trimmed.endswith(')') and trimmed.count(')') > trimmed.count('('):
            trimmed = trimmed[:-1]
        if trimmed == url:
            return url
        url = trimmed


def parse_inline(text: str, ref_map: dict | None = None, autolinks: bool = True) -> list[InlineElement]:
    """Parses inline markdown like bold, italic, links, images, code.

    Backslash escapes (``\\*``, ``\\[``, ...) make the character literal.

    Args:
        text: The inline markdown string to parse.
        ref_map: Optional dict mapping lowercase reference labels to (url, title) tuples,
                 used to resolve reference-style links and images.
        autolinks: Whether bare URLs become links (not inside a link's own text).
    """
    # A hard break (two trailing spaces or a backslash) is a "\n"; any other line break is a space
    text = re.sub(r'(?:[ \t]{2,}|[ \t]*\\)\n[ \t]*', _HARD_BREAK, text)
    text = re.sub(r'[ \t]*\n[ \t]*', ' ', text).replace(_HARD_BREAK, '\n')
    text = protect_escapes(text)
    ref_map = ref_map or {}
    items: list = []  # inline nodes and emphasis delimiters, matched at the end

    pos = 0
    while pos < len(text):
        m = _INLINE.search(text, pos)
        while m and m.group('bareurl') is not None and not autolinks:
            m = _INLINE.search(text, m.start() + 1)
        _scan_text(text, pos, m.start() if m else len(text), items)
        if not m:
            break
        g = m.groupdict()
        pos = m.end()

        if g['latexmacro'] is not None:
            node, pos = parse_reference_macro(text, m.start(), g['latexmacro'],
                                              lambda arg: parse_inline(arg, ref_map=ref_map))
            items.append(node or Text(content=g['latexmacro']))
        elif g['fnref'] is not None:
            key = '^' + unescape(g['fn_id']).lower()
            if key in ref_map:
                # The note's own definition is out of reach inside it, so a self-reference stays text
                inner_map = {k: v for k, v in ref_map.items() if k != key}
                items.append(Footnote(content=parse_inline(ref_map[key][0], ref_map=inner_map)))
            else:
                _scan_text(text, m.start(), m.end(), items)
        elif g['refimg'] is not None:
            label = unescape(g['ri_id'] or g['ri_alt']).lower().strip()
            if label in ref_map:
                url, title = ref_map[label]
                items.append(Image(src=url, alt=unescape(g['ri_alt']), title=title))
            else:
                _scan_text(text, m.start(), m.end(), items)  # undefined: literal text
        elif g['reflink'] is not None:
            label = unescape(g['rl_id'] or g['rl_text']).lower().strip()
            if label in ref_map:
                url, title = ref_map[label]
                items.append(Link(url=url, title=title,
                                  content=parse_inline(g['rl_text'], ref_map=ref_map, autolinks=False)))
            else:
                # Undefined reference (e.g. matrix[i][j]): literal text, not a link to "#"
                _scan_text(text, m.start(), m.end(), items)
        elif g['inlineimg'] is not None:
            ocr_text = base64.b64decode(g['ocr_b64']).decode('utf-8') if g['ocr_b64'] else None
            items.append(Image(src=_url(g, 'img_url'), alt=unescape(g['img_alt'] or ''),
                               title=_title(g['img_title']), extracted_text=ocr_text))
        elif g['linkedimg'] is not None:
            img = Image(src=_url(g, 'li_img_url'), alt=unescape(g['li_alt'] or ''), title=_title(g['li_img_title']))
            items.append(Link(url=_url(g, 'li_link_url'), title=_title(g['li_link_title']), content=[img]))
        elif g['inlinelink'] is not None:
            items.append(Link(url=_url(g, 'link_url'), title=_title(g['link_title']),
                              content=parse_inline(g['link_text'], ref_map=ref_map, autolinks=False)))
        elif g['shortcut'] is not None:
            label = unescape(g['sc_text']).lower().strip()
            if label in ref_map:
                url, title = ref_map[label]
                items.append(Link(url=url, title=title,
                                  content=parse_inline(g['sc_text'], ref_map=ref_map, autolinks=False)))
            else:
                # Only the bracket is literal: what follows may hold inline syntax
                pos = m.start() + 1
                _scan_text(text, m.start(), pos, items)
        elif g['codeinline'] is not None:
            code = g['code_content']
            if len(code) > 2 and code.startswith(' ') and code.endswith(' ') and code.strip():
                code = code[1:-1]
            items.append(CodeInline(code=_restore_raw(code)))
        elif g['mathinline'] is not None:
            items.append(Equation(code=_restore_raw(g['math_content']), inline=True))
        elif g['autolink'] is not None:
            url = _restore_raw(g['auto_url'])  # backslash escapes do not apply inside an autolink
            items.append(Link(url=url, content=[Text(content=url)]))
        elif g['automail'] is not None:
            address = _restore_raw(g['mail'])
            items.append(Link(url='mailto:' + address, content=[Text(content=address)]))
        elif g['bareurl'] is not None:
            shown = trim_bare_url(g['bareurl'])
            pos = m.start() + len(shown)
            shown = unescape(shown)
            if re.match(r'(?:https?://|www\.)\w', shown):
                items.append(Link(url=shown if '://' in shown else 'http://' + shown, content=[Text(content=shown)]))
            else:
                _scan_text(text, m.start(), pos, items)
        elif g['linebreak'] is not None:
            items.append(LineBreak())
        elif g['anytag'] is not None:
            if g['anytag'][1:4].lower() == 'img':
                from .html_parser import parse_html
                items.extend(n for block in parse_html(g['anytag']).children for n in getattr(block, 'children', []))
        elif g['tag'].lower() == 'kbd':
            items.append(CodeInline(code=unescape(g['html_content'])))
        else:
            inner = parse_inline(g['html_content'], ref_map=ref_map, autolinks=autolinks)
            for item in inner:
                _style(item, *_HTML_STYLES[g['tag'].lower()])
            items.extend(inner)

    return _resolve_emphasis(items)
