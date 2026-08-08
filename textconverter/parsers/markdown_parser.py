from __future__ import annotations
import re

from ..ast import (
    Document, Paragraph, Heading, Text, Link, Image, CodeInline,
    CodeBlock, ListBlock, ListItem, Table, TableRow, TableCell, InlineElement,
    BlockQuote, HorizontalRule, Equation
)

def smart_preprocess_markdown(text: str) -> str:
    """Preprocess raw markdown to ensure structural block boundaries have empty lines.

    This resolves bugs where headings, lists, code blocks, or blockquotes immediately
    follow paragraphs or other blocks without a blank line, causing them to be grouped
    into single paragraphs by simple block splitters.
    """
    # 1. Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # 2. Smart block separator insertion
    lines = text.split('\n')
    new_lines = []
    in_code_block = False
    
    for line in lines:
        stripped = line.strip()
        
        # Track code block state
        if stripped.startswith("```"):
            if in_code_block:
                in_code_block = False
                new_lines.append(line)
                continue
            else:
                in_code_block = True
            
        if in_code_block:
            new_lines.append(line)
            continue
            
        # Check if current line starts a block element
        is_heading = re.match(r'^#{1,6}\s+', stripped)
        is_list_item = re.match(r'^\s*[-*+•●○■]\s+', line) or re.match(r'^\s*\d+\.\s+', line)
        is_code_fence = stripped.startswith("```")
        is_hr = re.match(r'^[-*_]{3,}\s*$', stripped)
        is_blockquote = stripped.startswith(">")
        
        if (is_heading or is_list_item or is_code_fence or is_hr or is_blockquote) and new_lines:
            prev_line = new_lines[-1]
            prev_stripped = prev_line.strip()
            
            # Check if we should insert an empty line before the block element
            should_insert = False
            if prev_stripped: # Previous line is not empty
                if is_heading or is_hr:
                    should_insert = True
                elif is_code_fence:
                    prev_is_list = (re.match(r'^\s*[-*+]\s+', prev_line) or
                                    re.match(r'^\s*\d+\.\s+', prev_line))
                    if not prev_is_list:
                        should_insert = True
                elif is_blockquote:
                    if not prev_stripped.startswith(">"):
                        should_insert = True
                elif is_list_item:
                    # Insert if previous line was not a list item and not a continuation
                    prev_is_list = re.match(r'^\s*[-*+•●○■]\s+', prev_line) or re.match(r'^\s*\d+\.\s+', prev_line)
                    prev_is_continuation = prev_line.startswith(" ") or prev_line.startswith("\t")
                    if not (prev_is_list or prev_is_continuation):
                        should_insert = True
            
            if should_insert:
                new_lines.append("")
                
        new_lines.append(line)
        
    return '\n'.join(new_lines)


def _parse_markdown_list(block_text: str, ref_map: dict | None = None) -> ListBlock:
    lines = block_text.split('\n')
    stack = []
    root_list_block = None

    for line in lines:
        if not line.strip():
            continue
            
        m = re.match(r'^(\s*)([-*+•●○■]|\d+\.)\s+(.*)$', line)
        if m:
            indent = len(m.group(1).replace('\t', '    '))
            marker = m.group(2)
            content = m.group(3)
            ordered = marker[0].isdigit()
            
            # Pop stack while top has strictly greater indent
            while stack and stack[-1]["indent"] > indent:
                stack.pop()
                
            if not stack:
                # Root list block
                root_list_block = ListBlock(ordered=ordered)
                new_item = ListItem(children=[Paragraph(children=parse_inline(content.strip(), ref_map=ref_map))])
                root_list_block.items.append(new_item)
                stack.append({"indent": indent, "list_block": root_list_block, "list_item": new_item})
            elif stack[-1]["indent"] < indent:
                # Nested list block
                new_list = ListBlock(ordered=ordered)
                new_item = ListItem(children=[Paragraph(children=parse_inline(content.strip(), ref_map=ref_map))])
                new_list.items.append(new_item)
                stack[-1]["list_item"].children.append(new_list)
                stack.append({"indent": indent, "list_block": new_list, "list_item": new_item})
            else:
                # Sibling item in current list block
                new_item = ListItem(children=[Paragraph(children=parse_inline(content.strip(), ref_map=ref_map))])
                stack[-1]["list_block"].items.append(new_item)
                stack[-1]["list_item"] = new_item
        else:
            # Decode encoded code/math block placeholders that were inside a list item
            stripped_line = line.strip()
            m_cb = re.match(r'^<!--CODEBLOCK:([A-Za-z0-9+/=]+)-->$', stripped_line)
            m_mb = re.match(r'^<!--MATHBLOCK:([A-Za-z0-9+/=]+)-->$', stripped_line)
            if m_cb and stack:
                import base64, json as _json
                payload = _json.loads(base64.b64decode(m_cb.group(1)).decode('utf-8'))
                cb = CodeBlock(code=payload['code'].strip(), language=payload['lang'] or None)
                stack[-1]['list_item'].children.append(cb)
            elif m_mb and stack:
                import base64, json as _json
                payload = _json.loads(base64.b64decode(m_mb.group(1)).decode('utf-8'))
                stack[-1]['list_item'].children.append(Equation(code=payload['code'], inline=False))
            elif stack:
                # Continuation line — append to last paragraph of active item
                active_item = stack[-1]['list_item']
                last_p = None
                if active_item.children and isinstance(active_item.children[-1], Paragraph):
                    last_p = active_item.children[-1]
                if last_p:
                    last_p.children.extend(parse_inline(' ' + stripped_line))
                else:
                    active_item.children.append(Paragraph(children=parse_inline(stripped_line)))
                    
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
    _ref_def_re = re.compile(
        r'^ {0,3}\[([^\]]+)\]:\s+<?([^>\s]+?)>?'
        r'(?:\s+(?:"([^"]*)"|\x27([^\x27]*)\x27|\(([^)]*)\)))?\s*$',
        re.MULTILINE
    )
    ref_map: dict[str, tuple[str, str | None]] = dict(parent_ref_map or {})
    for rm in _ref_def_re.finditer(text):
        label = rm.group(1).lower().strip()
        url   = rm.group(2)
        title = rm.group(3) or rm.group(4) or rm.group(5) or None
        ref_map[label] = (url, title)
    text = _ref_def_re.sub('', text)
    
    # Pre-process code blocks to preserve empty lines inside them (first pass for existing fences)
    def _encode_codeblock(m):
        import base64, json
        lang = m.group(1)
        code = m.group(2)
        
        # Strip common indentation from code block lines
        lines = code.split('\n')
        if lines:
            indent = ""
            for line in lines:
                if line.strip():
                    indent = line[:len(line) - len(line.lstrip())]
                    break
            if indent:
                lines = [line[len(indent):] if line.startswith(indent) else line for line in lines]
            code = '\n'.join(lines)
            
        payload = json.dumps({"lang": lang, "code": code})
        b64_code = base64.b64encode(payload.encode('utf-8')).decode('utf-8')
        return f"\n\n<!--CODEBLOCK:{b64_code}-->\n\n"
        
    text = re.sub(r'^[ \t]*```[ \t]*([^\n`]*)\n(.*?)^[ \t]*```', _encode_codeblock, text, flags=re.MULTILINE | re.DOTALL)

    if code_parsing:
        from ..code_detector import pre_process_markdown_code
        text = pre_process_markdown_code(text)
        # Second pass: encode newly detected and fenced code blocks
        text = re.sub(r'^[ \t]*```[ \t]*([^\n`]*)\n(.*?)^[ \t]*```', _encode_codeblock, text, flags=re.MULTILINE | re.DOTALL)
        
    doc = Document()
    
    # Pre-process math blocks (before splitting into paragraphs)
    def _encode_mathblock(m):
        import base64, json
        code = m.group(1).strip()
        payload = json.dumps({"code": code})
        b64_code = base64.b64encode(payload.encode('utf-8')).decode('utf-8')
        return f"\n\n<!--MATHBLOCK:{b64_code}-->\n\n"
        
    text = re.sub(r'(?<!\\)\$\$(.*?)(?<!\\)\$\$', _encode_mathblock, text, flags=re.MULTILINE | re.DOTALL)
    
    # Pre-process OCR text from images
    def _encode_ocr(m):
        import base64
        img_str = m.group(1)
        ocr_text = m.group(2).strip()
        b64_ocr = base64.b64encode(ocr_text.encode('utf-8')).decode('utf-8')
        return f"{img_str}<!--OCR:{b64_ocr}-->"
        
    text = re.sub(r'(!\[.*?\]\(.*?\))\s*\*\*----- Start of picture text -----\*\*(.*?)\*\*----- End of picture text -----\*\*', _encode_ocr, text, flags=re.DOTALL)
    
    # Simple block splitting
    blocks = re.split(r'\n\s*\n', text.strip())
    
    for block in blocks:
        block = block.strip()
        if not block:
            continue
            
        # 1. Code Blocks
        m_code = re.match(r'^<!--CODEBLOCK:([A-Za-z0-9+/=]+)-->$', block)
        if m_code:
            import base64, json
            payload = json.loads(base64.b64decode(m_code.group(1)).decode('utf-8'))
            cb = CodeBlock(code=payload['code'].strip(), language=payload['lang'] or None)
            # If the previous block was a list, attach this code to the last list item
            if doc.children and isinstance(doc.children[-1], ListBlock):
                doc.children[-1].items[-1].children.append(cb)
            else:
                doc.children.append(cb)
            continue
            
        # 1b. Math Blocks
        m_math = re.match(r'^<!--MATHBLOCK:([A-Za-z0-9+/=]+)-->$', block)
        if m_math:
            import base64, json
            payload = json.loads(base64.b64decode(m_math.group(1)).decode('utf-8'))
            eq = Equation(code=payload['code'], inline=False)
            # If the previous block was a list, attach to the last list item
            if doc.children and isinstance(doc.children[-1], ListBlock):
                doc.children[-1].items[-1].children.append(eq)
            else:
                doc.children.append(eq)
            continue
            
        # 2. Headings
        m_heading = re.match(r'^(#{1,6})\s+(.*)$', block, flags=re.MULTILINE)
        if m_heading:
            level = len(m_heading.group(1))
            doc.children.append(Heading(level=level, children=parse_inline(m_heading.group(2).strip(), ref_map=ref_map)))
            continue
            
        # 3. Horizontal Rule
        if re.match(r'^[-*_]{3,}\s*$', block):
            doc.children.append(HorizontalRule())
            continue
            
        # 4. Blockquote
        if block.startswith(">"):
            lines = block.split('\n')
            cleaned_lines = []
            for line in lines:
                stripped_line = line.strip()
                if stripped_line.startswith(">"):
                    content = line.lstrip()[1:]
                    if content.startswith(" "):
                        content = content[1:]
                    cleaned_lines.append(content)
                else:
                    # Lazy continuation line
                    cleaned_lines.append(line)
            quote_text = '\n'.join(cleaned_lines).strip()
            
            # Detect callouts like [!IMPORTANT]
            alert_type = None
            m_alert = re.match(r'^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$', quote_text, flags=re.IGNORECASE | re.DOTALL)
            if m_alert:
                alert_type = m_alert.group(1).upper()
                quote_text = m_alert.group(2).strip()
                
            # Recursive parse to support nested elements; inherit the outer
            # document's reference-style link/image definitions so that
            # references defined outside the blockquote still resolve.
            parsed_inner = parse_markdown(quote_text, code_parsing=code_parsing, parent_ref_map=ref_map)
            
            # Check if this is an Abstract blockquote by inspecting the first text node
            def _get_first_text(n):
                from ..ast import Text
                if isinstance(n, Text): return n
                if hasattr(n, 'children') and n.children: return _get_first_text(n.children[0])
                if hasattr(n, 'content') and isinstance(n.content, list) and n.content: return _get_first_text(n.content[0])
                return None
                
            first_text = _get_first_text(parsed_inner)
            if first_text and first_text.content.strip().lower().startswith("abstract"):
                first_text.content = re.sub(r'^\s*abstract[\s:]*', '', first_text.content, flags=re.IGNORECASE)
                from ..ast import Abstract
                doc.children.append(Abstract(children=parsed_inner.children))
                continue
                
            doc.children.append(BlockQuote(children=parsed_inner.children, alert_type=alert_type))
            continue
            
        # 3. Lists (Ordered and Unordered)
        if re.match(r'^[-*+•●○■]\s+', block) or re.match(r'^\d+\.\s+', block):
            lb = _parse_markdown_list(block, ref_map=ref_map)
            if lb:
                if (doc.children and 
                    isinstance(doc.children[-1], ListBlock) and 
                    doc.children[-1].ordered == lb.ordered):
                    doc.children[-1].items.extend(lb.items)
                else:
                    doc.children.append(lb)
            continue
            
        # 5. Tables
        if '|' in block and '\n' in block:
            lines = block.split('\n')
            has_separator = len(lines) >= 2 and '|' in lines[0] and '-' in lines[1]
            is_strict_table = len(lines) >= 1 and all(line.strip().startswith('|') and line.strip().endswith('|') for line in lines)
            
            if has_separator or is_strict_table:
                table = Table()
                start_idx = 0
                
                if has_separator:
                    # Headers
                    headers = [c.strip() for c in lines[0].split('|') if c.strip()]
                    table.headers = [TableCell(children=parse_inline(h, ref_map=ref_map)) for h in headers]
                    start_idx = 2
                    
                # Rows
                for line in lines[start_idx:]:
                    cells = [c.strip() for c in line.split('|')]
                    # Filter out empty outer pipes
                    if line.strip().startswith('|'): cells = cells[1:]
                    if line.strip().endswith('|'): cells = cells[:-1]
                    
                    table.rows.append(TableRow(cells=[TableCell(children=parse_inline(c, ref_map=ref_map)) for c in cells]))
                doc.children.append(table)
                continue
                
        # Fallback: Paragraph
        p = Paragraph(children=parse_inline(block, ref_map=ref_map))
        doc.children.append(p)
        
    return doc

import uuid

def _parse_formatting(text: str) -> list[InlineElement]:
    store = {}
    counter = [0]
    
    def r_bold(m):
        counter[0] += 1
        k = f"@@B{counter[0]}@@"
        content = m.group(1) if m.group(1) is not None else m.group(2)
        store[k] = ('bold', content or "")
        return k
        
    def r_italic(m):
        counter[0] += 1
        k = f"@@I{counter[0]}@@"
        content = m.group(1) if m.group(1) is not None else m.group(2)
        store[k] = ('italic', content or "")
        return k

    text = re.sub(r'\*\*(.*?)\*\*|__(.*?)__', r_bold, text, flags=re.DOTALL)
    text = re.sub(r'\*(.*?)\*|_(.*?)_', r_italic, text, flags=re.DOTALL)
    
    def resolve(string, is_b=False, is_i=False):
        res = []
        parts = re.split(r'(@@[BI]\d+@@)', string)
        for p in parts:
             if not p: continue
             if p in store:
                 tag, inner = store[p]
                 if tag == 'bold': res.extend(resolve(inner, is_b=True, is_i=is_i))
                 elif tag == 'italic': res.extend(resolve(inner, is_b=is_b, is_i=True))
             else:
                 res.append(Text(content=p, bold=is_b, italic=is_i))
        return res
        
    return resolve(text)

def parse_inline(text: str, ref_map: dict | None = None) -> list[InlineElement]:
    """Parses inline markdown like bold, italic, links, images, code.

    Args:
        text: The inline markdown string to parse.
        ref_map: Optional dict mapping lowercase reference labels to (url, title) tuples,
                 used to resolve reference-style links and images.
    """
    elements = []

    pattern = re.compile(
        # LaTeX safeguarded macros
        r'(?P<latexmacro>\\(?:footnote|cite|citet|citep|ref|label)\b)|'
        # Reference-style image: ![alt][id]  — must come before reflink and inline-image
        r'(?P<refimg>!\[(?P<ri_alt>[^\]]*)\]\[(?P<ri_id>[^\]]*)\])|'
        # Reference-style link: [content][id] — content may include inline images
        # Uses .*? (non-greedy) so it stops at the first ][id] after the opening [
        r'(?P<reflink>(?<!!)(?<!\])\[(?P<rl_text>.*?)\]\[(?P<rl_id>[^\]]*)\])|'
        # Inline image: ![alt](url "title") with optional OCR block
        r'(?P<inlineimg>!\[(?P<img_alt>[^\]]*)\]\((?P<img_url>[^\)\s]*)(?:\s+"(?P<img_title>[^"]*)")?\)(?:<!--OCR:(?P<ocr_b64>[A-Za-z0-9+/=]+)-->)?)|'
        # Linked image: [![alt](imgurl "imgtitle")](linkurl "linktitle") — an inline image
        # used as the entire content of an inline link. Must come before inlinelink, whose
        # link_text ([^\]]+) cannot span the nested image's own closing bracket/paren and
        # would otherwise misparse the image's URL as the link's URL.
        r'(?P<linkedimg>\[!\[(?P<li_alt>[^\]]*)\]\((?P<li_img_url>[^\)\s]*)(?:\s+"(?P<li_img_title>[^"]*)")?\)\]\((?P<li_link_url>[^\)\s]*)(?:\s+"(?P<li_link_title>[^"]*)")?\))|'
        # Inline link: [text](url "title")
        r'(?P<inlinelink>(?<!!)(?<!\])\[(?P<link_text>[^\]]+)\]\((?P<link_url>[^\)\s]*)(?:\s+"(?P<link_title>[^"]*)")?\))|'
        r'(?P<codeinline>`(?P<code_content>[^`]+)`)|'
        r'(?P<mathinline>(?<!\\)\$(?!\s)(?P<math_content>[^$]+?)(?<!\s)(?<!\\)\$)|'
        r'(?P<linebreak><br\s*/?>)'
    )

    pos = 0
    while pos < len(text):
        m = pattern.search(text, pos)
        if not m:
            chunk = text[pos:]
            if chunk:
                elements.extend(_parse_formatting(chunk))
            break

        if m.start() > pos:
            chunk = text[pos:m.start()]
            if chunk:
                elements.extend(_parse_formatting(chunk))

        g = m.groupdict()

        if g.get('latexmacro') is not None:
            cmd_name = g['latexmacro']
            cmd_base = cmd_name[1:] # remove leading \
            from .latex_parser import _extract_macro_args
            from ..ast import Footnote, Citation, Reference, Label
            args, start, end = _extract_macro_args(text, cmd_name, m.start())
            if start != -1 and args:
                if cmd_base == 'footnote':
                    elements.append(Footnote(content=parse_inline(args[0], ref_map=ref_map)))
                elif cmd_base in ('cite', 'citet', 'citep'):
                    keys = [k.strip() for k in args[0].split(',') if k.strip()]
                    elements.append(Citation(keys=keys, style=cmd_base))
                elif cmd_base == 'ref':
                    elements.append(Reference(label=args[0].strip()))
                elif cmd_base == 'label':
                    elements.append(Label(name=args[0].strip()))
                pos = end
                continue
            else:
                # If extraction fails (e.g. no braces), treat it as plain text and advance
                elements.append(Text(content=cmd_name))
                pos = m.end()
                continue
                
        elif g.get('refimg') is not None:
            # Reference-style image: ![alt][id]
            label = (g['ri_id'] or g['ri_alt']).lower().strip()
            url, title = (ref_map or {}).get(label, ('', None))
            elements.append(Image(src=url, alt=g['ri_alt'], title=title))
        elif g.get('reflink') is not None:
            # Reference-style link: [content][id] — content may include an inline image
            label = (g['rl_id'] or g['rl_text']).lower().strip()
            url, title = (ref_map or {}).get(label, ('#', None))
            link = Link(url=url, title=title,
                        content=parse_inline(g['rl_text'], ref_map=ref_map))
            elements.append(link)
        elif g.get('inlineimg') is not None:
            ocr_text = None
            if g.get('ocr_b64'):
                import base64
                ocr_text = base64.b64decode(g['ocr_b64']).decode('utf-8')
            elements.append(Image(
                src=g['img_url'],
                alt=g.get('img_alt', ''),
                title=g.get('img_title'),
                extracted_text=ocr_text,
            ))
        elif g.get('linkedimg') is not None:
            img = Image(src=g['li_img_url'], alt=g.get('li_alt', ''), title=g.get('li_img_title'))
            link = Link(url=g['li_link_url'], title=g.get('li_link_title'), content=[img])
            elements.append(link)
        elif g.get('inlinelink') is not None:
            link = Link(
                url=g['link_url'],
                title=g.get('link_title'),
                content=parse_inline(g['link_text'], ref_map=ref_map),
            )
            elements.append(link)
        elif g.get('codeinline') is not None:
            elements.append(CodeInline(code=g['code_content']))
        elif g.get('mathinline') is not None:
            elements.append(Equation(code=g['math_content'], inline=True))
        elif g.get('linebreak') is not None:
            from ..ast import LineBreak
            elements.append(LineBreak())

        pos = m.end()

    return elements
