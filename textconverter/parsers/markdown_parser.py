from __future__ import annotations
import base64
import json
import re

from ..ast import (
    DESCRIPTION_END, DESCRIPTION_START, BlockQuote, CodeBlock, CodeInline, Document, Equation,
    Heading, HorizontalRule, Image, InlineElement, LineBreak, Link, ListBlock, ListItem, Paragraph,
    Table, TableCell, TableRow, Text, abstract_from,
)
from ._latex_macros import REFERENCE_MACROS, parse_reference_macro

# List item markers: Markdown's own plus the bullets PDF text extraction produces.
_BULLET = r'[-*+•●○■]'
_LIST_ITEM = re.compile(rf'^\s*(?:{_BULLET}|\d+\.)\s+')
# A table's delimiter row: | --- | :--: | ...
TABLE_SEPARATOR = re.compile(r'^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$')
# A fenced code block; the closing fence is at least as long as the opening one.
_FENCED_CODE = re.compile(
    r'^[ \t]*(?P<fence>`{3,})[ \t]*(?P<lang>[^\n`]*)\n(?P<code>.*?)^[ \t]*(?P=fence)`*[ \t]*$',
    re.MULTILINE | re.DOTALL,
)
_MATH_BLOCK = re.compile(r'(?<!\\)\$\$(.*?)(?<!\\)\$\$', re.MULTILINE | re.DOTALL)
# Text extracted by pymupdf4llm from a vector image, written right after the image.
_PICTURE_TEXT = re.compile(
    r'(!\[.*?\]\(.*?\))\s*\*\*----- Start of picture text -----\*\*(.*?)\*\*----- End of picture text -----\*\*',
    re.DOTALL,
)
# A described image as the renderers write it (see images.lower_image_descriptions).
_DESCRIBED_IMAGE = re.compile(
    r'^\*\*\\?\[Image Reference: (?P<src>.*?)(?: - Class: (?P<cat>[\w-]+))?\\?\]\*\*[ \t]*\n'
    rf'\*\*\\?{re.escape(DESCRIPTION_START)}\*\*[ \t]*\n'
    rf'(?P<desc>.*?)\n[ \t]*\*\*\\?{re.escape(DESCRIPTION_END)}\*\*[ \t]*$',
    re.MULTILINE | re.DOTALL,
)
_PLACEHOLDER = re.compile(r'^<!--(CODEBLOCK|MATHBLOCK|DESCRIBED):([A-Za-z0-9+/=]+)-->$')
_REF_DEF = re.compile(
    r'^ {0,3}\[([^\]]+)\]:\s+<?([^>\s]+?)>?'
    r'(?:\s+(?:"([^"]*)"|\x27([^\x27]*)\x27|\(([^)]*)\)))?\s*$',
    re.MULTILINE,
)

# Backslash escapes: each escapable ASCII punctuation character stands in a
# private-use code point while inline syntax is matched, so "\*" or "\[" is
# never read as markup; the character comes back as plain text afterwards.
_PUNCTUATION = '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'
_ESCAPE_RE = re.compile(r'\\([!-/:-@\[-`{-~])')
_TO_SENTINEL = {c: chr(0xE000 + i) for i, c in enumerate(_PUNCTUATION)}
_FROM_SENTINEL = {v: k for k, v in _TO_SENTINEL.items()}
_SENTINEL_RE = re.compile('[' + ''.join(_FROM_SENTINEL) + ']')


def _protect_escapes(text: str) -> str:
    return _ESCAPE_RE.sub(lambda m: _TO_SENTINEL[m.group(1)], text)


def _unescape(text: str) -> str:
    """Escaped characters back as literal text."""
    return _SENTINEL_RE.sub(lambda m: _FROM_SENTINEL[m.group(0)], text)


def _restore_raw(text: str) -> str:
    """Escaped characters back with their backslash (code and math keep the source)."""
    return _SENTINEL_RE.sub(lambda m: '\\' + _FROM_SENTINEL[m.group(0)], text)


def _encode_placeholder(kind: str, payload: dict) -> str:
    """A block that stands for content the block splitter must not see inside."""
    data = base64.b64encode(json.dumps(payload).encode('utf-8')).decode('ascii')
    return f"\n\n<!--{kind}:{data}-->\n\n"


def _decode_placeholder(line: str) -> tuple[str, dict] | None:
    m = _PLACEHOLDER.match(line.strip())
    if not m:
        return None
    return m.group(1), json.loads(base64.b64decode(m.group(2)).decode('utf-8'))


def _placeholder_node(kind: str, payload: dict):
    if kind == 'CODEBLOCK':
        return CodeBlock(code=payload['code'].strip(), language=payload['lang'] or None)
    if kind == 'MATHBLOCK':
        return Equation(code=payload['code'], inline=False)
    image = Image(src=payload['src'], description=payload['desc'], category=payload['cat'])
    return Paragraph(children=[image])


def smart_preprocess_markdown(text: str) -> str:
    """Preprocess raw markdown to ensure structural block boundaries have empty lines.

    This resolves bugs where headings, lists, code blocks, or blockquotes immediately
    follow paragraphs or other blocks without a blank line (or text follows a
    heading), causing them to be grouped into single blocks by simple block splitters.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    new_lines: list[str] = []
    fence: str | None = None  # the opening fence while inside a code block
    after_heading = False

    for line in text.split('\n'):
        stripped = line.strip()
        fence_match = re.match(r'^(`{3,})', stripped)
        if fence is not None:
            new_lines.append(line)
            if fence_match and len(fence_match.group(1)) >= len(fence) and not stripped.strip('`').strip():
                fence = None
            continue
        if fence_match:
            fence = fence_match.group(1)

        is_heading = re.match(r'^#{1,6}\s+', stripped)
        is_list_item = _LIST_ITEM.match(line)
        is_hr = re.match(r'^[-*_]{3,}\s*$', stripped)
        is_blockquote = stripped.startswith(">")

        should_insert = False
        if new_lines and new_lines[-1].strip():
            prev_line = new_lines[-1]
            if after_heading or is_heading or is_hr:
                should_insert = True
            elif fence_match:
                should_insert = not _LIST_ITEM.match(prev_line)
            elif is_blockquote:
                should_insert = not prev_line.strip().startswith(">")
            elif is_list_item:
                # Unless it continues a list (or an item's continuation line)
                prev_is_continuation = prev_line.startswith((" ", "\t"))
                should_insert = not (_LIST_ITEM.match(prev_line) or prev_is_continuation)
        if should_insert:
            new_lines.append("")
        new_lines.append(line)
        after_heading = bool(is_heading)

    return '\n'.join(new_lines)


def _split_table_cells(line: str) -> list[str]:
    """Split a Markdown table row into raw cell strings.

    Splits only on pipes that are genuine column delimiters: a pipe inside a
    backtick code span, or one escaped as ``\\|``, is kept as literal cell text
    (the backslash before an escaped pipe is dropped). Outer-pipe trimming and
    ``.strip()`` are left to the caller, so for a line with no backslash and no
    backtick this returns exactly what ``line.split('|')`` would.
    """
    cells: list[str] = []
    buf: list[str] = []
    in_code = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == '\\' and i + 1 < n and line[i + 1] == '|':
            buf.append('|')
            i += 2
            continue
        if ch == '`':
            in_code = not in_code
            buf.append(ch)
        elif ch == '|' and not in_code:
            cells.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    cells.append(''.join(buf))
    return cells


def _row_cells(line: str) -> list[str]:
    """The stripped cells of a table row; empty cells are kept, the outer pipes dropped."""
    cells = _split_table_cells(line)
    if line.strip().startswith('|'):
        cells = cells[1:]
    if line.strip().endswith('|'):
        cells = cells[:-1]
    return [c.strip() for c in cells]


def _parse_markdown_list(block_text: str, ref_map: dict | None = None) -> ListBlock:
    lines = block_text.split('\n')
    stack = []
    root_list_block = None

    for line in lines:
        if not line.strip():
            continue

        m = re.match(rf'^(\s*)({_BULLET}|\d+\.)\s+(.*)$', line)
        if m:
            indent = len(m.group(1).replace('\t', '    '))
            ordered = m.group(2)[0].isdigit()
            new_item = ListItem(children=[Paragraph(children=parse_inline(m.group(3).strip(), ref_map=ref_map))])

            # Pop stack while top has strictly greater indent
            while stack and stack[-1]["indent"] > indent:
                stack.pop()

            if not stack:
                root_list_block = ListBlock(ordered=ordered, items=[new_item])
                stack.append({"indent": indent, "list_block": root_list_block, "list_item": new_item})
            elif stack[-1]["indent"] < indent:
                new_list = ListBlock(ordered=ordered, items=[new_item])
                stack[-1]["list_item"].children.append(new_list)
                stack.append({"indent": indent, "list_block": new_list, "list_item": new_item})
            else:
                stack[-1]["list_block"].items.append(new_item)
                stack[-1]["list_item"] = new_item
        elif stack:
            active_item = stack[-1]['list_item']
            placeholder = _decode_placeholder(line)
            if placeholder:
                # A code/math block that was inside the list item
                active_item.children.append(_placeholder_node(*placeholder))
            elif active_item.children and isinstance(active_item.children[-1], Paragraph):
                # Continuation line: append to the item's last paragraph
                active_item.children[-1].children.extend(parse_inline(' ' + line.strip(), ref_map=ref_map))
            else:
                active_item.children.append(Paragraph(children=parse_inline(line.strip(), ref_map=ref_map)))

    return root_list_block


def parse_markdown(
    text: str,
    code_parsing: bool = False,
    parent_ref_map: dict[str, tuple[str, str | None]] | None = None,
) -> Document:
    """Parses markdown text into an AST Document.

    Args:
        text: The markdown source to parse.
        code_parsing: If True, enables heuristic code-block detection.
        parent_ref_map: Reference-style link/image definitions inherited from
            an enclosing document (used internally when a blockquote's content
            is re-parsed recursively, so references defined outside the
            blockquote still resolve correctly). Local definitions found in
            ``text`` take precedence over inherited ones with the same label.
    """
    text = smart_preprocess_markdown(text)

    # Collect and strip reference-style link/image definitions: [id]: <url> "title"
    ref_map: dict[str, tuple[str, str | None]] = dict(parent_ref_map or {})
    for rm in _REF_DEF.finditer(text):
        label = rm.group(1).lower().strip()
        title = rm.group(3) or rm.group(4) or rm.group(5) or None
        ref_map[label] = (rm.group(2), title)
    text = _REF_DEF.sub('', text)

    # Described images come first: their description may hold code or math blocks.
    def _encode_described(m: re.Match) -> str:
        return _encode_placeholder('DESCRIBED', {
            'src': _unescape(_protect_escapes(m.group('src'))),
            'cat': _unescape(_protect_escapes(m.group('cat'))) if m.group('cat') else None,
            'desc': m.group('desc').strip(),
        })

    text = _DESCRIBED_IMAGE.sub(_encode_described, text)

    # Fenced code keeps its blank lines: encode it before splitting into blocks.
    def _encode_codeblock(m: re.Match) -> str:
        lines = m.group('code').split('\n')
        # Strip the indentation common to the code lines
        indent = next((line[:len(line) - len(line.lstrip())] for line in lines if line.strip()), "")
        if indent:
            lines = [line[len(indent):] if line.startswith(indent) else line for line in lines]
        return _encode_placeholder('CODEBLOCK', {"lang": m.group('lang').strip(), "code": '\n'.join(lines)})

    text = _FENCED_CODE.sub(_encode_codeblock, text)
    if code_parsing:
        from ..code_detector import pre_process_markdown_code
        # Encode the code blocks the detector fences
        text = _FENCED_CODE.sub(_encode_codeblock, pre_process_markdown_code(text))

    text = _MATH_BLOCK.sub(lambda m: _encode_placeholder('MATHBLOCK', {"code": m.group(1).strip()}), text)

    def _encode_picture_text(m: re.Match) -> str:
        b64_ocr = base64.b64encode(m.group(2).strip().encode('utf-8')).decode('utf-8')
        return f"{m.group(1)}<!--OCR:{b64_ocr}-->"

    text = _PICTURE_TEXT.sub(_encode_picture_text, text)

    doc = Document()
    blocks = re.split(r'\n\s*\n', text.strip())

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # 1. Code, math and described-image blocks
        placeholder = _decode_placeholder(block)
        if placeholder:
            node = _placeholder_node(*placeholder)
            # A code or math block right after a list belongs to its last item
            if placeholder[0] != 'DESCRIBED' and doc.children and isinstance(doc.children[-1], ListBlock):
                doc.children[-1].items[-1].children.append(node)
            else:
                doc.children.append(node)
            continue

        # 2. Headings (the preprocess put any following text in a block of its own)
        m_heading = re.match(r'^(#{1,6})\s+(.*)$', block)
        if m_heading:
            doc.children.append(Heading(level=len(m_heading.group(1)),
                                        children=parse_inline(m_heading.group(2).strip(), ref_map=ref_map)))
            continue

        # 3. Horizontal Rule
        if re.match(r'^[-*_]{3,}\s*$', block):
            doc.children.append(HorizontalRule())
            continue

        # 4. Blockquote
        if block.startswith(">"):
            doc.children.append(_parse_blockquote(block, code_parsing, ref_map))
            continue

        # 5. Lists (Ordered and Unordered)
        if _LIST_ITEM.match(block):
            lb = _parse_markdown_list(block, ref_map=ref_map)
            if lb:
                if (doc.children and isinstance(doc.children[-1], ListBlock)
                        and doc.children[-1].ordered == lb.ordered):
                    doc.children[-1].items.extend(lb.items)
                else:
                    doc.children.append(lb)
            continue

        # 6. Tables
        table = _parse_table(block, ref_map)
        if table is not None:
            doc.children.append(table)
            continue

        # Fallback: Paragraph
        doc.children.append(Paragraph(children=parse_inline(block, ref_map=ref_map)))

    return doc


def _parse_blockquote(block: str, code_parsing: bool, ref_map: dict):
    """A ``>`` block: a block quote, a GitHub alert, or an abstract."""
    cleaned_lines = []
    for line in block.split('\n'):
        if line.strip().startswith(">"):
            content = line.lstrip()[1:]
            cleaned_lines.append(content[1:] if content.startswith(" ") else content)
        else:
            cleaned_lines.append(line)  # Lazy continuation line
    quote_text = '\n'.join(cleaned_lines).strip()

    # Detect callouts like [!IMPORTANT]
    alert_type = None
    m_alert = re.match(r'^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$', quote_text,
                       flags=re.IGNORECASE | re.DOTALL)
    if m_alert:
        alert_type = m_alert.group(1).upper()
        quote_text = m_alert.group(2).strip()

    # Recursive parse to support nested elements; inherit the outer
    # document's reference-style link/image definitions so that
    # references defined outside the blockquote still resolve.
    inner = parse_markdown(quote_text, code_parsing=code_parsing, parent_ref_map=ref_map)
    return abstract_from(inner.children) or BlockQuote(children=inner.children, alert_type=alert_type)


def _parse_table(block: str, ref_map: dict) -> Table | None:
    """A table block (with a delimiter row, or with every line between pipes), else None."""
    if '|' not in block or '\n' not in block:
        return None
    lines = block.split('\n')
    has_separator = '|' in lines[0] and bool(TABLE_SEPARATOR.match(lines[1]))
    is_strict_table = all(line.strip().startswith('|') and line.strip().endswith('|') for line in lines)
    if not (has_separator or is_strict_table):
        return None

    def cells(line: str) -> list[TableCell]:
        return [TableCell(children=parse_inline(c, ref_map=ref_map)) for c in _row_cells(line)]

    table = Table()
    if has_separator:
        table.headers = cells(lines[0])
        lines = lines[2:]
    table.rows = [TableRow(cells=cells(line)) for line in lines]
    return table


_EMPHASIS = (
    ('strike', re.compile(r'~~(?=\S)(.+?)(?<=\S)~~', re.DOTALL)),
    ('bold', re.compile(r'\*\*(.*?)\*\*|(?<!\w)__(.*?)__(?!\w)', re.DOTALL)),
    # An underscore inside a word (snake_case) is not emphasis
    ('italic', re.compile(r'\*(.*?)\*|(?<!\w)_(.+?)_(?!\w)', re.DOTALL)),
)


def _parse_formatting(
    text: str,
    fmt: dict[str, bool] | None = None,
    store: dict[str, tuple[str, str]] | None = None,
) -> list[InlineElement]:
    """Bold, italic and strikethrough runs of plain text (no links, code or math left).

    The content of a run is parsed again, so ``**_x_**`` is bold and italic.
    ``store`` maps the placeholders that stand for runs to their (tag, content);
    it is shared by the recursive calls, since a run may enclose another's placeholder.
    """
    fmt = fmt or {'bold': False, 'italic': False, 'strike': False}
    store = {} if store is None else store

    def keep(tag: str):
        def replace(m: re.Match) -> str:
            key = f"@@{tag[0].upper()}{len(store)}@@"
            store[key] = (tag, next((g for g in m.groups() if g is not None), ""))
            return key
        return replace

    for tag, pattern in _EMPHASIS:
        text = pattern.sub(keep(tag), text)

    res: list[InlineElement] = []
    for p in re.split(r'(@@[BIS]\d+@@)', text):
        if not p:
            continue
        if p in store:
            tag, inner = store[p]
            res.extend(_parse_formatting(inner, {**fmt, tag: True}, store))
        else:
            res.append(Text(content=_unescape(p), bold=fmt['bold'], italic=fmt['italic'],
                            strikethrough=fmt['strike']))
    return res


def _url_pattern(name: str) -> str:
    """A link destination: ``<...>`` (may hold spaces), or a URL with balanced parentheses."""
    return rf'(?:<(?P<{name}_b>[^<>\n]*)>|(?P<{name}>(?:[^\s()]|\([^\s()]*\))*))'


_INLINE = re.compile(
    # Footnotes, citations, cross-references (kept as LaTeX macros)
    rf'(?P<latexmacro>\\(?:{"|".join(REFERENCE_MACROS)})\*?(?![a-zA-Z]))|'
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
    # Code span: as many backticks to close as to open
    r'(?P<codeinline>(?P<ticks>`+)(?P<code_content>.+?)(?<!`)(?P=ticks)(?!`))|'
    r'(?P<mathinline>(?<!\\)\$(?!\s)(?P<math_content>[^$]+?)(?<!\s)(?<!\\)\$)|'
    r'(?P<linebreak><br\s*/?>)'
)


def _url(g: dict, name: str) -> str:
    return _unescape(g[f'{name}_b'] if g[f'{name}_b'] is not None else g[name] or '')


def parse_inline(text: str, ref_map: dict | None = None) -> list[InlineElement]:
    """Parses inline markdown like bold, italic, links, images, code.

    Backslash escapes (``\\*``, ``\\[``, ...) make the character literal.

    Args:
        text: The inline markdown string to parse.
        ref_map: Optional dict mapping lowercase reference labels to (url, title) tuples,
                 used to resolve reference-style links and images.
    """
    # A hard break is just the line break: drop its trailing spaces (or backslash)
    text = re.sub(r'(?:[ \t]{2,}|[ \t]*\\)\n', '\n', text)
    text = _protect_escapes(text)
    ref_map = ref_map or {}
    elements: list[InlineElement] = []

    pos = 0
    while pos < len(text):
        m = _INLINE.search(text, pos)
        if not m:
            elements.extend(_parse_formatting(text[pos:]))
            break
        if m.start() > pos:
            elements.extend(_parse_formatting(text[pos:m.start()]))
        g = m.groupdict()

        if g['latexmacro'] is not None:
            node, pos = parse_reference_macro(text, m.start(), g['latexmacro'],
                                              lambda arg: parse_inline(arg, ref_map=ref_map))
            elements.append(node or Text(content=g['latexmacro']))
            continue

        if g['refimg'] is not None:
            label = _unescape(g['ri_id'] or g['ri_alt']).lower().strip()
            if label in ref_map:
                url, title = ref_map[label]
                elements.append(Image(src=url, alt=_unescape(g['ri_alt']), title=title))
            else:
                elements.extend(_parse_formatting(g['refimg']))  # undefined: literal text
        elif g['reflink'] is not None:
            label = _unescape(g['rl_id'] or g['rl_text']).lower().strip()
            if label in ref_map:
                url, title = ref_map[label]
                elements.append(Link(url=url, title=title, content=parse_inline(g['rl_text'], ref_map=ref_map)))
            else:
                # Undefined reference (e.g. matrix[i][j]): literal text, not a link to "#"
                elements.extend(_parse_formatting(g['reflink']))
        elif g['inlineimg'] is not None:
            ocr_text = base64.b64decode(g['ocr_b64']).decode('utf-8') if g['ocr_b64'] else None
            elements.append(Image(src=_url(g, 'img_url'), alt=_unescape(g['img_alt'] or ''),
                                  title=g['img_title'], extracted_text=ocr_text))
        elif g['linkedimg'] is not None:
            img = Image(src=_url(g, 'li_img_url'), alt=_unescape(g['li_alt'] or ''), title=g['li_img_title'])
            elements.append(Link(url=_url(g, 'li_link_url'), title=g['li_link_title'], content=[img]))
        elif g['inlinelink'] is not None:
            elements.append(Link(url=_url(g, 'link_url'), title=g['link_title'],
                                 content=parse_inline(g['link_text'], ref_map=ref_map)))
        elif g['codeinline'] is not None:
            code = g['code_content']
            if len(code) > 2 and code.startswith(' ') and code.endswith(' ') and code.strip():
                code = code[1:-1]
            elements.append(CodeInline(code=_restore_raw(code)))
        elif g['mathinline'] is not None:
            elements.append(Equation(code=_restore_raw(g['math_content']), inline=True))
        elif g['linebreak'] is not None:
            elements.append(LineBreak())

        pos = m.end()

    return elements
