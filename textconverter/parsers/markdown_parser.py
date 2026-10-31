from __future__ import annotations
import base64
import json
import re
from dataclasses import replace

from ..ast import (
    DESCRIPTION_END, DESCRIPTION_START, METADATA_FIELDS, BlockQuote, CodeBlock, Document, Equation, Heading,
    HorizontalRule, Image, InlineElement, Label, LineBreak, ListBlock, ListItem, Node, Paragraph, Table, TableCell,
    TableRow, Text, abstract_from, walk,
)
from ..logger import log_warning
from ._markdown_inline import parse_inline, protect_escapes, unescape
from ._math import split_math_env

# List item markers: Markdown's own plus the bullets PDF text extraction produces.
_BULLET = r'[-*+•●○■]'
_LIST_ITEM = re.compile(rf'^\s*(?:{_BULLET}|\d+\.)\s+')
# A table's delimiter row: | --- | :--: | ...
TABLE_SEPARATOR = re.compile(r'^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$')
# A fenced code block (``` or ~~~); the closing fence is the same character, at least as long.
_FENCED_CODE = re.compile(
    r'^(?P<indent>[ \t]*)(?P<fence>(?P<fc>[`~])(?P=fc){2,})[ \t]*(?P<lang>[^\n`]*)\n'
    r'(?P<code>.*?)^[ \t]*(?P=fence)(?P=fc)*[ \t]*$',
    re.MULTILINE | re.DOTALL,
)
_FENCE_LINE = re.compile(r'^(`{3,}|~{3,})')
# A fence that nothing closes: its code runs to the end of the document (read after the closed ones).
_UNCLOSED_FENCE = re.compile(
    r'^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})[ \t]*(?P<lang>[^\n`]*)\n(?P<code>.*)\Z', re.MULTILINE | re.DOTALL)
# A task list item's checkbox: "[ ] text" or "[x] text".
_TASK = re.compile(r'^\[([ xX])\][ \t]+(.*)$', re.DOTALL)
_SETEXT_UNDERLINE = re.compile(r'^(?:=+|-+)[ \t]*$')
# YAML front matter at the very start: only "key: value" lines between "---" lines.
_FRONT_MATTER = re.compile(r'\A---[ \t]*\n((?:[ \t]*(?:[A-Za-z_][\w-]*[ \t]*:.*)?\n)*?)(?:---|\.\.\.)[ \t]*(?:\n|\Z)')
# A GFM footnote definition and its indented continuation lines.
_FOOTNOTE_DEF = re.compile(r'^ {0,3}\[\^([^\]\s]+)\]:[ \t]*(.*(?:\n(?:[ \t]{2,}\S.*|[ \t]*$))*)', re.MULTILINE)
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
# An HTML comment, unless it is one of the placeholders above; a code span is matched only to keep it.
_HTML_COMMENT = re.compile(
    r'(?P<code>(?P<ticks>`+).+?(?P=ticks))'
    r'|(?P<lead>[ \t]*)<!--(?!CODEBLOCK:|MATHBLOCK:|DESCRIBED:|OCR:).*?-->(?P<trail>[ \t]*)', re.DOTALL)
# A block of HTML, which the HTML parser reads.
_HTML_BLOCK = re.compile(
    r'</?(?:address|article|aside|blockquote|body|center|details|dd|dialog|div|dl|dt|fieldset|figcaption|figure|'
    r'footer|form|h[1-6]|header|hr|html|img|li|main|nav|ol|p|pre|section|summary|table|tbody|td|tfoot|th|thead|tr|ul)'
    r'(?=[\s/>])', re.IGNORECASE)
_HARD_BREAK_END = re.compile(r'(?: {2,}|\t|(?<!\\)\\)$')
_CLOSING_HASHES = re.compile(r'(?:^|[ \t]+)#+[ \t]*$')
_AND = re.compile(r'[ \t]*\\and(?![a-zA-Z])[ \t]*')
_REF_DEF = re.compile(
    r'^ {0,3}\[([^\]]+)\]:\s+<?([^>\s]+?)>?'
    r'(?:\s+(?:"([^"]*)"|\x27([^\x27]*)\x27|\(([^)]*)\)))?\s*$',
    re.MULTILINE,
)


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
        return CodeBlock(code=payload['code'].strip('\n'), language=payload['lang'] or None)
    if kind == 'MATHBLOCK':
        code, env = split_math_env(payload['code'])
        return Equation(code=code, inline=False, env=env)
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
        fence_match = _FENCE_LINE.match(stripped)
        if fence is not None:
            new_lines.append(line)
            closing = fence_match and fence_match.group(1)[0] == fence[0]
            if closing and len(fence_match.group(1)) >= len(fence) and not stripped.strip(fence[0]).strip():
                fence = None
            continue
        if fence_match:
            fence = fence_match.group(1)

        is_heading = re.match(r'^#{1,6}\s+', stripped)
        is_list_item = _LIST_ITEM.match(line)
        is_hr = re.match(r'^[-*_]{3,}\s*$', stripped)
        is_blockquote = stripped.startswith(">")
        # "Title" over a line of "=" or "-" is a heading (setext), not a paragraph and a rule
        is_setext = (bool(_SETEXT_UNDERLINE.match(stripped)) and not after_heading
                     and bool(new_lines) and _is_text_line(new_lines[-1]))

        should_insert = False
        if new_lines and new_lines[-1].strip() and not is_setext:
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
        after_heading = bool(is_heading or is_setext)

    return '\n'.join(new_lines)


def _is_text_line(line: str) -> bool:
    """A line of paragraph text (what a setext underline can turn into a heading)."""
    stripped = line.strip()
    return bool(stripped) and not (
        re.match(r'^#{1,6}(\s|$)', stripped) or _LIST_ITEM.match(line) or stripped.startswith(('>', '|'))
        or _FENCE_LINE.match(stripped) or re.match(r'^[-*_=]{3,}\s*$', stripped)
        or line.startswith(('    ', '\t')))


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


def _item_line(line: str) -> tuple[str, bool]:
    """The text of a line of a list item and whether it ends in a hard break."""
    hard = bool(_HARD_BREAK_END.search(line))
    text = line.strip()
    return (text[:-1].rstrip() if hard and text.endswith('\\') else text), hard


def _parse_markdown_list(block_text: str, ref_map: dict | None = None) -> ListBlock:
    lines = block_text.split('\n')
    stack = []
    root_list_block = None
    hard_break = False  # the line before ended in one

    for line in lines:
        if not line.strip():
            continue

        m = re.match(rf'^(\s*)({_BULLET}|\d+\.)\s+(.*)$', line)
        if m:
            indent = len(m.group(1).replace('\t', '    '))
            ordered = m.group(2)[0].isdigit()
            start = int(m.group(2)[:-1]) if ordered else 1
            text, hard_break = _item_line(m.group(3))
            task = _TASK.match(text)
            if task:
                text = task.group(2)
            new_item = ListItem(children=[Paragraph(children=parse_inline(text, ref_map=ref_map))],
                                checked=(task.group(1) != ' ') if task else None)

            # Pop stack while top has strictly greater indent
            while stack and stack[-1]["indent"] > indent:
                stack.pop()

            if not stack:
                root_list_block = ListBlock(ordered=ordered, items=[new_item], start=start)
                stack.append({"indent": indent, "list_block": root_list_block, "list_item": new_item})
            elif stack[-1]["indent"] < indent:
                new_list = ListBlock(ordered=ordered, items=[new_item], start=start)
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
                text, next_break = _item_line(line)
                nodes = active_item.children[-1].children
                nodes.extend([LineBreak(), *parse_inline(text, ref_map=ref_map)] if hard_break
                             else parse_inline(' ' + text, ref_map=ref_map))
                hard_break = next_break
            else:
                active_item.children.append(Paragraph(children=parse_inline(line.strip(), ref_map=ref_map)))

    return root_list_block


def parse_markdown(
    text: str,
    code_parsing: bool = False,
    parent_ref_map: dict[str, tuple[str, str | None]] | None = None,
    indented_code: bool = True,
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
        indented_code: Read a block indented by four spaces as code; off for
            Markdown written by a program (PDF text, AI transcriptions), whose
            indentation says nothing.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    metadata = {}
    if parent_ref_map is None:  # front matter only opens a whole document
        text, metadata = _front_matter(text)
    text = smart_preprocess_markdown(text)

    ref_map: dict[str, tuple[str, str | None]] = dict(parent_ref_map or {})
    # GFM footnote definitions ([^id]: text) come out first: they look like reference definitions.
    # They share the reference map, under "^id", so nested parses inherit them too.
    for fm in _FOOTNOTE_DEF.finditer(text):
        ref_map['^' + fm.group(1).lower()] = (fm.group(2).strip(), None)
    text = _FOOTNOTE_DEF.sub('', text)

    # Collect and strip reference-style link/image definitions: [id]: <url> "title"
    for rm in _REF_DEF.finditer(text):
        label = rm.group(1).lower().strip()
        title = rm.group(3) or rm.group(4) or rm.group(5) or None
        ref_map[label] = (rm.group(2), title)
    text = _REF_DEF.sub('', text)

    # Described images come first: their description may hold code or math blocks.
    def _encode_described(m: re.Match) -> str:
        return _encode_placeholder('DESCRIBED', {
            'src': unescape(protect_escapes(m.group('src'))),
            'cat': unescape(protect_escapes(m.group('cat'))) if m.group('cat') else None,
            'desc': m.group('desc').strip(),
        })

    text = _DESCRIBED_IMAGE.sub(_encode_described, text)

    # Fenced code keeps its blank lines: encode it before splitting into blocks.
    def _encode_codeblock(m: re.Match) -> str:
        lines = m.group('code').split('\n')
        # The fence's own indentation is not part of the code
        indent = m.group('indent')
        if indent:
            lines = [line[len(indent):] if line.startswith(indent) else line.lstrip() for line in lines]
        return _encode_placeholder('CODEBLOCK', {"lang": m.group('lang').strip(), "code": '\n'.join(lines),
                                                 "attach": _continues_block(m)})

    text = _FENCED_CODE.sub(_encode_codeblock, text)
    if code_parsing:
        from ..code_detector import pre_process_markdown_code
        # Encode the code blocks the detector fences
        text = _FENCED_CODE.sub(_encode_codeblock, pre_process_markdown_code(text))

    def _encode_unclosed(m: re.Match) -> str:
        log_warning("A code fence is never closed: the rest of the document is read as code.")
        return _encode_codeblock(m)

    text = _UNCLOSED_FENCE.sub(_encode_unclosed, text, count=1)

    text = _MATH_BLOCK.sub(lambda m: _encode_placeholder(
        'MATHBLOCK', {"code": m.group(1).strip(), "attach": _continues_block(m)}), text)
    text = _HTML_COMMENT.sub(_drop_comment, text)

    def _encode_picture_text(m: re.Match) -> str:
        b64_ocr = base64.b64encode(m.group(2).strip().encode('utf-8')).decode('utf-8')
        return f"{m.group(1)}<!--OCR:{b64_ocr}-->"

    text = _PICTURE_TEXT.sub(_encode_picture_text, text)

    doc = Document(**metadata)
    blocks = re.split(r'\n\s*\n', text.strip('\n'))
    indented: CodeBlock | None = None  # the code block an indented block continues

    for raw in blocks:
        block = raw.strip()
        if not block:
            continue
        after_list = bool(doc.children) and isinstance(doc.children[-1], ListBlock)
        previous_code, indented = indented, None

        # 1. Code, math and described-image blocks
        placeholder = _decode_placeholder(block)
        if placeholder:
            node = _placeholder_node(*placeholder)
            # A code or math block indented under a list item, or right below it, belongs to it
            if placeholder[0] != 'DESCRIBED' and after_list and placeholder[1].get('attach', True):
                doc.children[-1].items[-1].children.append(node)
            else:
                doc.children.append(node)
            continue

        # An indented block after a list continues its last item (a second paragraph, a nested list)
        if after_list and _indent_width(raw) >= 2:
            inner = parse_markdown(_dedent(raw), code_parsing=code_parsing, parent_ref_map=ref_map,
                                   indented_code=indented_code)
            doc.children[-1].items[-1].children.extend(inner.children)
            continue

        # Four spaces of indentation: code, with what a blank line separates from the block before
        if indented_code and _indent_width(raw) >= 4:
            code = _indented_code(raw)
            if previous_code is not None:
                previous_code.code += '\n\n' + code
                indented = previous_code
            else:
                indented = CodeBlock(code=code)
                doc.children.append(indented)
            continue

        if _HTML_BLOCK.match(block):
            from .html_parser import parse_html
            doc.children.extend(parse_html(block).children)
            continue

        # 2. Headings (the preprocess put any following text in a block of its own)
        m_heading = re.match(r'^(#{1,6})\s+(.*)$', block)
        if m_heading:
            title = _CLOSING_HASHES.sub('', m_heading.group(2).strip())
            doc.children.append(Heading(level=len(m_heading.group(1)), children=parse_inline(title, ref_map=ref_map)))
            continue
        lines = block.split('\n')
        if len(lines) > 1 and _SETEXT_UNDERLINE.match(lines[-1].strip()) and _is_text_line(lines[-2]):
            level = 1 if lines[-1].strip()[0] == '=' else 2
            doc.children.append(Heading(level=level, children=parse_inline('\n'.join(lines[:-1]), ref_map=ref_map)))
            continue

        # 3. Horizontal Rule
        if re.match(r'^[-*_]{3,}\s*$', block):
            doc.children.append(HorizontalRule())
            continue

        # 4. Blockquote
        if block.startswith(">"):
            doc.children.append(_parse_blockquote(block, code_parsing, ref_map, indented_code))
            continue

        # 5. Lists (Ordered and Unordered)
        if _LIST_ITEM.match(block):
            lb = _parse_markdown_list(block, ref_map=ref_map)
            if lb:
                if doc.children and _continues_list(doc.children[-1], lb):
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

    _attach_captions(doc.children)
    return doc


def _drop_comment(m: re.Match) -> str:
    """Nothing for an HTML comment (one space if there was one on each side); a code span stays."""
    if m.group('code') is not None:
        return m.group(0)
    return ' ' if m.group('lead') and m.group('trail') else m.group('lead') or m.group('trail')


def _indented_code(block: str) -> str:
    """The code of a block indented by four spaces or a tab."""
    lines = [line.replace('\t', '    ', 1) if line.startswith('\t') else line for line in block.split('\n')]
    return '\n'.join(line[4:] if line.startswith('    ') else line.lstrip() for line in lines)


def _continues_list(previous: Node, new: ListBlock) -> bool:
    """Whether a list after a blank line goes on from the list before it.

    An ordered one does only if its number follows: that is the one way the
    text can show two lists in a row.
    """
    if not isinstance(previous, ListBlock) or previous.ordered != new.ordered:
        return False
    return not new.ordered or new.start == previous.start + len(previous.items)


def _continues_block(m: re.Match) -> bool:
    """Whether a fenced or math block matched at ``m`` is indented or right below a non-blank line."""
    before = m.string[:m.start()]
    line_start = before[before.rfind('\n') + 1:]
    if line_start or m.groupdict().get('indent'):  # indentation (or text) before it on its line
        return True
    previous = before[:-1].rsplit('\n', 1)[-1] if before.endswith('\n') else ''
    return bool(previous.strip())


def _indent_width(block: str) -> int:
    """The indentation of a block's first non-blank line (a tab counts as 4)."""
    first = next((line for line in block.split('\n') if line.strip()), '')
    return len(first.replace('\t', '    ')) - len(first.lstrip())


def _dedent(block: str) -> str:
    """The block without the indentation common to its non-blank lines."""
    lines = [line.replace('\t', '    ') for line in block.split('\n')]
    width = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
    return '\n'.join(line[width:] for line in lines).strip('\n')


def _yaml_scalar(value: str) -> str:
    """A YAML scalar's text: quoted strings are unquoted and unescaped."""
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return re.sub(r'\\(["\\n])', lambda m: '\n' if m.group(1) == 'n' else m.group(1), value[1:-1])
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _front_matter(text: str) -> tuple[str, dict[str, list[InlineElement]]]:
    """Split a YAML front matter block off ``text``; return the rest and the metadata it sets.

    Only ``title``, ``author`` and ``date`` are read (their values are inline
    Markdown); other keys are reported and ignored.
    """
    m = _FRONT_MATTER.match(text)
    if not m:
        return text, {}
    fields: dict[str, str] = {}
    for line in m.group(1).split('\n'):
        if line.strip():
            key, _, value = line.partition(':')
            fields[key.strip().lower()] = _yaml_scalar(value.strip())
    unknown = sorted(set(fields) - set(METADATA_FIELDS))
    if unknown:
        log_warning(f"Ignoring unknown front matter keys: {', '.join(unknown)}")
    metadata = {k: parse_inline(v) for k, v in fields.items() if k in METADATA_FIELDS and v}
    if 'author' in metadata:
        metadata['author'] = _split_authors(metadata['author'])
    return text[m.end():], metadata


def _split_authors(nodes: list[InlineElement]) -> list[InlineElement]:
    """Turn the ``\\and`` the renderer writes between two authors into its line break."""
    out: list[InlineElement] = []
    for node in nodes:
        if not isinstance(node, Text):
            out.append(node)
            continue
        first, *rest = _AND.split(node.content)
        out.extend([replace(node, content=first)] if first else [])
        for part in rest:
            out.append(LineBreak(author_separator=True))
            out.extend([replace(node, content=part)] if part else [])
    return out


def _caption_text(block: Node, prefix: str) -> list[InlineElement] | None:
    """The caption a ``Table: ...`` / ``Figure: ...`` paragraph holds, or None."""
    if not isinstance(block, Paragraph) or not block.children:
        return None
    first = block.children[0]
    if not (isinstance(first, Text) and first.content.startswith(prefix)
            and not (first.bold or first.italic or first.strikethrough)):
        return None
    rest = first.content[len(prefix):]
    return ([replace(first, content=rest)] if rest else []) + block.children[1:]


def _set_caption(node: Table | Image, caption: list[InlineElement]) -> None:
    """Give a table or image its caption; a ``\\label`` in it becomes the node's label."""
    labels = [n for n in caption if isinstance(n, Label)]
    node.caption = [n for n in caption if not isinstance(n, Label)]
    while node.caption and isinstance(node.caption[-1], Text) and not node.caption[-1].content.strip():
        node.caption.pop()
    if node.caption and isinstance(node.caption[-1], Text):
        node.caption[-1].content = node.caption[-1].content.rstrip()
    if labels:
        node.label = labels[-1].name


def _attach_captions(blocks: list[Node]) -> None:
    """Read ``Table: ...`` before a table and ``Figure: ...`` after an image's paragraph as captions."""
    out: list[Node] = []
    for block in blocks:
        previous = out[-1] if out else None
        figure_caption = _caption_text(block, "Figure: ")
        if figure_caption is not None and isinstance(previous, Paragraph):
            image = next((n for n in walk(previous) if isinstance(n, Image) and not n.caption and not n.label), None)
            if image is not None:
                _set_caption(image, figure_caption)
                continue
        if isinstance(block, Table) and not block.caption and previous is not None:
            table_caption = _caption_text(previous, "Table: ")
            if table_caption is not None:
                out.pop()
                _set_caption(block, table_caption)
        out.append(block)
    blocks[:] = out


def _parse_blockquote(block: str, code_parsing: bool, ref_map: dict, indented_code: bool = True):
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
    inner = parse_markdown(quote_text, code_parsing=code_parsing, parent_ref_map=ref_map, indented_code=indented_code)
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
        # An all-empty header row is how a table without header is written
        if any(_row_cells(lines[0])):
            table.headers = cells(lines[0])
        lines = lines[2:]
    table.rows = [TableRow(cells=cells(line)) for line in lines]
    return table
