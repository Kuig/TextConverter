"""LaTeX source before parsing: code hidden, comments dropped, files included, the author's macros expanded.

``prepare_source`` runs these passes in the order TeX itself would see them,
so the parser only meets text whose literal parts are out of its way.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from ..logger import log_warning
from ._latex_macros import find_balanced_braces

# The URL argument of \url and \href, where "%" is literal rather than a comment: it
# stands in a private-use character until the link is built.
URL_PERCENT = '\ue000'
_URL_ARG = re.compile(r'\\(?:url|href)\{[^{}]*\}')
_OPTIONS = r'(?:\[(?:[^\]\n{}]|\{[^{}\n]*\})*\])'
# A code environment, with the "% language: x" line the LaTeX renderer writes above a verbatim.
_CODE_ENV = re.compile(
    r'(?:^[ \t]*%[ \t]*language:[ \t]*(?P<language>\S+)[ \t]*\n[ \t]*)?'
    r'\\begin\{(?P<env>verbatim\*?|lstlisting|minted|Verbatim\*?|BVerbatim\*?)\}'
    rf'(?P<head>(?:{_OPTIONS}|\{{[^{{}}\n]*\}})*)(?P<body>.*?)\\end\{{(?P=env)\}}',
    re.DOTALL | re.MULTILINE)
_CODE_MACRO = re.compile(rf'\\(?:verb\*?|lstinline{_OPTIONS}?|mintinline{_OPTIONS}?\{{[^{{}}\n]*\}})(?![a-zA-Z])')
_LANGUAGE = re.compile(r'language\s*=\s*\{?([\w+#-]+)')
_CAPTION = re.compile(r'caption\s*=\s*(?:\{((?:[^{}]|\{[^{}]*\})*)\}|([^,\]]+))')
_COMMENT = re.compile(r'(?<!\\)%.*$', re.MULTILINE)
_INPUT = re.compile(r'\\(?:input|include)(?![a-zA-Z])\s*(?:\{([^{}\n]+)\}|([\w./-]+))')
_COMMENT_ENV = re.compile(r'\\begin\{comment\}.*?\\end\{comment\}', re.DOTALL)
_MATH_ENV = re.compile(r'\\begin\{math\}(.*?)\\end\{math\}', re.DOTALL)
_IF_FALSE = re.compile(r'\\iffalse(?![a-zA-Z@])')
# \iff is the math symbol and \ifthenelse a command with arguments: neither is closed by \fi.
_CONDITIONAL = re.compile(
    r'\\(?:(?P<open>if(?!f(?![a-zA-Z])|thenelse)[a-zA-Z@]*)|(?P<else>else)|(?P<close>fi))(?![a-zA-Z@])')
_CONTROL_WORD = re.compile(r'\\[a-zA-Z]+')
_NEW_COMMAND = re.compile(
    r'\\(?:(?:re)?newcommand|providecommand|DeclareRobustCommand)\*?\s*(?:\{\s*\\([a-zA-Z@]+)\s*\}|\\([a-zA-Z@]+))'
    r'\s*(?:\[(\d)\])?\s*(?:\[([^\]]*)\])?\s*(?=\{)')
_DEF = re.compile(r'\\(?:def|gdef|edef)\s*\\([a-zA-Z@]+)([^{]*)(?=\{)')
_MATH_OPERATOR = re.compile(r'\\DeclareMathOperator\*?\s*\{\s*\\([a-zA-Z@]+)\s*\}\s*(?=\{)')
_FOOTNOTE_MARK = re.compile(r'\\footnotemark(?:\[[^\]]*\])?(?:\{\})?')
_FOOTNOTE_TEXT = re.compile(r'\\footnotetext(?:\[[^\]]*\])?\s*(?=\{)')
_MAX_DEPTH = 16
_MAX_GROWTH = 100


@dataclass
class HiddenCode:
    """A code environment taken out of the source: ``\\begin{verbatim}`` holds its index."""
    code: str
    language: str | None = None
    caption: str | None = None


def code_placeholder(index: int) -> str:
    return f"\\begin{{verbatim}}\x00{index}\x00\\end{{verbatim}}"


def _hide_environment(m: re.Match, hidden: list[HiddenCode]) -> str:
    head = m.group('head')
    language = m.group('language')
    if m.group('env') == 'minted':
        name = re.search(r'\{([^{}]*)\}', re.sub(_OPTIONS, '', head))
        language = name.group(1).lower() if name else language
    elif (found := _LANGUAGE.search(head)) is not None:
        language = found.group(1).lower()
    caption = _CAPTION.search(head)
    text = next((g for g in caption.groups() if g is not None), None) if caption else None
    hidden.append(HiddenCode(code=m.group('body').strip('\n').rstrip(), language=language, caption=text))
    return code_placeholder(len(hidden) - 1)


def _hide_inline(text: str) -> str:
    r"""``\verb|x|`` and its kin as ``\tcverbatim{hex}``: nothing in them can look like LaTeX anymore."""
    out: list[str] = []
    pos = 0
    while (m := _CODE_MACRO.search(text, pos)) is not None:
        start = m.end()
        if start >= len(text):
            break
        if text[start] == '{' and not m.group(0).startswith('\\verb'):
            code, end = find_balanced_braces(text, start)
        else:
            close = text.find(text[start], start + 1)
            newline = text.find('\n', start)
            if close == -1 or (newline != -1 and newline < close):
                pos = start
                continue
            code, end = text[start + 1:close], close + 1
        out.append(text[pos:m.start()] + f"\\tcverbatim{{{code.encode('utf-8').hex()}}}")
        pos = end
    return ''.join(out) + text[pos:]


def _prepare_text(text: str, hidden: list[HiddenCode]) -> str:
    """Hide the code of a source, then drop its comments."""
    text = _CODE_ENV.sub(lambda m: _hide_environment(m, hidden), text)
    text = _hide_inline(text)
    text = _URL_ARG.sub(lambda m: m.group(0).replace('%', URL_PERCENT), text)
    return _COMMENT.sub('', text)


def _readable(name: str, source: str) -> str | None:
    """The file ``\\input{name}`` means, when it is a ``.tex`` file in the folder of ``source`` or below it."""
    root = os.path.dirname(os.path.realpath(source))
    name = name.strip()
    path = os.path.realpath(os.path.join(root, name if os.path.splitext(name)[1] else name + ".tex"))
    try:
        inside = os.path.commonpath([root, path]) == root
    except ValueError:  # another drive
        inside = False
    return path if inside and path.lower().endswith(".tex") and os.path.isfile(path) else None


def _include(text: str, source: str | None, hidden: list[HiddenCode], stack: list[str], missing: list[str]) -> str:
    """``text`` with its ``\\input`` and ``\\include`` replaced by the files they name, or removed.

    Paths resolve from the main file, as in TeX. Only ``.tex`` files in its
    folder or below are read: a document cannot pull in any other file.
    """
    def repl(m: re.Match) -> str:
        name = m.group(1) or m.group(2)
        path = _readable(name, source) if source else None
        if path is None or path in stack or len(stack) >= _MAX_DEPTH:
            missing.append(name.strip())
            return ''
        with open(path, encoding='utf-8', errors='replace') as f:
            included = _prepare_text(f.read(), hidden)
        return _include(included, source, hidden, [*stack, path], missing)

    return _INPUT.sub(repl, text)


def _drop_conditionals(text: str) -> str:
    r"""Remove ``\iffalse ... \fi``, keeping what an ``\else`` of its own opens; inner conditionals nest."""
    out: list[str] = []
    pos = 0
    while (start := _IF_FALSE.search(text, pos)) is not None:
        out.append(text[pos:start.start()])
        depth, keep_from, end = 1, None, None
        for m in _CONDITIONAL.finditer(text, start.end()):
            if m.group('open'):
                depth += 1
            elif m.group('close'):
                depth -= 1
                if depth == 0:
                    end = m
                    break
            elif depth == 1 and keep_from is None:
                keep_from = m.end()
        if end is None:  # unclosed: TeX would skip all that follows
            stop = text.find('\\end{document}', start.end())
            pos = stop if stop != -1 else len(text)
            continue
        if keep_from is not None:
            out.append(text[keep_from:end.start()])
        pos = end.end()
    return ''.join(out) + text[pos:]


def _pair_footnotes(text: str) -> str:
    r"""Move each ``\footnotetext{...}`` to its ``\footnotemark``, in order; a text without a mark stays in place."""
    marks = list(_FOOTNOTE_MARK.finditer(text))
    notes = []
    pos = 0
    kept: list[str] = []
    for m in _FOOTNOTE_TEXT.finditer(text):
        if len(notes) >= len(marks):
            break
        body, end = find_balanced_braces(text, m.end())
        notes.append(body)
        kept.append(text[pos:m.start()])
        pos = end
    if not notes:
        return text
    text = ''.join(kept) + text[pos:]
    remaining = iter(notes)
    return _FOOTNOTE_MARK.sub(lambda m: f"\\footnote{{{next(remaining, '')}}}", text)


@dataclass
class _Definition:
    body: str
    arguments: int = 0
    default: str | None = None


def _take_definitions(text: str) -> tuple[str, dict[str, _Definition], list[str]]:
    """Remove the macro definitions of the source; return it, the definitions and the ones that cannot be used."""
    definitions: dict[str, _Definition] = {}
    unsupported: list[str] = []
    found = sorted(((kind, m) for kind, regex in (("new", _NEW_COMMAND), ("def", _DEF), ("op", _MATH_OPERATOR))
                    for m in regex.finditer(text)), key=lambda pair: pair[1].start())
    out: list[str] = []
    pos = 0
    for kind, m in found:
        start = m.start()
        if start < pos:
            continue
        body, stop = find_balanced_braces(text, m.end())
        name = m.group(1) or m.group(2) if kind == "new" else m.group(1)
        if kind == "new":
            definitions[name] = _Definition(body, int(m.group(3) or 0), m.group(4))
        elif kind == "op":
            definitions[name] = _Definition(f"\\operatorname{{{body}}}")
        elif re.fullmatch(r'\s*(?:#\d\s*)*', m.group(2)):
            definitions[name] = _Definition(body, m.group(2).count('#'))
        else:
            unsupported.append(f"\\{name}")
        out.append(text[pos:start])
        pos = stop
    return ''.join(out) + text[pos:], definitions, unsupported


def _argument(text: str, pos: int) -> tuple[str, int] | None:
    """The argument at ``pos``: a ``{...}`` group, a control word or one character."""
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text):
        return None
    if text[pos] == '{':
        return find_balanced_braces(text, pos)
    word = _CONTROL_WORD.match(text, pos)
    if word:
        return word.group(0), word.end()
    return text[pos], pos + 1


def _expansion(definition: _Definition, text: str, pos: int) -> tuple[str, int] | None:
    """What a macro whose name ends at ``pos`` stands for and the position after its arguments."""
    arguments: list[str] = []
    wanted = definition.arguments
    if definition.default is not None:
        wanted -= 1
        if text.startswith('[', pos):
            close = text.find(']', pos)
            arguments.append(text[pos + 1:close])
            pos = close + 1
        else:
            arguments.append(definition.default)
    for _ in range(wanted):
        argument = _argument(text, pos)
        if argument is None:
            return None
        arguments.append(argument[0])
        pos = argument[1]
    body = re.sub(r'#(\d)', lambda m: arguments[int(m.group(1)) - 1] if int(m.group(1)) <= len(arguments) else '',
                  definition.body)
    if not definition.arguments:
        if text.startswith('{}', pos):
            pos += 2
        else:
            while pos < len(text) and text[pos] in ' \t':
                pos += 1
    if re.search(r'\\[a-zA-Z]+$', body) and pos < len(text) and text[pos].isalpha():
        body += ' '  # the next letter is not part of the command
    return body, pos


def _expand(text: str, definitions: dict[str, _Definition]) -> str:
    """Expand the macros until none is left, or until a recursive definition shows it never ends."""
    if not definitions:
        return text
    names = re.compile(r'\\(' + '|'.join(re.escape(n) for n in sorted(definitions, key=len, reverse=True)) + r')(?![a-zA-Z@])')
    limit = len(text) * _MAX_GROWTH + 1_000_000
    for _ in range(_MAX_DEPTH):
        out: list[str] = []
        pos = 0
        changed = False
        while (m := names.search(text, pos)) is not None:
            expansion = _expansion(definitions[m.group(1)], text, m.end())
            if expansion is None:
                break
            out.append(text[pos:m.start()] + expansion[0])
            pos = expansion[1]
            changed = True
        text = ''.join(out) + text[pos:]
        if not changed or len(text) > limit:
            return text
    return text


def prepare_source(text: str, source: str | None = None) -> tuple[str, list[HiddenCode]]:
    """Run the passes that come before parsing.

    Args:
        text: The LaTeX source.
        source: Its path; without one ``\\input`` reads nothing.

    Returns:
        The source to parse and the code taken out of it.
    """
    hidden: list[HiddenCode] = []
    missing: list[str] = []
    stack = [os.path.realpath(source)] if source else []
    text = _include(_prepare_text(text, hidden), source, hidden, stack, missing)
    if missing:
        log_warning(f"LaTeX files not included: {', '.join(dict.fromkeys(missing))}. Only .tex files in the "
                    "folder of the source or below it are read.")
    text = _COMMENT_ENV.sub('', text)
    text = _drop_conditionals(text)
    text = _MATH_ENV.sub(lambda m: f"\\({m.group(1)}\\)", text)
    text, definitions, unsupported = _take_definitions(text)
    if unsupported:
        log_warning(f"LaTeX macros not expanded (their parameters are delimited): {', '.join(unsupported)}.")
    return _pair_footnotes(_expand(text, definitions)), hidden
