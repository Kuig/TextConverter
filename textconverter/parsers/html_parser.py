from __future__ import annotations
import html
import re
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Sequence
from ..ast import (
    Abstract, BlockQuote, Citation, CodeBlock, CodeInline, Document, Equation, Footnote, Heading,
    HorizontalRule, Image, Label, LineBreak, Link, ListBlock, ListItem, Node, Paragraph, Reference,
    Table, TableCell, TableRow, Text, abstract_from, child_lists, walk,
)
from ._latex_macros import REFERENCE_MACRO, lift_macros, parse_reference_macro
from ._math import split_math_env, strip_displaystyle, unwrap_math

if TYPE_CHECKING:
    from ..site_profiles.base import SiteProfile

_INLINE_TAGS = frozenset([
    'a', 'b', 'strong', 'i', 'em', 'span', 'code', 'img', 'br', 'sub', 'sup',
    'small', 'mark', 'ins', 'del', 'cite', 'dfn', 'kbd', 'samp', 'var', 'q',
    'time', 'ruby', 'rt', 'rp', 'data', 'abbr', 's', 'strike', 'u', 'font', 'big', 'tt'
])
_VOID = frozenset([
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr'
])
# Block tags that end an open paragraph.
_PARAGRAPH_CLOSERS = frozenset([
    'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'table', 'tr', 'td', 'th',
    'pre', 'blockquote', 'hr',
])


@dataclass
class _CaptionHolder(Node):
    """The content of a ``<caption>`` or ``<figcaption>`` while it is read."""
    children: list[Node] = field(default_factory=list)


@dataclass
class _RefHolder(Node):
    """The raw text of a ``<span class="tc-ref">`` (a citation, reference or label macro)."""
    raw: str = ""


# End tag -> AST node types it closes.
_NODE_TAGS: dict[str, tuple[type, ...]] = {
    **{f'h{i}': (Heading,) for i in range(1, 7)},
    'p': (Paragraph, Heading), 'ul': (ListBlock,), 'ol': (ListBlock,), 'li': (ListItem,),
    'table': (Table,), 'tr': (TableRow,), 'td': (TableCell,), 'th': (TableCell,),
    'a': (Link,), 'pre': (CodeBlock,), 'code': (CodeInline,), 'blockquote': (BlockQuote,),
    'caption': (_CaptionHolder,), 'figcaption': (_CaptionHolder,),
}
# HTML whitespace (not U+00A0, which is meant to stay).
_WHITESPACE = re.compile(r'[ \t\n\r\f]+')
# Inline nodes: an inline node reaching a block container goes into a paragraph.
_INLINE_NODES = (Text, Link, Image, CodeInline, LineBreak, Equation, Footnote, Citation, Reference, Label)
# The classes TextConverter's HTML output marks its own constructs with.
_META_CLASSES = {'tc-title': 'title', 'tc-author': 'author', 'tc-date': 'date'}

# Containers whose children are blocks: inline content gets an anonymous paragraph.
_BLOCK_CONTAINERS = (Document, BlockQuote, ListItem, _CaptionHolder)


@dataclass
class _MathCapture:
    """A formula being read.

    ``kind`` is ``"mathml"`` (``<math>``, TeX from its annotation),
    ``"script"`` (``<script type="math/tex">``) or ``"element"`` (an element
    with class ``math`` holding delimited TeX). ``text`` is the MathML's
    visible text, used when it has no TeX annotation.
    """
    kind: str
    inline: bool
    code: str = ""
    depth: int = 1
    in_annotation: bool = False
    text: str = ""


def _language(classes: list[str]) -> str | None:
    """The code language named by a ``language-x`` / ``lang-x`` class, if any."""
    for c in classes:
        for prefix in ('language-', 'lang-'):
            if c.startswith(prefix) and len(c) > len(prefix):
                return c[len(prefix):]
    return None


def _image_source(attrs: dict[str, str | None]) -> str:
    """The image URL, falling back to lazy-loading attributes when ``src`` is a placeholder."""
    src = attrs.get('src') or ''
    if not src or src.startswith('data:'):
        lazy = attrs.get('data-src') or attrs.get('data-lazy-src')
        srcset = attrs.get('srcset') or attrs.get('data-srcset')
        if lazy:
            return lazy
        if srcset:
            return srcset.split(',')[0].strip().split(' ')[0]
    return src


class ASTHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._active_anon_paragraph: Paragraph | None = None
        self.doc = Document()
        self.stack: list[Node] = [self.doc]
        self.in_pre = False
        self.in_thead = False
        self.ignore_data = False
        # Active vertical cell merges carried into following <tr>s:
        # list of {'col': <output column index>, 'rows_left': <int>}.
        self._rowspan_carry: list[dict] = []
        # id(cell) -> (colspan, rowspan), and the ids of <th> cells, until their row closes.
        self._spans: dict[int, tuple[int, int]] = {}
        self._header_cells: set[int] = set()
        # ids of block quotes titled "Abstract" by an alert-title div.
        self._abstract_quotes: set[int] = set()

        self.css_styles: dict[str, dict[str, bool]] = {}  # e.g. {'c10': {'bold': True}, ...}
        self.in_style_tag = False
        self.style_data = ""
        self.in_alert_title = False

        self._math: _MathCapture | None = None
        self.just_parsed_math = False

        self._title: str | None = None
        self._in_title = False
        self._generated_by_us = False

        # (tag, formatting) pairs: the formatting in force inside each open tag.
        self._formats: list[tuple[str, dict[str, bool]]] = []
        # One entry per open <span>: the node it opened (a reference or footnote), or None.
        self._open_spans: list[Node | None] = []
        # Open <figure>s: {'label': data-label, 'target': the last image or table inside}.
        self._figures: list[dict] = []
        # id(table) -> content found directly inside it, placed before the table.
        self._fostered: dict[int, list[Node]] = {}
        # id(node) -> Document metadata field, for TextConverter's title block.
        self._meta: dict[int, str] = {}

    @property
    def current_text_attrs(self) -> dict[str, bool]:
        return self._formats[-1][1] if self._formats else {
            'bold': False, 'italic': False, 'strikethrough': False, 'script': None}

    # ── Start tags ────────────────────────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        classes = (attr_dict.get('class') or '').split()

        if self._math is not None:
            if self._math.kind == 'mathml':
                if tag == 'annotation' and attr_dict.get('encoding') == 'application/x-tex':
                    self._math.in_annotation = True
            elif self._math.kind == 'element' and tag not in _VOID:
                self._math.depth += 1
            return

        if tag not in ('math', 'annotation', 'semantics', 'mrow', 'mi', 'mo', 'mn', 'msup', 'msub', 'img', 'span', 'div'):
            self.just_parsed_math = False

        if tag == 'math':
            self._math = _MathCapture('mathml', inline=attr_dict.get('display') != 'block')
            return
        if tag == 'title':
            self._in_title = True
            self._title = ""
            return
        if tag == 'meta':
            if (attr_dict.get('name') or '').lower() == 'generator' and attr_dict.get('content') == 'TextConverter':
                self._generated_by_us = True
            return

        if tag not in _INLINE_TAGS:
            self._active_anon_paragraph = None
        self._close_implied(tag)

        # A new block chunk inside a table cell (word-processor HTML wraps each
        # cell line in its own <div>/<p> with no whitespace between): keep the
        # words apart. Runs after the implicit block-close above so the cell,
        # not a just-closed inner paragraph, is on top of the stack.
        if tag not in _INLINE_TAGS and tag not in ('td', 'th', 'tr', 'table'):
            self._maybe_cell_separator()

        if tag == 'style':
            self.in_style_tag = True
            self.ignore_data = True
            return
        if tag == 'script':
            script_type = attr_dict.get('type') or ''
            if script_type.startswith('math/tex'):
                self._math = _MathCapture('script', inline='mode=display' not in script_type)
            else:
                self.ignore_data = True
            return
        if tag == 'div' and 'alert-title' in classes:
            self.in_alert_title = True
            self.ignore_data = True
            return
        if tag in ('span', 'div') and 'math' in classes:
            self._math = _MathCapture('element', inline='inline' in classes or tag == 'span')
            return

        if tag == 'img':
            self._image(attr_dict, classes)
            return
        if tag == 'br':
            self._append_to_parent(LineBreak(author_separator='tc-and' in classes))
            return
        if tag == 'hr':
            self._append_to_parent(HorizontalRule())
            return
        if tag == 'input':
            self._checkbox(attr_dict)
            return
        if tag in _VOID:
            return
        if tag == 'figure':
            self._figures.append({'label': attr_dict.get('data-label'), 'target': None})

        formats = dict(self.current_text_attrs)
        for c in classes:  # Google Docs styles by class
            formats.update(self.css_styles.get(c, {}))
        if tag in ('b', 'strong'):
            formats['bold'] = True
        elif tag in ('i', 'em'):
            formats['italic'] = True
        elif tag in ('s', 'del', 'strike'):
            formats['strikethrough'] = True
        elif tag in ('sup', 'sub'):
            formats['script'] = tag
        self._formats.append((tag, formats))

        node = self._node_for(tag, attr_dict, classes)
        if tag == 'span':
            self._open_spans.append(node)
        if node is not None:
            self.stack.append(node)

    def _checkbox(self, attr_dict: dict[str, str | None]) -> None:
        """A checkbox at the start of a list item makes it a task list item."""
        item = self.stack[-1]
        if (attr_dict.get('type') or '').lower() == 'checkbox' and isinstance(item, ListItem) \
                and not item.children and item.checked is None:
            item.checked = 'checked' in attr_dict

    def _node_for(self, tag: str, attr_dict: dict[str, str | None], classes: list[str]) -> Node | None:
        """The AST node a start tag opens, or None for tags that only set state or formatting."""
        node = self._block_node_for(tag, attr_dict, classes)
        meta = next((_META_CLASSES[c] for c in classes if c in _META_CLASSES), None)
        if meta and isinstance(node, (Heading, Paragraph)):
            self._meta[id(node)] = meta
        return node

    def _block_node_for(self, tag: str, attr_dict: dict[str, str | None], classes: list[str]) -> Node | None:
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            return Heading(level=int(tag[1]))
        if tag == 'p':
            return Heading(level=1) if 'title' in classes else Paragraph()
        if tag in ('ul', 'ol'):
            try:
                start = int(attr_dict.get('start') or 1)
            except ValueError:
                start = 1
            return ListBlock(ordered=(tag == 'ol'), start=start)
        if tag == 'li':
            return ListItem()
        if tag == 'table':
            self._rowspan_carry = []  # spans do not cross table boundaries
            return Table(label=attr_dict.get('data-label'))
        if tag in ('caption', 'figcaption'):
            return _CaptionHolder()
        if tag == 'thead':
            self.in_thead = True
            return None
        if tag == 'tr':
            return TableRow()
        if tag in ('td', 'th'):
            if isinstance(self.stack[-1], Table):
                self.stack.append(TableRow())  # a cell outside any row opens one, as in browsers
            cell = TableCell()

            def _span(name: str) -> int:
                try:
                    return max(1, int(attr_dict.get(name) or '1'))
                except ValueError:
                    return 1
            self._spans[id(cell)] = (_span('colspan'), _span('rowspan'))
            if tag == 'th':
                self._header_cells.add(id(cell))
            return cell
        if tag == 'pre':
            self.in_pre = True
            return CodeBlock(code="", language=_language(classes))
        if tag == 'code':
            if self.in_pre:
                block = self.stack[-1]
                if isinstance(block, CodeBlock) and not block.language:
                    block.language = _language(classes)
                return None
            return CodeInline(code="")
        if tag == 'a':
            href = attr_dict.get('href')
            # An anchor without href (<a name="top">) is only a target: its text stays plain
            return None if href is None else Link(url=href, title=attr_dict.get('title'))
        if tag == 'blockquote':
            alert_type = next((c[len('alert-'):].upper() for c in classes if c.startswith('alert-')), None)
            return BlockQuote(alert_type=alert_type)
        if tag == 'span' and 'tc-ref' in classes:
            return _RefHolder()
        if tag == 'span' and 'tc-footnote' in classes:
            return Footnote()
        return None

    def _image(self, attr_dict: dict[str, str | None], classes: list[str]) -> None:
        # Wikipedia's math fallback image: skip it after its MathML, else read its TeX alt text
        if any(c.startswith('mwe-math-fallback-image') for c in classes):
            if self.just_parsed_math:
                self.just_parsed_math = False
                return
            inline = 'mwe-math-fallback-image-inline' in classes
            self._append_to_parent(Equation(code=strip_displaystyle(attr_dict.get('alt') or ''), inline=inline))
            return
        image = Image(src=_image_source(attr_dict), alt=attr_dict.get('alt') or '', title=attr_dict.get('title'))
        if self._figures:
            self._figures[-1]['target'] = image
        self._append_to_parent(image)

    def _close_implied(self, tag: str) -> None:
        """Close the nodes a start tag ends implicitly (``<li>`` ends the open item, ...)."""
        if tag in _PARAGRAPH_CLOSERS:
            self._pop_while(Paragraph)
        if tag == 'li':
            self._pop_while(Paragraph, ListItem, stop_after=ListItem)
        elif tag == 'tr':
            self._pop_while(Paragraph, TableCell, TableRow, stop_after=TableRow)
        elif tag in ('td', 'th'):
            self._pop_while(Paragraph, TableCell, stop_after=TableCell)

    def _pop_while(self, *types: type, stop_after: type | None = None) -> None:
        """Close nodes on top of the stack while they are of ``types``; stop after one ``stop_after``."""
        while len(self.stack) > 1 and isinstance(self.stack[-1], types):
            node = self._finish(self.stack.pop())
            if stop_after is not None and isinstance(node, stop_after):
                return

    # ── End tags ──────────────────────────────────────────────────────────────

    def handle_endtag(self, tag: str) -> None:
        if self._math is not None:
            self._end_math(tag)
            return
        if tag == 'title':
            self._in_title = False
            return
        if tag in _VOID:
            return

        if tag not in _INLINE_TAGS:
            self._active_anon_paragraph = None
        if tag == 'style':
            self.in_style_tag = False
            self.ignore_data = False
            self.parse_css(self.style_data)
            self.style_data = ""
            return
        if tag == 'script':
            self.ignore_data = False
            return
        if tag == 'div' and self.in_alert_title:
            self.in_alert_title = False
            self.ignore_data = False
            return

        # Close the formatting this tag opened, ignoring a stray end tag
        for i in range(len(self._formats) - 1, -1, -1):
            if self._formats[i][0] == tag:
                del self._formats[i:]
                break

        if tag == 'thead':
            self.in_thead = False
            return
        if tag == 'pre':
            self.in_pre = False
        if tag == 'code' and self.in_pre:
            return
        if tag == 'span':
            opened = self._open_spans.pop() if self._open_spans else None
            if opened is not None and any(n is opened for n in self.stack):
                while self.stack[-1] is not opened:
                    self._finish(self.stack.pop())
                self._finish(self.stack.pop())
            return
        if tag == 'figure':
            if self._figures:
                figure = self._figures.pop()
                if figure['target'] is not None and figure['label']:
                    figure['target'].label = figure['label']
            return

        types = _NODE_TAGS.get(tag)
        if types is None:
            return
        # Close up to the nearest node this tag opened; a stray end tag closes nothing.
        for i in range(len(self.stack) - 1, 0, -1):
            if isinstance(self.stack[i], types):
                while len(self.stack) > i:
                    self._finish(self.stack.pop())
                return

    def _end_math(self, tag: str) -> None:
        math = self._math
        env = None
        if math.kind == 'mathml':
            if tag == 'annotation':
                math.in_annotation = False
                return
            if tag != 'math':
                return
            # Without a TeX annotation, the formula's visible text stands in for it
            code = strip_displaystyle(math.code) or _WHITESPACE.sub(' ', math.text).strip()
            self.just_parsed_math = True
            if not code:
                self._math = None
                return
        elif math.kind == 'script':
            if tag != 'script':
                return
            code = math.code.strip()
        else:
            if tag in _VOID:
                return
            math.depth -= 1
            if math.depth > 0:
                return
            code, env = split_math_env(math.code.strip())
            if env is None:
                code = strip_displaystyle(unwrap_math(code) or code)
        self._math = None
        self._append_to_parent(Equation(code=code, inline=math.inline, env=env))

    def _finish(self, node: Node) -> Node:
        """Attach a node just popped from the stack to its parent; return what was attached."""
        parent = self.stack[-1]
        if isinstance(node, TableRow):
            # Read before the spans add their blank cells. The AST has one header row: the others open the body
            header_row = isinstance(parent, Table) and not parent.headers and (self.in_thead or (
                not parent.rows and bool(node.cells) and all(id(c) in self._header_cells for c in node.cells)))
            self._resolve_row_spans(node)
            if header_row:
                parent.headers = node.cells
                return node
        elif isinstance(node, BlockQuote):
            if id(node) in self._abstract_quotes:
                node = Abstract(children=node.children)
            else:
                node = abstract_from(node.children) or node
        elif isinstance(node, _CaptionHolder):
            return self._finish_caption(node, parent)
        elif isinstance(node, _RefHolder):
            node = _reference_node(node.raw)
        elif isinstance(node, Footnote):
            _strip_footnote_frame(node.content)
        elif isinstance(node, Table):
            for block in self._fostered.pop(id(node), []):
                self._append_to_parent(block, force_parent=parent)
            if isinstance(parent, TableCell):
                parent.children.extend(_table_text(node))
                return node
            if self._figures:
                self._figures[-1]['target'] = node
        if id(node) in self._meta:
            self._trim_trailing_space(node.children)
            setattr(self.doc, self._meta.pop(id(node)), node.children)
            return node
        self._append_to_parent(node, force_parent=parent)
        return node

    def _finish_caption(self, holder: _CaptionHolder, parent: Node) -> Node:
        """Give a table or figure its caption; a caption with nothing to caption stays text."""
        content: list[Node] = []
        for block in holder.children:
            inline = block.children if isinstance(block, (Paragraph, Heading)) else [
                n for n in walk(block) if isinstance(n, Text)]
            if content and inline:
                content.append(Text(content=' '))
            content.extend(inline)
        self._trim_trailing_space(content)
        figure = self._figures[-1] if self._figures else None
        if isinstance(parent, Table):
            parent.caption = content
        elif figure is not None and figure['target'] is not None:
            figure['target'].caption = content
        else:
            for block in holder.children:
                self._append_to_parent(block, force_parent=parent)
        return holder

    # ── Text ──────────────────────────────────────────────────────────────────

    def handle_data(self, data: str) -> None:
        if self._math is not None:
            if self._math.kind != 'mathml' or self._math.in_annotation:
                self._math.code += data
            else:
                self._math.text += data
            return
        if self._in_title:
            self._title += data
            return
        if self.in_alert_title:
            if data.strip().lower() == "abstract" and isinstance(self.stack[-1], BlockQuote):
                self._abstract_quotes.add(id(self.stack[-1]))
            return
        if self.in_style_tag:
            self.style_data += data
        if self.ignore_data:
            return

        parent = self.stack[-1]
        if self.in_pre and isinstance(parent, CodeBlock):
            parent.code += data
            return
        if isinstance(parent, _RefHolder):
            parent.raw += data
            return
        if isinstance(parent, CodeInline):
            parent.code += data
            return

        if not self.in_pre:
            data = _WHITESPACE.sub(' ', data)
            target = self._inline_target()
            if target is None or not target or self._ends_with_space(target):
                data = data.lstrip()
            if not data:
                return
        fmt = self.current_text_attrs
        self._append_to_parent(Text(content=data, bold=fmt['bold'], italic=fmt['italic'],
                                    strikethrough=fmt.get('strikethrough', False),
                                    script=fmt.get('script')),
                               force_parent=parent)

    def _inline_target(self) -> list[Node] | None:
        """The list the next inline node goes into; None when it would start a new paragraph."""
        parent = self.stack[-1]
        if isinstance(parent, _BLOCK_CONTAINERS):
            anon = self._active_anon_paragraph
            if anon is not None and parent.children and parent.children[-1] is anon:
                return anon.children
            return None
        if isinstance(parent, (ListBlock, Table, TableRow)):
            return None
        lists = child_lists(parent)
        return lists[0] if lists else None

    @staticmethod
    def _trim_trailing_space(nodes: list[Node]) -> None:
        """Drop the space that collapsed whitespace leaves before a block's end."""
        while nodes and isinstance(nodes[-1], Text) and not nodes[-1].content.strip():
            nodes.pop()
        if nodes and isinstance(nodes[-1], Text):
            nodes[-1].content = nodes[-1].content.rstrip()

    @staticmethod
    def _ends_with_space(nodes: list[Node]) -> bool:
        last = nodes[-1]
        if isinstance(last, LineBreak):
            return True
        return isinstance(last, Text) and (not last.content or last.content[-1].isspace())

    def _maybe_cell_separator(self) -> None:
        """Insert a space between adjacent block chunks inside a table cell.

        Word-processor HTML frequently wraps each visual line of a cell in its
        own ``<div>``/``<p>`` with no whitespace between them; without this the
        renderers would glue the words together ("Enter" + "Service").
        """
        if not self.stack or not isinstance(self.stack[-1], TableCell):
            return
        cell = self.stack[-1]
        if cell.children and not self._ends_with_space(cell.children):
            cell.children.append(Text(content=" "))

    def _resolve_row_spans(self, row: TableRow) -> None:
        """Expand ``colspan``/``rowspan`` on a just-closed row into plain cells.

        ``colspan`` becomes N cells (content in the first, blanks after);
        ``rowspan`` records a carry so the following rows get a blank
        placeholder at the same column. The emitted AST is span-free, so the
        JSON schema is unchanged.
        """
        src = row.cells
        out: list[TableCell] = []
        i = 0
        # Cap iterations defensively against pathological span values.
        while len(out) < 4096:
            idx = len(out)
            carry = next((c for c in self._rowspan_carry
                          if c['col'] == idx and c['rows_left'] > 0), None)
            if carry is not None:
                out.append(TableCell())
                carry['rows_left'] -= 1
                continue
            if i >= len(src):
                if any(c['rows_left'] > 0 and c['col'] > idx for c in self._rowspan_carry):
                    out.append(TableCell())  # gap column before a later carry
                    continue
                break
            cell = src[i]
            i += 1
            colspan, rowspan = self._spans.pop(id(cell), (1, 1))
            for k in range(colspan):
                start_col = len(out)
                out.append(cell if k == 0 else TableCell())
                if rowspan > 1:
                    self._rowspan_carry.append({'col': start_col, 'rows_left': rowspan - 1})
        self._rowspan_carry = [c for c in self._rowspan_carry if c['rows_left'] > 0]
        row.cells = out

    def _append_to_parent(self, node: Node, force_parent: Node | None = None) -> None:
        parent = force_parent or self.stack[-1]

        # Wrap consecutive orphan inline elements in a Paragraph
        # when appending to block containers (Document, BlockQuote, ListItem)
        if isinstance(parent, _BLOCK_CONTAINERS) and isinstance(node, _INLINE_NODES) and not (
                isinstance(node, Equation) and not node.inline):
            anon = self._active_anon_paragraph
            if anon is None or not parent.children or parent.children[-1] is not anon:
                anon = Paragraph()
                parent.children.append(anon)
                self._active_anon_paragraph = anon
            anon.children.append(node)
            return

        if isinstance(parent, Table) and isinstance(node, TableRow):
            parent.rows.append(node)
        elif isinstance(parent, ListBlock) and isinstance(node, ListItem):
            parent.items.append(node)
        elif isinstance(parent, TableRow) and isinstance(node, TableCell):
            parent.cells.append(node)
        elif isinstance(parent, ListBlock):
            # Content directly inside a list belongs to its last item, as browsers show it
            if not parent.items:
                parent.items.append(ListItem())
            self._append_to_parent(node, force_parent=parent.items[-1])
        elif isinstance(parent, (Table, TableRow)):
            self._foster(node, parent)
        else:
            lists = child_lists(parent)
            if lists:
                lists[0].append(node)

    def _foster(self, node: Node, parent: Table | TableRow) -> None:
        """Keep content found directly in a table (not in a cell) for before the table, as browsers do."""
        table = parent if isinstance(parent, Table) else next(
            (n for n in reversed(self.stack) if isinstance(n, Table)), None)
        if table is None:  # a row outside any table: the content gets a cell of its own
            if isinstance(node, _INLINE_NODES):
                parent.cells.append(TableCell(children=[node]))
            elif isinstance(node, (Paragraph, Heading)):
                parent.cells.append(TableCell(children=node.children))
            return
        blocks = self._fostered.setdefault(id(table), [])
        if isinstance(node, _INLINE_NODES):
            if not blocks or not isinstance(blocks[-1], Paragraph):
                blocks.append(Paragraph())
            previous = blocks[-1].children
            if previous and isinstance(node, Text) and not self._ends_with_space(previous):
                node.content = ' ' + node.content  # separate runs of text, not one word
            previous.append(node)
        else:
            blocks.append(node)

    def parse_css(self, css_str: str) -> None:
        for match in re.finditer(r'\.([a-zA-Z0-9_-]+)\s*\{([^}]+)\}', css_str):
            cls_name = match.group(1)
            rules = match.group(2)
            style_dict = {}
            if 'font-weight:700' in rules or 'font-weight:bold' in rules:
                style_dict['bold'] = True
            if 'font-style:italic' in rules:
                style_dict['italic'] = True
            if style_dict:
                self.css_styles[cls_name] = style_dict

    def close(self) -> None:
        super().close()
        while len(self.stack) > 1:
            self._finish(self.stack.pop())
        for node in walk(self.doc):
            if isinstance(node, (Paragraph, Heading, TableCell)):
                self._trim_trailing_space(node.children)
        # The page title stands in for a missing main heading; TextConverter's
        # own output only carries the template's placeholder title.
        title = _WHITESPACE.sub(' ', self._title or '').strip()
        has_h1 = any(isinstance(n, Heading) and n.level == 1 for n in self.doc.children)
        if title and not has_h1 and not self._generated_by_us:
            self.doc.children.insert(0, Heading(level=1, children=[Text(content=title)]))
        if self._generated_by_us:
            # TextConverter 0.3.0 wrote reference macros as bare text
            for node in list(walk(self.doc)):
                for lst in child_lists(node):
                    lst[:] = lift_macros(lst)


def _table_text(table: Table) -> list[Node]:
    """A table inside a cell, which the AST cannot hold, as text: one line per row."""
    out: list[Node] = []
    for row in ([TableRow(cells=table.headers)] if table.headers else []) + table.rows:
        out.extend([Text(content="\n")] if out else [])
        for k, cell in enumerate(row.cells):
            out.extend([Text(content=" ")] if k else [])
            out.extend(cell.children)
    return out


def _reference_node(raw: str) -> Node:
    """The citation, reference or label a ``tc-ref`` span holds; its text when it is not one."""
    raw = raw.strip()
    m = REFERENCE_MACRO.match(raw)
    if m:
        node, end = parse_reference_macro(raw, 0, m.group(0), lambda arg: [Text(content=arg)])
        if node is not None and end == len(raw):
            return node
    return Text(content=raw)


def _strip_footnote_frame(content: list[Node]) -> None:
    """Drop the ``\\footnote{`` and ``}`` a ``tc-footnote`` span shows around its content."""
    if content and isinstance(content[0], Text) and content[0].content.lstrip().startswith('\\footnote{'):
        content[0].content = content[0].content.lstrip()[len('\\footnote{'):]
    if content and isinstance(content[-1], Text) and content[-1].content.rstrip().endswith('}'):
        content[-1].content = content[-1].content.rstrip()[:-1]
    content[:] = [n for n in content if not (isinstance(n, Text) and not n.content)]


_NOISE = frozenset(['script', 'style', 'nav', 'footer', 'header',
                    'aside', 'noscript', 'iframe', 'form', 'head'])
_SAFE_ATTRS = frozenset([
    'href', 'src', 'alt', 'title', 'class', 'id', 'role', 'encoding', 'display', 'colspan', 'rowspan',
    'data-src', 'data-lazy-src', 'srcset', 'data-srcset', 'data-label', 'start', 'type', 'checked',
])
# Opening tag -> (open tags it ends implicitly, tags that stop the search).
_IMPLIED_END: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    'li': (frozenset({'li'}), frozenset({'ul', 'ol'})),
    'dt': (frozenset({'dt', 'dd'}), frozenset({'dl'})),
    'dd': (frozenset({'dt', 'dd'}), frozenset({'dl'})),
    'tr': (frozenset({'tr', 'td', 'th'}), frozenset({'table', 'thead', 'tbody', 'tfoot'})),
    'td': (frozenset({'td', 'th'}), frozenset({'tr', 'table'})),
    'th': (frozenset({'td', 'th'}), frozenset({'tr', 'table'})),
    'thead': (frozenset({'thead', 'tbody', 'tfoot', 'tr', 'td', 'th'}), frozenset({'table'})),
    'tbody': (frozenset({'thead', 'tbody', 'tfoot', 'tr', 'td', 'th'}), frozenset({'table'})),
    'tfoot': (frozenset({'thead', 'tbody', 'tfoot', 'tr', 'td', 'th'}), frozenset({'table'})),
    'option': (frozenset({'option'}), frozenset({'select', 'datalist'})),
}


class _ContentExtractor(HTMLParser):
    """Pre-pass stdlib-only: removes noise, isolates the main content block.

    Strategy:
      1. Skip noise tags (and all their children)
      2. If <main>, <article>, or role=main is found -> return only that block
      3. Otherwise return the entire cleaned HTML

    Elements are tracked on a stack of open tags, so an omitted end tag
    (``</li>``, ``</p>``, ``</td>``, valid HTML5) or a stray one cannot shift
    where a skipped subtree or the main block ends. Text and attribute values
    are escaped again, since the parser decodes entities.

    ``profiles`` are the site profiles this page was recognized by; each can
    veto extra subtrees via ``skip_subtree``.
    """
    def __init__(self, profiles: Sequence[SiteProfile] = ()) -> None:
        super().__init__()
        self._profiles = list(profiles)
        self._open: list[str] = []
        # Stack index of the root of the subtree being skipped, or None.
        self._skip_at: int | None = None
        self._buf: list[str] = []       # Complete cleaned HTML buffer
        self._main_buf: list[str] = []  # Main content block buffer
        self._main_at: int | None = None

    def _is_dropped(self, tag: str, ad: dict[str, str | None]) -> bool:
        if tag in _NOISE:
            return True
        return any(profile.skip_subtree(tag, ad) for profile in self._profiles)

    def _emit(self, piece: str) -> None:
        self._buf.append(piece)
        if self._main_at is not None:
            self._main_buf.append(piece)

    def _pop_to(self, index: int) -> None:
        """Close the open elements from the top of the stack down to ``index``."""
        while len(self._open) > index:
            at = len(self._open) - 1
            tag = self._open.pop()
            if self._skip_at is not None:
                if at == self._skip_at:
                    self._skip_at = None  # Closed the root of the skipped subtree
                continue
            self._emit(f'</{tag}>')
            if at == self._main_at:
                self._main_at = None  # Exited the main content block

    def _close_implied(self, tag: str) -> None:
        if tag in _PARAGRAPH_CLOSERS:
            # An open <p> with only inline elements above it ends here
            for i in range(len(self._open) - 1, -1, -1):
                if self._open[i] == 'p':
                    self._pop_to(i)
                    break
                if self._open[i] not in _INLINE_TAGS:
                    break
        rule = _IMPLIED_END.get(tag)
        if rule is None:
            return
        ends, boundary = rule
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i] in ends:
                self._pop_to(i)
                return
            if self._open[i] in boundary:
                return

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = dict(attrs)
        self._close_implied(tag)
        void = tag in _VOID
        if self._skip_at is not None:
            if not void:
                self._open.append(tag)
            return
        if self._is_dropped(tag, ad):
            if not void:
                self._skip_at = len(self._open)
                self._open.append(tag)
            return

        if not void:
            self._open.append(tag)
            if self._main_at is None and (tag in ('main', 'article') or ad.get('role') == 'main'):
                self._main_at = len(self._open) - 1
        attr_str = ''.join(
            f' {k}="{html.escape(v, quote=True)}"' for k, v in attrs
            if k in _SAFE_ATTRS and v
        )
        self._emit(f'<{tag}{attr_str}>')

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i] == tag:
                self._pop_to(i)
                return
        # A stray end tag closes nothing

    def handle_data(self, data: str) -> None:
        if self._skip_at is not None:
            return
        self._emit(html.escape(data, quote=False))

    def get_html(self) -> str:
        return ''.join(self._main_buf or self._buf)


def extract_content(html_text: str, profiles: Sequence[SiteProfile] = ()) -> str:
    """Return the main content of an HTML page, without navigation and other chrome.

    Args:
        html_text: The page source.
        profiles: Active site profiles; their ``skip_subtree`` hooks drop
            site-specific chrome.
    """
    ex = _ContentExtractor(profiles)
    ex.feed(html_text)
    return ex.get_html()


def parse_html(
    text: str,
    *,
    extract_html: bool = False,
    profiles: Sequence[SiteProfile] = (),
) -> Document:
    """Parse HTML text into an AST Document.

    Args:
        text: HTML source.
        extract_html: Keep only the main content (see ``extract_content``).
        profiles: Active site profiles; used with ``extract_html``, then
            their ``clean_ast`` hooks edit the tree.
    """
    if extract_html:
        text = extract_content(text, profiles)
    parser = ASTHTMLParser()
    parser.feed(text)
    parser.close()
    for profile in profiles:
        profile.clean_ast(parser.doc)
    return parser.doc
