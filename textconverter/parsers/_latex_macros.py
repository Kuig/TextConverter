"""LaTeX macro parsing shared by the LaTeX and Markdown parsers.

Markdown sources keep footnotes, citations and cross-references as LaTeX
macros (the renderers write them that way), so both parsers read them here.
"""
from __future__ import annotations

from collections.abc import Callable

from ..ast import Citation, Footnote, Label, Node, Reference

# Macros kept as AST nodes; a trailing "*" (\citet*) is accepted and ignored.
REFERENCE_MACROS = ("footnote", "cite", "citet", "citep", "ref", "label")


def find_balanced_braces(text: str, start_pos: int) -> tuple[str, int]:
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


def extract_macro_args(text: str, macro_name: str, start_pos: int = 0) -> tuple[list[str], int, int]:
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
        saved_idx = idx
        while idx < len(text) and text[idx].isspace():
            idx += 1
            
        if idx < len(text) and text[idx] == '{':
            content, next_idx = find_balanced_braces(text, idx)
            args.append(content)
            idx = next_idx
        else:
            idx = saved_idx
            break
            
    return args, pos, idx


def parse_reference_macro(
    text: str, pos: int, cmd_name: str, parse_inline: Callable[[str], list[Node]]
) -> tuple[Node | None, int]:
    """Parse a reference macro (``REFERENCE_MACROS``) found at ``pos``.

    Args:
        text: The text being parsed.
        pos: Index of the macro's backslash.
        cmd_name: The macro as written, e.g. ``\\citet*``.
        parse_inline: Parses a footnote's content (with the caller's formatting).

    Returns:
        ``(node, end)``; ``node`` is None when the macro has no argument, and
        ``end`` then points just past the macro name.
    """
    base = cmd_name[1:].rstrip("*")
    args, start, end = extract_macro_args(text, cmd_name, pos)
    if start != pos or not args:
        return None, pos + len(cmd_name)
    if base == "footnote":
        return Footnote(content=parse_inline(args[0])), end
    if base in ("cite", "citet", "citep"):
        return Citation(keys=[k.strip() for k in args[0].split(",") if k.strip()], style=base), end
    if base == "ref":
        return Reference(label=args[0].strip()), end
    return Label(name=args[0].strip()), end
