import re
from typing import List

from ..ast import (
    Document, Paragraph, Heading, Text, Link, Image, CodeInline,
    CodeBlock, ListBlock, ListItem, Table, TableRow, TableCell, InlineElement,
    BlockQuote, HorizontalRule
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
                if is_heading or is_code_fence or is_hr:
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


def parse_markdown(text: str, code_parsing: bool = False) -> Document:
    """Parses markdown text into an AST Document."""
    text = smart_preprocess_markdown(text)
    
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
        
    text = re.sub(r'^[ \t]*```[ \t]*(\w*)\n(.*?)^[ \t]*```', _encode_codeblock, text, flags=re.MULTILINE | re.DOTALL)

    if code_parsing:
        from ..code_detector import pre_process_markdown_code
        text = pre_process_markdown_code(text)
        # Second pass: encode newly detected and fenced code blocks
        text = re.sub(r'^[ \t]*```[ \t]*(\w*)\n(.*?)^[ \t]*```', _encode_codeblock, text, flags=re.MULTILINE | re.DOTALL)
        
    doc = Document()
    
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
            doc.children.append(CodeBlock(code=payload['code'].strip(), language=payload['lang'] or None))
            continue
            
        # 2. Headings
        m_heading = re.match(r'^(#{1,6})\s+(.*)$', block, flags=re.MULTILINE)
        if m_heading:
            level = len(m_heading.group(1))
            doc.children.append(Heading(level=level, children=parse_inline(m_heading.group(2).strip())))
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
                
            # Recursive parse to support nested elements
            parsed_inner = parse_markdown(quote_text, code_parsing=code_parsing)
            doc.children.append(BlockQuote(children=parsed_inner.children, alert_type=alert_type))
            continue
            
        # 3. Unordered Lists
        if re.match(r'^[-*+•●○■]\s+', block):
            lb = ListBlock(ordered=False)
            lines = block.split('\n')
            for line in lines:
                m_item = re.match(r'^\s*[-*+•●○■]\s+(.*)$', line)
                if m_item:
                    lb.items.append(ListItem(children=[Paragraph(children=parse_inline(m_item.group(1).strip()))]))
                elif lb.items:
                    lb.items[-1].children.append(Paragraph(children=parse_inline(line.strip())))
            
            if doc.children and isinstance(doc.children[-1], ListBlock) and not doc.children[-1].ordered:
                doc.children[-1].items.extend(lb.items)
            else:
                doc.children.append(lb)
            continue
            
        # 4. Ordered Lists
        if re.match(r'^\d+\.\s+', block):
            lb = ListBlock(ordered=True)
            lines = block.split('\n')
            for line in lines:
                m_item = re.match(r'^\s*\d+\.\s+(.*)$', line)
                if m_item:
                    lb.items.append(ListItem(children=[Paragraph(children=parse_inline(m_item.group(1).strip()))]))
                elif lb.items:
                    lb.items[-1].children.append(Paragraph(children=parse_inline(line.strip())))
            
            if doc.children and isinstance(doc.children[-1], ListBlock) and doc.children[-1].ordered:
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
                    table.headers = [TableCell(children=parse_inline(h)) for h in headers]
                    start_idx = 2
                    
                # Rows
                for line in lines[start_idx:]:
                    cells = [c.strip() for c in line.split('|')]
                    # Filter out empty outer pipes
                    if line.strip().startswith('|'): cells = cells[1:]
                    if line.strip().endswith('|'): cells = cells[:-1]
                    
                    table.rows.append(TableRow(cells=[TableCell(children=parse_inline(c)) for c in cells]))
                doc.children.append(table)
                continue
                
        # Fallback: Paragraph
        p = Paragraph(children=parse_inline(block))
        doc.children.append(p)
        
    return doc

import uuid

def _parse_formatting(text: str) -> List[InlineElement]:
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

def parse_inline(text: str) -> List[InlineElement]:
    """Parses inline markdown like bold, italic, links, images, code."""
    elements = []
    
    pattern = re.compile(
        r'(!\[(?P<img_alt>[^\]]*)\]\((?P<img_url>[^\)\s]*)\s*(?:\"(?P<img_title>[^\"]*)\")?\)(?:<!--OCR:(?P<ocr_b64>[A-Za-z0-9+/=]+)-->)?)|'
        r'(\[(?P<link_text>[^\]]+)\]\((?P<link_url>[^\)\s]*)\s*(?:\"(?P<link_title>[^\"]*)\")?\))|'
        r'(?P<codeinline>`(?P<code_content>[^`]+)`)|'
        r'(?P<linebreak><br\s*/?>)'
    )
    
    pos = 0
    while pos < len(text):
        m = pattern.search(text, pos)
        if not m:
            chunk = text[pos:]
            if chunk: elements.extend(_parse_formatting(chunk))
            break
            
        if m.start() > pos:
            chunk = text[pos:m.start()]
            if chunk: elements.extend(_parse_formatting(chunk))
            
        g = m.groupdict()
        if g.get('img_url') is not None:
            ocr_text = None
            if g.get('ocr_b64'):
                import base64
                ocr_text = base64.b64decode(g['ocr_b64']).decode('utf-8')
            elements.append(Image(src=g['img_url'], alt=g.get('img_alt', ''), title=g.get('img_title'), extracted_text=ocr_text))
        elif g.get('link_url') is not None:
            link = Link(url=g['link_url'], title=g.get('link_title'), content=parse_inline(g['link_text']))
            elements.append(link)
        elif g.get('codeinline') is not None:
            elements.append(CodeInline(code=g['code_content']))
        elif g.get('linebreak') is not None:
            from ..ast import LineBreak
            elements.append(LineBreak())
            
        pos = m.end()
        
    return elements
