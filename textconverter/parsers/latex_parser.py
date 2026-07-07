import re
from typing import List

from ..ast import (
    Document, Paragraph, Heading, Text, Link, Image, CodeInline,
    CodeBlock, ListBlock, ListItem, Table, TableRow, TableCell, InlineElement,
    BlockQuote, Equation
)

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


def _find_balanced_braces(text: str, start_pos: int) -> tuple[str, int]:
    """Finds the content enclosed in balanced curly braces starting from start_pos.
    
    Returns a tuple of (content_inside, index_after_closing_brace).
    If braces are not balanced or not found, returns ("", start_pos).
    """
    brace_start = text.find('{', start_pos)
    if brace_start == -1:
        return "", start_pos
        
    depth = 0
    content_chars = []
    i = brace_start
    while i < len(text):
        char = text[i]
        if char == '{':
            if depth > 0:
                content_chars.append(char)
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return "".join(content_chars), i + 1
            content_chars.append(char)
        else:
            if depth > 0:
                content_chars.append(char)
        i += 1
    return "".join(content_chars), len(text)


def _extract_macro_args(text: str, macro_name: str, start_pos: int = 0) -> tuple[list[str], int, int]:
    """Finds the first occurrence of macro_name in text after start_pos and extracts its arguments.
    
    A macro can have one or more consecutive {...} argument blocks.
    Returns:
        (args_list, macro_start_index, macro_end_index)
        If not found, returns ([], -1, -1).
    """
    pos = text.find(macro_name, start_pos)
    if pos == -1:
        return [], -1, -1
        
    # Check if there is an opening brace following the macro name (possibly with spaces/newline)
    idx = pos + len(macro_name)
    
    # Skip optional parameter [...] if present
    if idx < len(text) and text[idx] == '[':
        end_opt = text.find(']', idx)
        if end_opt != -1:
            idx = end_opt + 1
            
    args = []
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
            
        if idx < len(text) and text[idx] == '{':
            content, next_idx = _find_balanced_braces(text, idx)
            args.append(content)
            idx = next_idx
        else:
            break
            
    return args, pos, idx


def _strip_macro(text: str, macro_name: str, num_args: int = 1) -> str:
    """Finds all occurrences of macro_name and strips them out along with their arguments."""
    pos = 0
    while True:
        args, start, end = _extract_macro_args(text, macro_name, pos)
        if start == -1:
            break
        text = text[:start] + text[end:]
        pos = start
    return text


def _extract_environment(text: str, env_name: str, start_pos: int = 0) -> tuple[str, int, int]:
    """Finds the first occurrence of \\begin{env_name} ... \\end{env_name} in text.
    
    Returns (env_content, begin_index, end_index).
    If not found, returns ("", -1, -1).
    """
    begin_str = f"\\begin{{{env_name}}}"
    end_str = f"\\end{{{env_name}}}"
    
    start_idx = text.find(begin_str, start_pos)
    if start_idx == -1:
        return "", -1, -1
        
    end_idx = text.find(end_str, start_idx + len(begin_str))
    if end_idx == -1:
        return "", -1, -1
        
    content = text[start_idx + len(begin_str) : end_idx]
    
    # Strip any leading braced environment configuration arguments, e.g. {p{4cm} p{4cm}}
    idx = 0
    while idx < len(content) and content[idx].isspace():
        idx += 1
    if idx < len(content) and content[idx] == '{':
        _, next_idx = _find_balanced_braces(content, idx)
        content = content[next_idx:]
        
    return content, start_idx, end_idx + len(end_str)

def parse_latex(text: str) -> Document:
    """Parses a basic subset of LaTeX into AST Document."""
    doc = Document()

    # Strip comments first so that they are not included in metadata extraction
    text = re.sub(r'(?<!\\)%.*$', '', text, flags=re.MULTILINE)

    # Strip custom two-column layouts and wrappers
    text = re.sub(r'\\twocolumn\s*\[', '', text)
    text = text.replace('\\begin{@twocolumnfalse}', '')
    text = re.sub(r'\\end\{@twocolumnfalse\}\s*\]', '', text)
    text = text.replace('\\end{@twocolumnfalse}', '')

    # Strip layout and styling commands first so they are cleaned from metadata too
    text = _strip_macro(text, "\\fontsize")
    for cmd in ["\\thispagestyle", "\\pubyear", "\\pagerange", "\\vspace", "\\hspace", "\\pageref", "\\bibliographystyle", "\\bibliography"]:
        text = _strip_macro(text, cmd)
        
    for cmd in ["\\selectfont", "\\balance", "\\noindent", "\\raggedright", "\\justifying", "\\centering", "\\hfill", "\\maketitle", "\\printbibliography", "\\appendix"]:
        text = re.sub(re.escape(cmd) + r'\b', '', text)

    # Extract \title{...}, \author{...}, \date{...} (now clean of layout commands)
    title_text = None
    args_title, _, _ = _extract_macro_args(text, "\\title")
    if args_title:
        title_text = args_title[0].strip()

    author_text = None
    args_author, _, _ = _extract_macro_args(text, "\\author")
    if args_author:
        author_text = args_author[0].strip()

    date_text = None
    args_date, _, _ = _extract_macro_args(text, "\\date")
    if args_date:
        date_text = args_date[0].strip()

    # Strip out preamble if document environment exists
    m_doc = re.search(r'\\begin\{document\}(.*?)\\end\{document\}', text, re.DOTALL)
    if m_doc:
        text = m_doc.group(1)

    pos = 0
    targets = [
        ('\\section', 'section'),
        ('\\subsection', 'subsection'),
        ('\\subsubsection', 'subsubsection'),
        ('\\paragraph', 'paragraph'),
        ('\\begin{abstract}', 'abstract'),
        ('\\begin{itemize}', 'itemize'),
        ('\\begin{enumerate}', 'enumerate'),
        ('\\begin{verbatim}', 'verbatim'),
        ('\\begin{lstlisting}', 'lstlisting'),
        ('\\begin{tabular}', 'tabular'),
        ('\\begin{figure}', 'figure'),
        ('\\begin{figure*}', 'figure*'),
        ('\\begin{table}', 'table'),
        ('\\begin{table*}', 'table*'),
        ('\\begin{equation}', 'equation'),
        ('\\begin{align}', 'align'),
        ('\\begin{displaymath}', 'displaymath'),
        ('\\begin{keywords}', 'keywords')
    ]
    
    # Pre-populate title, author, date in doc
    if title_text:
        doc.children.append(Heading(level=1, children=parse_inline_latex(title_text, is_bold=True)))
    if author_text:
        doc.children.append(Paragraph(children=parse_inline_latex(author_text)))
    if date_text:
        doc.children.append(Paragraph(children=parse_inline_latex(date_text)))
        
    while pos < len(text):
        first_pos = -1
        first_type = None
        first_cmd = None
        
        for cmd, t_type in targets:
            idx = text.find(cmd, pos)
            if idx != -1:
                # Ensure boundary (not followed by alphabetic characters)
                if cmd.startswith('\\') and not cmd.endswith('}'):
                    next_char_idx = idx + len(cmd)
                    if next_char_idx < len(text) and text[next_char_idx].isalpha():
                        continue
                if first_pos == -1 or idx < first_pos:
                    first_pos = idx
                    first_type = t_type
                    first_cmd = cmd
                    
        if first_pos == -1:
            # Parse remaining text as plain blocks
            chunk = text[pos:].strip()
            if chunk:
                for p_text in re.split(r'\n\s*\n', chunk):
                    if p_text.strip():
                        doc.children.append(Paragraph(children=parse_inline_latex(p_text.strip())))
            break
            
        if first_pos > pos:
            # Parse text leading up to the match
            chunk = text[pos:first_pos].strip()
            if chunk:
                for p_text in re.split(r'\n\s*\n', chunk):
                    if p_text.strip():
                        doc.children.append(Paragraph(children=parse_inline_latex(p_text.strip())))
                        
        # Process block target
        if first_type in ('section', 'subsection', 'subsubsection', 'paragraph'):
            cmd_len = len(first_cmd)
            is_starred = False
            if first_pos + cmd_len < len(text) and text[first_pos + cmd_len] == '*':
                cmd_name = first_cmd + '*'
            else:
                cmd_name = first_cmd
                
            args, start, end = _extract_macro_args(text, cmd_name, first_pos)
            if start != -1 and args:
                level = {'section': 1, 'subsection': 2, 'subsubsection': 3, 'paragraph': 4}.get(first_type, 1)
                doc.children.append(Heading(level=level, children=parse_inline_latex(args[0])))
                pos = end
            else:
                pos = first_pos + len(cmd_name)
                
        elif first_type == 'abstract':
            content, start, end = _extract_environment(text, 'abstract', first_pos)
            if start != -1:
                abstract_bq = BlockQuote()
                abstract_bq.children.append(Heading(level=2, children=[Text(content="Abstract")]))
                for p_text in re.split(r'\n\s*\n', content.strip()):
                    if p_text.strip():
                        abstract_bq.children.append(Paragraph(children=parse_inline_latex(p_text.strip())))
                doc.children.append(abstract_bq)
                pos = end
            else:
                pos = first_pos + len(first_cmd)
                
        elif first_type in ('itemize', 'enumerate'):
            content, start, end = _extract_environment(text, first_type, first_pos)
            if start != -1:
                ordered = (first_type == 'enumerate')
                lb = ListBlock(ordered=ordered)
                items = re.split(r'\\item', content)
                for item in items[1:]:
                    lb.items.append(ListItem(children=[Paragraph(children=parse_inline_latex(item.strip()))]))
                doc.children.append(lb)
                pos = end
            else:
                pos = first_pos + len(first_cmd)
                
        elif first_type in ('verbatim', 'lstlisting'):
            content, start, end = _extract_environment(text, first_type, first_pos)
            if start != -1:
                doc.children.append(CodeBlock(code=content.strip(), language=None))
                pos = end
            else:
                pos = first_pos + len(first_cmd)
                
        elif first_type == 'tabular':
            content, start, end = _extract_environment(text, 'tabular', first_pos)
            if start != -1:
                doc.children.append(_parse_latex_table(content.strip()))
                pos = end
            else:
                pos = first_pos + len(first_cmd)
                
        elif first_type in ('figure', 'figure*'):
            env_name = first_type
            content, start, end = _extract_environment(text, env_name, first_pos)
            if start != -1:
                img_args, img_start, img_end = _extract_macro_args(content, "\\includegraphics")
                cap_args, cap_start, cap_end = _extract_macro_args(content, "\\caption")
                caption_text = cap_args[0].strip() if cap_args else None
                
                if img_args:
                    img_src = img_args[0].strip()
                    doc.children.append(Image(src=img_src, alt="image"))
                    if caption_text:
                        doc.children.append(Paragraph(children=parse_inline_latex(f"Figure: {caption_text}")))
                elif caption_text:
                    doc.children.append(Paragraph(children=parse_inline_latex(f"Figure: {caption_text}")))
                pos = end
            else:
                pos = first_pos + len(first_cmd)
                
        elif first_type in ('table', 'table*'):
            env_name = first_type
            content, start, end = _extract_environment(text, env_name, first_pos)
            if start != -1:
                tab_content, tab_start, tab_end = _extract_environment(content, "tabular")
                cap_args, cap_start, cap_end = _extract_macro_args(content, "\\caption")
                caption_text = cap_args[0].strip() if cap_args else None
                
                if caption_text:
                    doc.children.append(Paragraph(children=parse_inline_latex(f"Table: {caption_text}")))
                if tab_start != -1:
                    doc.children.append(_parse_latex_table(tab_content.strip()))
                pos = end
            else:
                pos = first_pos + len(first_cmd)
                
        elif first_type in ('equation', 'align', 'displaymath'):
            content, start, end = _extract_environment(text, first_type, first_pos)
            if start != -1:
                doc.children.append(Equation(code=content.strip(), inline=False))
                pos = end
            else:
                pos = first_pos + len(first_cmd)
                
        elif first_type == 'keywords':
            content, start, end = _extract_environment(text, 'keywords', first_pos)
            if start != -1:
                doc.children.append(Paragraph(children=[Text(content="Keywords: ", bold=True)] + parse_inline_latex(content.strip())))
                pos = end
            else:
                pos = first_pos + len(first_cmd)

    return doc

def _parse_latex_table(content: str) -> Table:
    table = Table()
    content = content.replace('\\toprule', '').replace('\\midrule', '').replace('\\bottomrule', '')
    rows = content.split('\\\\')

    for i, row in enumerate(rows):
        row = row.replace('\\hline', '').strip()
        if not row:
            continue
        cells = [c.strip() for c in row.split('&')]

        if i == 0:
            table.headers = [TableCell(children=parse_inline_latex(c)) for c in cells]
        else:
            table.rows.append(TableRow(cells=[TableCell(children=parse_inline_latex(c)) for c in cells]))

    return table

def parse_inline_latex(text: str, is_bold: bool = False, is_italic: bool = False) -> List[InlineElement]:
    elements = []
    pos = 0
    
    while pos < len(text):
        m = re.search(r'(\\|\$)', text[pos:])
        if not m:
            # No more commands, parse plain text
            plain = _normalize_latex_quotes(text[pos:])
            if plain:
                elements.append(Text(content=plain, bold=is_bold, italic=is_italic))
            break
            
        idx = pos + m.start()
        
        if idx > pos:
            # Text leading up to the backslash or dollar
            plain = _normalize_latex_quotes(text[pos:idx])
            if plain:
                elements.append(Text(content=plain, bold=is_bold, italic=is_italic))
            pos = idx
            
        # Handle $ and $$
        if text[pos] == '$':
            if pos + 1 < len(text) and text[pos + 1] == '$':
                # Block math
                end_idx = text.find('$$', pos + 2)
                if end_idx != -1:
                    code = text[pos + 2:end_idx].strip()
                    elements.append(Equation(code=code, inline=False))
                    pos = end_idx + 2
                else:
                    elements.append(Text(content="$$", bold=is_bold, italic=is_italic))
                    pos += 2
            else:
                # Inline math
                end_idx = text.find('$', pos + 1)
                # Ensure we don't match \$
                while end_idx != -1 and text[end_idx - 1] == '\\':
                    end_idx = text.find('$', end_idx + 1)
                if end_idx != -1:
                    code = text[pos + 1:end_idx].strip()
                    elements.append(Equation(code=code, inline=True))
                    pos = end_idx + 1
                else:
                    elements.append(Text(content="$", bold=is_bold, italic=is_italic))
                    pos += 1
            continue

        # Now text[pos] is '\\'. Let's see what follows it.
        if pos + 1 >= len(text):
            elements.append(Text(content='\\', bold=is_bold, italic=is_italic))
            break
            
        next_char = text[pos + 1]
        
        # Math Environments: \( ... \) and \[ ... \]
        if next_char == '(':
            end_idx = text.find('\\)', pos + 2)
            if end_idx != -1:
                code = text[pos + 2:end_idx].strip()
                elements.append(Equation(code=code, inline=True))
                pos = end_idx + 2
            else:
                elements.append(Text(content="\\(", bold=is_bold, italic=is_italic))
                pos += 2
            continue
            
        if next_char == '[':
            end_idx = text.find('\\]', pos + 2)
            if end_idx != -1:
                code = text[pos + 2:end_idx].strip()
                elements.append(Equation(code=code, inline=False))
                pos = end_idx + 2
            else:
                elements.append(Text(content="\\[", bold=is_bold, italic=is_italic))
                pos += 2
            continue
        
        # 1. Line breaks: \\ or \\[...]
        if next_char == '\\':
            from ..ast import LineBreak
            elements.append(LineBreak())
            # Check for \\[1ex] or similar optional parameter
            pos += 2
            if pos < len(text) and text[pos] == '[':
                end_opt = text.find(']', pos)
                if end_opt != -1:
                    pos = end_opt + 1
            continue
            
        # 2. Escaped characters: \%, \&, \$, \_, \#, \{, \}
        if next_char in ('%', '&', '$', '_', '#', '{', '}'):
            elements.append(Text(content=next_char, bold=is_bold, italic=is_italic))
            pos += 2
            continue
            
        # 3. Macro command starting with letters
        m = re.match(r'^\\([a-zA-Z]+)\*?', text[pos:])
        if not m:
            elements.append(Text(content='\\', bold=is_bold, italic=is_italic))
            pos += 1
            continue
            
        cmd_name = m.group(0) # e.g. \textbf or \cite
        cmd_base = m.group(1) # e.g. textbf or cite
        
        # Check if it is a safeguarded macro: cite, citet, citet*, citet, citet*, ref, label
        if cmd_base in ('cite', 'citet', 'citep', 'ref', 'label'):
            args, start, end = _extract_macro_args(text, cmd_name, pos)
            if start != -1:
                # Include the macro and its arguments as plain text verbatim
                elements.append(Text(content=text[start:end], bold=is_bold, italic=is_italic))
                pos = end
            else:
                elements.append(Text(content=cmd_name, bold=is_bold, italic=is_italic))
                pos += len(cmd_name)
            continue
            
        # Check if it is a known inline style command
        if cmd_base in ('textbf', 'textit', 'texttt', 'href', 'url', 'includegraphics'):
            args, start, end = _extract_macro_args(text, cmd_name, pos)
            if start != -1 and args:
                if cmd_base == 'textbf':
                    elements.extend(parse_inline_latex(args[0], is_bold=True, is_italic=is_italic))
                elif cmd_base == 'textit':
                    elements.extend(parse_inline_latex(args[0], is_bold=is_bold, is_italic=True))
                elif cmd_base == 'texttt':
                    elements.append(CodeInline(code=args[0]))
                elif cmd_base == 'href':
                    if len(args) >= 2:
                        elements.append(Link(url=args[0], title=None, content=parse_inline_latex(args[1], is_bold=is_bold, is_italic=is_italic)))
                    elif len(args) == 1:
                        elements.append(Link(url=args[0], title=None, content=[Text(content=args[0], bold=is_bold, italic=is_italic)]))
                elif cmd_base == 'url':
                    elements.append(Link(url=args[0], title=None, content=[Text(content=args[0], bold=is_bold, italic=is_italic)]))
                elif cmd_base == 'includegraphics':
                    elements.append(Image(src=args[0], alt="image"))
                pos = end
            else:
                elements.append(Text(content=cmd_name, bold=is_bold, italic=is_italic))
                pos += len(cmd_name)
            continue
            
        # 4. Any other unrecognized macro command
        args, start, end = _extract_macro_args(text, cmd_name, pos)
        if start != -1:
            if args:
                # Replace command with its recursively parsed argument content
                elements.extend(parse_inline_latex(args[0], is_bold=is_bold, is_italic=is_italic))
            pos = end
        else:
            # 0-argument command -> strip it completely
            pos += len(cmd_name)
            
    return elements

