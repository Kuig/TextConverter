"""LaTeX macro parsing shared by the LaTeX, Markdown, HTML and Word parsers.

Markdown, HTML and Word sources keep footnotes, citations and cross-references
as LaTeX macros (the renderers write them that way), so the parsers read them here.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace

from ..ast import BibEntry, Bibliography, Citation, Document, Footnote, Label, Node, Paragraph, Reference, Text

# The citation macros of LaTeX, natbib and biblatex.
CITATION_MACROS = (
    "cite", "citet", "citep", "citealt", "citealp", "citeauthor", "citeyear", "citeyearpar", "citetitle", "nocite",
    "cites", "Cite", "Citet", "Citep", "parencite", "Parencite", "autocite", "Autocite", "textcite", "Textcite",
    "footcite",
)
# The cross-reference macros of LaTeX, amsmath, hyperref, cleveref and varioref.
REFERENCE_FAMILY = ("ref", "eqref", "pageref", "autoref", "cref", "Cref", "nameref", "vref", "hyperref")
# Macros kept as AST nodes, stars included: \citet* comes back as \citet*.
REFERENCE_MACROS = ("footnote", *CITATION_MACROS, *REFERENCE_FAMILY, "label")
REFERENCE_MACRO = re.compile(rf'\\(?:{"|".join(REFERENCE_MACROS)})\*?(?![a-zA-Z])')
# The commands that point to a bibliography, as they stand on a line of their own.
BIBLIOGRAPHY_COMMAND = re.compile(
    r'\\(?:bibliographystyle|bibliography|addbibresource|printbibliography)(?![a-zA-Z])(?:\[[^\]\n]*\])?(?:\{[^{}\n]*\})?')
_ONLY_COMMANDS = re.compile(rf'\s*(?:{BIBLIOGRAPHY_COMMAND.pattern}\s*)+$')
_BIB_ITEM = re.compile(r'\s*\\bibitem(?:\[([^\]\n]*)\])?\{([^{}\n]*)\}\s*')
_BIB_BEGIN = re.compile(r'\s*\\begin\{thebibliography\}\{([^{}\n]*)\}\s*$')
_BIB_END = re.compile(r'\s*\\end\{thebibliography\}\s*$')


def find_balanced_braces(text: str, start_pos: int) -> tuple[str, int]:
    """Finds the content enclosed in balanced curly braces starting from start_pos.

    An escaped brace (``\\{``, ``\\}``) is content, not a delimiter.

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
        if char == '\\' and depth > 0:
            content_chars.append(text[i:i + 2])
            i += 2
            continue
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
    
    # Skip the optional parameters, e.g. \citep[e.g.][p. 3]{key}
    while idx < len(text) and text[idx] == '[':
        end_opt = text.find(']', idx)
        if end_opt == -1:
            break
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


def _optional_args(text: str, idx: int) -> tuple[list[str], int]:
    """The ``[...]`` arguments starting at ``idx``, as written, and the position after them."""
    options = []
    while idx < len(text) and text[idx] == '[':
        close = text.find(']', idx)
        if close == -1:
            break
        options.append(text[idx + 1:close])
        idx = close + 1
    return options, idx


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
    style = cmd_name[1:]
    base = style.rstrip("*")
    args, start, end = extract_macro_args(text, cmd_name, pos)
    if start != pos or not args:
        return None, pos + len(cmd_name)
    options, idx = _optional_args(text, pos + len(cmd_name))
    if base != "cites":  # a {...} after the argument is the text's own
        end = find_balanced_braces(text, idx)[1]
    if base == "footnote":
        return Footnote(content=parse_inline(args[0])), end
    if base == "label":
        return Label(name=args[0].strip()), end
    if base == "cites":
        return Citation(keys=[a.strip() for a in args], style=style, options=options), end
    if base in CITATION_MACROS:
        return Citation(keys=[k.strip() for k in args[0].split(",") if k.strip()], style=style, options=options), end
    return Reference(label=args[0].strip(), style=style, options=options), end


def _plain(block: Node) -> str | None:
    """The text of a paragraph made of plain text only, else None."""
    if isinstance(block, Paragraph) and block.children and all(isinstance(n, Text) for n in block.children):
        return "".join(n.content for n in block.children)
    return None


def _entry(block: Node) -> BibEntry | None:
    """The ``\\bibitem`` a paragraph opens with, as an entry."""
    if not isinstance(block, Paragraph) or not block.children or not isinstance(block.children[0], Text):
        return None
    first = block.children[0]
    m = _BIB_ITEM.match(first.content)
    if m is None:
        return None
    rest = first.content[m.end():]
    return BibEntry(key=m.group(2), label=m.group(1),
                    children=[*([replace(first, content=rest)] if rest else []), *block.children[1:]])


def lift_bibliography(doc: Document) -> None:
    """Rebuild a ``Bibliography`` from the paragraphs of macros the renderers write for it.

    Formats without a construct of their own keep the bibliography visible as
    LaTeX, one command or entry per paragraph; a run of them becomes one node.
    """
    out: list[Node] = []
    current: Bibliography | None = None
    in_entries = False
    for block in doc.children:
        text = _plain(block)
        begin = _BIB_BEGIN.match(text) if text is not None else None
        if begin:
            current = current or Bibliography()
            current.widest = begin.group(1)
            in_entries = True
            if not out or out[-1] is not current:
                out.append(current)
        elif in_entries and text is not None and _BIB_END.match(text):
            in_entries = False
        elif in_entries and (entry := _entry(block)) is not None:
            current.entries.append(entry)
        elif text is not None and _ONLY_COMMANDS.match(text):
            current = current or Bibliography()
            current.commands.extend(m.group(0) for m in BIBLIOGRAPHY_COMMAND.finditer(text))
            if not out or out[-1] is not current:
                out.append(current)
        else:
            current, in_entries = None, False
            out.append(block)
    doc.children[:] = out


def lift_macros(nodes: list[Node]) -> list[Node]:
    """Turn reference macros written as text (``\\cite{a}``, ``\\footnote{...}``) into nodes.

    A footnote's content may span several formatted text nodes; a macro that
    does not parse stays text.
    """
    out: list[Node] = []
    i = 0
    while i < len(nodes):
        node = nodes[i]
        m = REFERENCE_MACRO.search(node.content) if isinstance(node, Text) else None
        if m is None:
            out.append(node)
            i += 1
            continue
        if m.start():
            out.append(replace(node, content=node.content[:m.start()]))
        rest = node.content[m.start():]
        name = m.group(0)
        if name.rstrip('*') == '\\footnote':
            lifted = _lift_footnote(nodes, i, replace(node, content=rest[len(name):]))
            if lifted is not None:
                footnote, i, tail = lifted
                out.append(footnote)
                if tail is not None:
                    nodes = [*nodes[:i], tail, *nodes[i:]]
                continue
        else:
            macro, end = parse_reference_macro(rest, 0, name, lambda arg: [Text(content=arg)])
            if macro is not None:
                out.append(macro)
                nodes = [*nodes[:i], replace(node, content=rest[end:]), *nodes[i + 1:]]
                if not rest[end:]:
                    i += 1
                continue
        out.append(replace(node, content=name))
        nodes = [*nodes[:i], replace(node, content=rest[len(name):]), *nodes[i + 1:]]
        if not rest[len(name):]:
            i += 1
    return out


def _lift_footnote(nodes: list[Node], i: int, first: Text) -> tuple[Footnote, int, Text | None] | None:
    """Read ``{...}`` from ``first`` (the text after ``\\footnote``) and the nodes after ``nodes[i]``.

    Returns ``(footnote, index of the next unread node, the text left after the
    closing brace)``, or None when the braces are not balanced.
    """
    if not first.content.startswith('{'):
        return None
    content: list[Node] = []
    depth = 0
    current: Node = first
    j = i
    while True:
        if isinstance(current, Text):
            text = current.content
            for k, ch in enumerate(text):
                depth += {'{': 1, '}': -1}.get(ch, 0)
                if depth == 0:
                    inner = text[1:k] if current is first else text[:k]
                    if inner:
                        content.append(replace(current, content=inner))
                    tail = text[k + 1:]
                    return Footnote(content=lift_macros(content)), j + 1, (
                        replace(current, content=tail) if tail else None)
            inner = text[1:] if current is first else text
            if inner:
                content.append(replace(current, content=inner))
        else:
            content.append(current)
        j += 1
        if j >= len(nodes):
            return None
        current = nodes[j]
