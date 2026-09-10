from __future__ import annotations
from html.parser import HTMLParser
from ..ast import (
    Document, Paragraph, Heading, Text, Link, Image, CodeInline, LineBreak,
    CodeBlock, ListBlock, ListItem, Table, TableRow, TableCell, Node,
    BlockQuote, HorizontalRule, Equation
)

_INLINE_TAGS = frozenset([
    'a', 'b', 'strong', 'i', 'em', 'span', 'code', 'img', 'br', 'sub', 'sup',
    'small', 'mark', 'ins', 'del', 'cite', 'dfn', 'kbd', 'samp', 'var', 'q',
    'time', 'ruby', 'rt', 'rp', 'data', 'abbr', 's', 'strike', 'u', 'font', 'big', 'tt'
])

class ASTHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._active_anon_paragraph = None
        self.doc = Document()
        self.stack = [self.doc]
        self.current_text_attrs = {'bold': False, 'italic': False}
        self.in_pre = False
        self.in_thead = False
        self.ignore_data = False
        # Active vertical cell merges carried into following <tr>s:
        # list of {'col': <output column index>, 'rows_left': <int>}.
        self._rowspan_carry: list[dict] = []
        
        self.css_styles = {} # e.g. {'c10': {'bold': True}, ...}
        self.in_style_tag = False
        self.style_data = ""
        self.in_alert_title = False
        
        self.in_math_script = False
        self.math_script_data = ""
        self.math_script_inline = True
        
        self.in_math_element = False
        self.math_element_data = ""
        self.math_element_inline = True
        self.math_element_depth = 0
        
        self.in_math = False
        self.math_code = ""
        self.math_inline = True
        self.in_math_annotation = False
        self.just_parsed_math = False
        
        self.attr_stack = [self.current_text_attrs.copy()]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        classes = attr_dict.get('class', '').split()
        
        if getattr(self, 'in_math', False):
            if tag == 'annotation':
                if attr_dict.get('encoding') == 'application/x-tex':
                    self.in_math_annotation = True
                    self.ignore_data = False
            return

        if tag not in ('math', 'annotation', 'semantics', 'mrow', 'mi', 'mo', 'mn', 'msup', 'msub', 'img', 'span', 'div'):
            self.just_parsed_math = False

        if tag == 'math':
            self.in_math = True
            self.math_inline = (attr_dict.get('display') != 'block')
            self.math_code = ""
            self.in_math_annotation = False
            self.ignore_data = True
            return

        if tag not in _INLINE_TAGS:
            self._active_anon_paragraph = None
        # Implicitly close paragraph if entering a new block element
        if tag in ('p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'table', 'tr', 'td', 'th', 'pre', 'blockquote', 'hr'):
            while len(self.stack) > 1 and isinstance(self.stack[-1], Paragraph):
                node = self.stack.pop()
                self._append_to_parent(node)

        # Implicitly close list item if entering a new list item
        if tag == 'li':
            while len(self.stack) > 1 and isinstance(self.stack[-1], ListItem):
                node = self.stack.pop()
                self._append_to_parent(node)

        # Implicitly close table elements if entering new sibling elements
        if tag == 'tr':
            while len(self.stack) > 1 and isinstance(self.stack[-1], TableRow):
                node = self.stack.pop()
                self._append_to_parent(node)
        elif tag in ('td', 'th'):
            while len(self.stack) > 1 and isinstance(self.stack[-1], TableCell):
                node = self.stack.pop()
                self._append_to_parent(node)

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
        elif tag == 'script':
            script_type = attr_dict.get('type', '')
            if script_type.startswith('math/tex'):
                self.in_math_script = True
                self.math_script_data = ""
                self.math_script_inline = 'mode=display' not in script_type
                self.ignore_data = False
            else:
                self.ignore_data = True
            return
        elif tag == 'div' and 'alert-title' in classes:
            self.in_alert_title = True
            self.ignore_data = True
            return
            
        if not self.in_math_element and tag in ('span', 'div') and 'math' in classes:
            self.in_math_element = True
            self.math_element_data = ""
            self.math_element_inline = 'inline' in classes or tag == 'span'
            self.math_element_depth = 1
            self.ignore_data = False
            return
            
        if getattr(self, 'in_math_element', False):
            self.math_element_depth += 1
            
        # update attrs from stack
        new_attrs = self.attr_stack[-1].copy()
        
        # check CSS class for Google Docs
        for c in classes:
            if c in self.css_styles:
                if self.css_styles[c].get('bold'): new_attrs['bold'] = True
                if self.css_styles[c].get('italic'): new_attrs['italic'] = True
                
        if tag in ('b', 'strong'):
            new_attrs['bold'] = True
        elif tag in ('i', 'em'):
            new_attrs['italic'] = True
            
        self.current_text_attrs = new_attrs
        self.attr_stack.append(new_attrs)
            
        node = None
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            node = Heading(level=int(tag[1]))
        elif tag == 'title':
            node = Heading(level=1)
        elif tag == 'p':
            if 'title' in classes:
                node = Heading(level=1)
            else:
                node = Paragraph()
        elif tag in ('ul', 'ol'):
            node = ListBlock(ordered=(tag == 'ol'))
        elif tag == 'li':
            node = ListItem()
        elif tag == 'table':
            node = Table()
            self._rowspan_carry = []  # spans do not cross table boundaries
        elif tag == 'thead':
            self.in_thead = True
        elif tag == 'tr':
            node = TableRow()
        elif tag in ('td', 'th'):
            node = TableCell()
            # If th and parent is TableRow, we just treat it nicely.
            # We'll map it to headers if in_thead is True or if headers are empty
            def _span(name: str) -> int:
                try:
                    return max(1, int(attr_dict.get(name, '1')))
                except (TypeError, ValueError):
                    return 1
            node._colspan = _span('colspan')
            node._rowspan = _span('rowspan')
        elif tag == 'pre':
            self.in_pre = True
            # Looking for class="language-xyz"
            lang = attr_dict.get('class', '').replace('language-', '') or None
            node = CodeBlock(code="", language=lang)
        elif tag == 'code' and not self.in_pre:
            node = CodeInline(code="")
        elif tag == 'a':
            node = Link(url=attr_dict.get('href', ''), title=attr_dict.get('title'))
        elif tag == 'img':
            # Skip Wikipedia math fallback images or convert them if math was not parsed
            if any(c.startswith('mwe-math-fallback-image') for c in classes):
                if getattr(self, 'just_parsed_math', False):
                    self.just_parsed_math = False
                    return
                alt = attr_dict.get('alt', '')
                if alt.startswith(r'{\displaystyle') and alt.endswith('}'):
                    alt = alt[14:-1].strip()
                elif alt.startswith(r'\displaystyle'):
                    alt = alt[13:].strip()
                inline = 'mwe-math-fallback-image-inline' in classes
                eq = Equation(code=alt, inline=inline)
                self._append_to_parent(eq)
                return
            img = Image(src=attr_dict.get('src', ''), alt=attr_dict.get('alt', ''), title=attr_dict.get('title'))
            self._append_to_parent(img)
            return
        elif tag == 'br':
            self._append_to_parent(LineBreak())
            return
        elif tag == 'hr':
            self._append_to_parent(HorizontalRule())
            return
        elif tag == 'blockquote':
            alert_type = None
            for c in classes:
                if c.startswith('alert-'):
                    alert_type = c.replace('alert-', '').upper()
                    break
            node = BlockQuote(alert_type=alert_type)
            
        if node is not None:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        if getattr(self, 'in_math', False):
            if tag == 'annotation' and getattr(self, 'in_math_annotation', False):
                self.in_math_annotation = False
                self.ignore_data = True
            elif tag == 'math':
                self.in_math = False
                self.ignore_data = False
                self.just_parsed_math = True
                code = self.math_code.strip()
                if code.startswith(r'{\displaystyle') and code.endswith('}'):
                    code = code[14:-1].strip()
                elif code.startswith(r'\displaystyle'):
                    code = code[13:].strip()
                eq = Equation(code=code, inline=self.math_inline)
                self._append_to_parent(eq)
            return

        if tag not in _INLINE_TAGS:
            self._active_anon_paragraph = None
        if tag == 'style':
            self.in_style_tag = False
            self.ignore_data = False
            self.parse_css(self.style_data)
            self.style_data = ""
            return
        elif tag == 'script':
            if getattr(self, 'in_math_script', False):
                self.in_math_script = False
                eq = Equation(code=self.math_script_data.strip(), inline=self.math_script_inline)
                self._append_to_parent(eq)
                self.math_script_data = ""
            self.ignore_data = False
            return
        elif tag == 'div' and self.in_alert_title:
            self.in_alert_title = False
            self.ignore_data = False
            return
            
        if getattr(self, 'in_math_element', False):
            if tag in ('span', 'div') and self.math_element_depth == 1:
                self.in_math_element = False
                code = self.math_element_data.strip()
                if code.startswith(r'\(') and code.endswith(r'\)'):
                    code = code[2:-2].strip()
                elif code.startswith('$$') and code.endswith('$$'):
                    code = code[2:-2].strip()
                elif code.startswith(r'\[') and code.endswith(r'\]'):
                    code = code[2:-2].strip()
                eq = Equation(code=code, inline=self.math_element_inline)
                self._append_to_parent(eq)
                self.math_element_data = ""
                return
            else:
                self.math_element_depth -= 1
            
        # pop attrs for this tag
        if len(self.attr_stack) > 1:
            self.attr_stack.pop()
        self.current_text_attrs = self.attr_stack[-1]
            
        if tag == 'thead':
            self.in_thead = False
            return
        elif tag == 'pre':
            self.in_pre = False
            
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'ul', 'ol', 'li', 'table', 'tr', 'td', 'th', 'a', 'pre', 'code', 'blockquote', 'title'):
            # Only pop if we actually pushed something (ignoring structural mismatches)
            if len(self.stack) > 1:
                node = self.stack.pop()

                parent = self.stack[-1]

                # Flatten colspan/rowspan into a rectangular grid of plain cells
                if tag == 'tr' and isinstance(node, TableRow):
                    self._resolve_row_spans(node)

                # Check if this is an Abstract blockquote
                if tag == 'blockquote' and isinstance(node, BlockQuote):
                    if getattr(node, '_is_abstract', False):
                        from ..ast import Abstract
                        node = Abstract(children=node.children)
                    else:
                        def _get_first_text(n: Node) -> Text | None:
                            from ..ast import Text
                            if isinstance(n, Text): return n
                            if hasattr(n, 'children') and n.children: return _get_first_text(n.children[0])
                            if hasattr(n, 'content') and isinstance(n.content, list) and n.content: return _get_first_text(n.content[0])
                            return None
                            
                        first_text = _get_first_text(node)
                        if first_text and first_text.content.strip().lower().startswith("abstract"):
                            import re
                            first_text.content = re.sub(r'^\s*abstract[\s:]*', '', first_text.content, flags=re.IGNORECASE)
                            from ..ast import Abstract
                            node = Abstract(children=node.children)
                
                # Special handling for table headers
                if tag == 'th' or (tag == 'tr' and self.in_thead and isinstance(parent, Table)):
                    if isinstance(node, TableRow) and isinstance(parent, Table):
                        parent.headers = node.cells
                    elif isinstance(node, TableCell) and getattr(parent, 'cells', None) is not None:
                        parent.cells.append(node)
                    else:
                        self._append_to_parent(node, force_parent=parent)
                else:
                    self._append_to_parent(node, force_parent=parent)

    def handle_data(self, data: str) -> None:
        if getattr(self, 'in_alert_title', False):
            if data.strip().lower() == "abstract":
                if len(self.stack) > 0 and isinstance(self.stack[-1], BlockQuote):
                    self.stack[-1]._is_abstract = True
            return

        if self.in_style_tag:
            self.style_data += data
            
        if getattr(self, 'in_math', False):
            if getattr(self, 'in_math_annotation', False):
                self.math_code += data
            return
            
        if getattr(self, 'in_math_script', False):
            self.math_script_data += data
            return
            
        if getattr(self, 'in_math_element', False):
            self.math_element_data += data
            return
            
        if self.ignore_data:
            return
            
        if not data.strip() and not self.in_pre:
            return
            
        parent = self.stack[-1]
        
        if self.in_pre and isinstance(parent, CodeBlock):
            parent.code += data
            return
            
        if isinstance(parent, CodeInline):
            parent.code += data
            return

        text = Text(
            content=data if self.in_pre else data,
            bold=self.current_text_attrs['bold'],
            italic=self.current_text_attrs['italic']
        )
        self._append_to_parent(text, force_parent=parent)

    def _maybe_cell_separator(self) -> None:
        """Insert a space between adjacent block chunks inside a table cell.

        Word-processor HTML frequently wraps each visual line of a cell in its
        own ``<div>``/``<p>`` with no whitespace between them; without this the
        renderers would glue the words together ("Enter" + "Service").
        """
        if not self.stack or not isinstance(self.stack[-1], TableCell):
            return
        cell = self.stack[-1]
        if not cell.children:
            return
        last = cell.children[-1]
        if isinstance(last, LineBreak):
            return
        if isinstance(last, Text) and (not last.content or last.content[-1].isspace()):
            return
        cell.children.append(Text(content=" "))

    def _resolve_row_spans(self, row: TableRow) -> None:
        """Expand ``colspan``/``rowspan`` on a just-closed row into plain cells.

        ``colspan`` becomes N cells (content in the first, blanks after);
        ``rowspan`` records a carry so the following rows get a blank
        placeholder at the same column. The private ``_colspan``/``_rowspan``
        attributes are removed so the emitted AST is span-free and the JSON
        schema is unchanged.
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
            colspan = getattr(cell, '_colspan', 1) or 1
            rowspan = getattr(cell, '_rowspan', 1) or 1
            for attr in ('_colspan', '_rowspan'):
                if hasattr(cell, attr):
                    delattr(cell, attr)
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
        if isinstance(parent, (Document, BlockQuote, ListItem)):
            if isinstance(node, (Text, Link, Image, CodeInline, LineBreak)):
                if (self._active_anon_paragraph is None or 
                    not parent.children or 
                    parent.children[-1] is not self._active_anon_paragraph):
                    
                    p = Paragraph()
                    parent.children.append(p)
                    self._active_anon_paragraph = p
                
                self._active_anon_paragraph.children.append(node)
                return

        if hasattr(parent, 'children'):
            parent.children.append(node)
        elif hasattr(parent, 'items') and isinstance(node, ListItem):
            parent.items.append(node)
        elif hasattr(parent, 'rows') and isinstance(node, TableRow):
            parent.rows.append(node)
        elif hasattr(parent, 'cells') and isinstance(node, TableCell):
            parent.cells.append(node)
        elif hasattr(parent, 'content') and isinstance(node, Node): # Link content
            parent.content.append(node)
            
    def parse_css(self, css_str: str) -> None:
        import re
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
            node = self.stack.pop()
            self._append_to_parent(node)


_NOISE = frozenset(['script', 'style', 'nav', 'footer', 'header',
                    'aside', 'noscript', 'iframe', 'form', 'head'])
_VOID = frozenset([
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr'
])
_SAFE_ATTRS = frozenset(['href', 'src', 'alt', 'title', 'class', 'id', 'role', 'encoding', 'display', 'colspan', 'rowspan'])


class _ContentExtractor(HTMLParser):
    """Pre-pass stdlib-only: removes noise, isolates the main content block.

    Strategy:
      1. Skip noise tags (and all their children)
      2. If <main>, <article>, or role=main is found -> return only that block
      3. Otherwise return the entire cleaned HTML
    """
    def __init__(self) -> None:
        super().__init__()
        self._depth = 0
        self._skip_tag = None   # Name of the active noise tag causing skip
        self._buf = []     # Complete cleaned HTML buffer
        self._main_buf = []     # Main content block buffer
        self._main_depth = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_tag is not None:
            return
        if tag in _NOISE:
            self._skip_tag = tag
            return

        if tag not in _VOID:
            self._depth += 1

        ad = dict(attrs)
        if tag in ('main', 'article') or ad.get('role') == 'main':
            if self._main_depth is None:
                self._main_depth = self._depth

        attr_str = ''.join(
            f' {k}="{v}"' for k, v in attrs
            if k in _SAFE_ATTRS and v
        )
        piece = f'<{tag}{attr_str}>'
        self._buf.append(piece)
        if self._main_depth is not None:
            self._main_buf.append(piece)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if self._skip_tag is not None:
            if tag == self._skip_tag:
                self._skip_tag = None
            return

        self._depth -= 1
        piece = f'</{tag}>'
        self._buf.append(piece)
        if self._main_depth is not None:
            self._main_buf.append(piece)
            if self._depth < self._main_depth:
                self._main_depth = None  # Exited the main content block

    def handle_data(self, data: str) -> None:
        if self._skip_tag is not None:
            return
        self._buf.append(data)
        if self._main_depth is not None:
            self._main_buf.append(data)

    def get_html(self) -> str:
        return ''.join(self._main_buf or self._buf)


def extract_content(html: str) -> str:
    ex = _ContentExtractor()
    ex.feed(html)
    return ex.get_html()


def parse_html(text: str, extract: bool = False) -> Document:
    if extract:
        text = extract_content(text)
    parser = ASTHTMLParser()
    parser.feed(text)
    parser.close()
    return parser.doc

