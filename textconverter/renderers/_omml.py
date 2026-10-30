"""LaTeX math to Office Math (OMML), for the equations of Word documents.

The inverse of ``parsers/_omml.py`` (whose symbol tables it shares): fractions,
scripts, radicals, n-ary operators, ``\\left...\\right`` delimiters, functions,
accents, bars, ``\\text``, matrices, ``cases`` and aligned equations. A formula
using anything else raises ``UnsupportedMath`` so the caller can keep it as text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from ..parsers._omml import ACCENTS, DELIMITERS, FUNCTIONS, M_NS, NARY, SYMBOLS

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_MATH_FONT = "Cambria Math"

_TOKEN = re.compile(r"\\[A-Za-z]+\*?|\\.|[{}^_&]|\s+|.", re.DOTALL)
_ROW_BREAK = "\\\\"
# Commands with no effect on the structure of a formula.
_IGNORED = frozenset({"\\limits", "\\nolimits", "\\displaystyle", "\\textstyle", "\\scriptstyle", "\\!"})
_ESCAPED = {"\\{": "{", "\\}": "}", "\\%": "%", "\\&": "&", "\\#": "#", "\\_": "_", "\\$": "$"}
_SPACES = {"\\,": "\u2009", "\\;": "\u2004", "\\:": "\u2005", "\\ ": " ", "\\quad": "\u2003",
           "\\qquad": "\u2003\u2003"}
_BLACKBOARD = {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ"}
_TEXT_COMMANDS = {"text": "nor", "textrm": "nor", "mbox": "nor", "mathrm": "p", "mathbf": "b",
                  "boldsymbol": "b", "mathit": None, "mathcal": None, "mathsf": None}
# Functions whose subscript goes under them, as in a limit.
_LIMIT_FUNCTIONS = frozenset({"lim", "limsup", "liminf", "max", "min", "sup", "inf"})
_MATRICES = {"matrix": ("", ""), "smallmatrix": ("", ""), "pmatrix": ("(", ")"), "bmatrix": ("[", "]"),
             "Bmatrix": ("{", "}"), "vmatrix": ("|", "|"), "Vmatrix": ("‖", "‖"), "array": ("", "")}
_ALIGNED = frozenset({"align", "align*", "aligned", "alignat", "gather", "gather*", "gathered", "split",
                      "multline", "multline*", "flalign", "flalign*", "eqnarray", "eqnarray*", "equation",
                      "equation*"})

# LaTeX command -> character, built from the tables the reader uses.
_COMMANDS: dict[str, str] = {}
for _char, _latex in SYMBOLS.items():
    if re.fullmatch(r"\\[A-Za-z]+", _latex):
        _COMMANDS.setdefault(_latex[1:], _char)
_COMMANDS.update({"le": "≤", "ge": "≥", "ne": "≠", "rightarrow": "→", "dots": "…", "lbrace": "{",
                  "rbrace": "}", "prime": "′", "cdotp": "·", "ast": "∗", "|": "‖"})
_NARY_COMMANDS = {latex[1:]: char for char, latex in NARY.items()}
_ACCENT_COMMANDS: dict[str, str] = {}
for _char, _latex in ACCENTS.items():
    _ACCENT_COMMANDS.setdefault(_latex[1:], _char)
_DELIMITER_COMMANDS = {latex[1:] if latex.startswith("\\") else latex: char for char, latex in DELIMITERS.items()}


class UnsupportedMath(ValueError):
    """The formula uses something this converter does not translate."""


def _m(name: str) -> str:
    return f"{{{M_NS}}}{name}"


def _el(name: str, *children: etree._Element, **attrs: str) -> etree._Element:
    node = etree.Element(_m(name))
    for key, value in attrs.items():
        node.set(_m(key), value)
    node.extend(children)
    return node


def _holder(name: str, items: list[etree._Element]) -> etree._Element:
    """An element such as ``m:e`` or ``m:sub`` holding ``items``."""
    return _el(name, *items)


def _run(text: str, style: str | None = None, normal: bool = False) -> etree._Element:
    run = _el("r")
    if normal:
        run.append(_el("rPr", _el("nor")))
    elif style:
        run.append(_el("rPr", _el("sty", val=style)))
    fonts = etree.SubElement(etree.SubElement(run, f"{{{W_NS}}}rPr"), f"{{{W_NS}}}rFonts")
    fonts.set(f"{{{W_NS}}}ascii", _MATH_FONT)
    fonts.set(f"{{{W_NS}}}hAnsi", _MATH_FONT)
    t = etree.SubElement(run, _m("t"))
    t.set(_XML_SPACE, "preserve")
    t.text = text
    return run


def _merge_runs(items: list[etree._Element]) -> list[etree._Element]:
    """Join adjacent plain runs, so ``n\\pi x`` is one run and not three."""
    merged: list[etree._Element] = []
    for item in items:
        previous = merged[-1] if merged else None
        if (previous is not None and item.tag == _m("r") and previous.tag == _m("r")
                and item.find(_m("rPr")) is None and previous.find(_m("rPr")) is None):
            previous.find(_m("t")).text += item.find(_m("t")).text
        else:
            merged.append(item)
    return merged


@dataclass
class _Atom:
    """What was read before looking for scripts; ``kind`` marks n-ary operators and functions."""
    items: list[etree._Element] = field(default_factory=list)
    kind: str | None = None
    name: str = ""


class _Parser:
    def __init__(self, source: str):
        self.tokens = _TOKEN.findall(source)
        self.pos = 0

    # ---- token access ---------------------------------------------------

    def peek(self) -> str | None:
        while self.pos < len(self.tokens) and (self.tokens[self.pos].isspace()
                                               or self.tokens[self.pos] in _IGNORED):
            self.pos += 1
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> str:
        token = self.peek()
        if token is None:
            raise UnsupportedMath("unexpected end of the formula")
        self.pos += 1
        return token

    def expect(self, token: str) -> None:
        if self.next() != token:
            raise UnsupportedMath(f"expected {token}")

    def raw_group(self) -> str:
        """The text of a ``{...}`` argument, spaces included."""
        self.expect("{")
        depth, parts = 1, []
        while True:
            if self.pos >= len(self.tokens):
                raise UnsupportedMath("unbalanced braces")
            token = self.tokens[self.pos]
            self.pos += 1
            depth += (token == "{") - (token == "}")
            if depth == 0:
                return "".join(parts)
            parts.append(token)

    # ---- structure ------------------------------------------------------

    def sequence(self, until: tuple[str, ...] = ()) -> list[etree._Element]:
        items: list[etree._Element] = []
        while (token := self.peek()) is not None and token not in until:
            if token in ("}", "\\right"):
                raise UnsupportedMath(f"unexpected {token}")
            items.extend(self.unit())
        return _merge_runs(items)

    def has_unit(self) -> bool:
        return self.peek() not in (None, "}", "\\right", "\\end", "&", _ROW_BREAK, "^", "_")

    def group_arg(self) -> list[etree._Element]:
        """A ``{...}`` argument, or the single token that stands for it."""
        if self.peek() == "{":
            return self.group()
        return self.atom().items

    def group(self) -> list[etree._Element]:
        self.expect("{")
        items = self.sequence(until=("}",))
        self.expect("}")
        return items

    def unit(self) -> list[etree._Element]:
        atom = self.atom()
        sub = sup = None
        while self.peek() in ("^", "_"):
            if self.next() == "^":
                if sup is not None:
                    raise UnsupportedMath("two superscripts")
                sup = self.group_arg()
            else:
                if sub is not None:
                    raise UnsupportedMath("two subscripts")
                sub = self.group_arg()
        if atom.kind == "nary":
            return [self.nary(atom.name, sub, sup)]
        if atom.kind == "func":
            return self.function(atom.name, sub, sup)
        if sub is None and sup is None:
            return atom.items
        return [self.scripted(atom.items, sub, sup)]

    @staticmethod
    def scripted(base: list[etree._Element], sub, sup) -> etree._Element:
        parts = [_holder("e", base)]
        if sub is not None:
            parts.append(_holder("sub", sub))
        if sup is not None:
            parts.append(_holder("sup", sup))
        name = "sSubSup" if sub is not None and sup is not None else "sSub" if sub is not None else "sSup"
        return _el(name, *parts)

    def nary(self, char: str, sub, sup) -> etree._Element:
        props = _el("naryPr", _el("chr", val=char))
        if sub is None:
            props.append(_el("subHide", val="1"))
        if sup is None:
            props.append(_el("supHide", val="1"))
        body = self.unit() if self.has_unit() else []
        return _el("nary", props, _holder("sub", sub or []), _holder("sup", sup or []), _holder("e", body))

    def function(self, name: str, sub, sup) -> list[etree._Element]:
        title = _holder("fName", [_run(name, style="p")])
        if sub is not None and sup is None and name in _LIMIT_FUNCTIONS:
            return [_el("limLow", _holder("e", [_run(name, style="p")]), _holder("lim", sub))]
        if sub is not None or sup is not None:
            return [self.scripted([_run(name, style="p")], sub, sup)]
        body = self.unit() if self.has_unit() else []
        return [_el("func", title, _holder("e", body))]

    # ---- atoms ----------------------------------------------------------

    def atom(self) -> _Atom:
        token = self.next()
        if token == "{":
            self.pos -= 1
            return _Atom(self.group())
        if token == "&":
            return _Atom([_run("&")])
        if token in ("}", "^", "_", _ROW_BREAK):
            raise UnsupportedMath(f"unexpected {token}")
        if not token.startswith("\\"):
            return _Atom([_run(_plain(token))])
        if token in _ESCAPED:
            return _Atom([_run(_ESCAPED[token])])
        if token in _SPACES:
            return _Atom([_run(_SPACES[token])])
        return self.command(token[1:].rstrip("*") if token[1:].isalpha() else token[1:])

    def command(self, name: str) -> _Atom:
        if name in _NARY_COMMANDS:
            return _Atom(kind="nary", name=_NARY_COMMANDS[name])
        if name in FUNCTIONS:
            return _Atom(kind="func", name=name)
        if name in ("frac", "dfrac", "tfrac", "binom"):
            num, den = self.group_arg(), self.group_arg()
            props = [_el("fPr", _el("type", val="noBar"))] if name == "binom" else []
            return _Atom([_el("f", *props, _holder("num", num), _holder("den", den))])
        if name == "sqrt":
            degree = None
            if self.peek() == "[":
                self.next()
                degree = self.sequence(until=("]",))
                self.expect("]")
            body = self.group_arg()
            props = [_el("radPr", _el("degHide", val="1"))] if degree is None else []
            return _Atom([_el("rad", *props, _holder("deg", degree or []), _holder("e", body))])
        if name == "left":
            return _Atom([self.delimited()])
        if name in _ACCENT_COMMANDS or name == "widehat":
            char = _ACCENT_COMMANDS.get(name, "\u0302")
            return _Atom([_el("acc", _el("accPr", _el("chr", val=char)), _holder("e", self.group_arg()))])
        if name in ("overline", "underline"):
            props = [_el("barPr", _el("pos", val="bot"))] if name == "underline" else []
            return _Atom([_el("bar", *props, _holder("e", self.group_arg()))])
        if name in ("overset", "underset"):
            limit, base = self.group_arg(), self.group_arg()
            return _Atom([_el("limUpp" if name == "overset" else "limLow", _holder("e", base),
                              _holder("lim", limit))])
        if name == "operatorname":
            return _Atom(kind="func", name=self.raw_group().strip())
        if name == "mathbb":
            letter = self.raw_group().strip()
            if letter not in _BLACKBOARD:
                raise UnsupportedMath(f"\\mathbb{{{letter}}}")
            return _Atom([_run(_BLACKBOARD[letter])])
        if name in _TEXT_COMMANDS:
            style = _TEXT_COMMANDS[name]
            return _Atom([_run(self.raw_group(), style=None if style == "nor" else style, normal=style == "nor")])
        if name == "begin":
            return _Atom([self.environment()])
        if name in _COMMANDS:
            return _Atom([_run(_COMMANDS[name])])
        raise UnsupportedMath(f"\\{name}")

    def delimiter(self) -> str:
        token = self.next()
        if token == ".":
            return ""
        if token.startswith("\\"):
            if token[1:] not in _DELIMITER_COMMANDS:
                raise UnsupportedMath(token)
            return _DELIMITER_COMMANDS[token[1:]]
        return token

    def delimited(self) -> etree._Element:
        opening = self.delimiter()
        body = self.sequence(until=("\\right",))
        self.expect("\\right")
        closing = self.delimiter()
        return self.fenced(opening, closing, [_holder("e", body)])

    @staticmethod
    def fenced(opening: str, closing: str, items: list[etree._Element]) -> etree._Element:
        return _el("d", _el("dPr", _el("begChr", val=opening), _el("endChr", val=closing)), *items)

    # ---- environments ---------------------------------------------------

    def environment(self) -> etree._Element:
        name = self.raw_group().strip()
        if name == "array":
            self.raw_group()
        if name in _MATRICES:
            rows = self.rows(split_cells=True, name=name)
            matrix = _el("m", *(_el("mr", *(_holder("e", cell) for cell in row)) for row in rows))
            opening, closing = _MATRICES[name]
            return self.fenced(opening, closing, [_holder("e", [matrix])]) if opening else matrix
        if name == "cases":
            rows = self.rows(split_cells=False, name=name)
            return self.fenced("{", "", [_holder("e", [self.equation_array(rows)])])
        if name in _ALIGNED:
            return self.equation_array(self.rows(split_cells=False, name=name))
        raise UnsupportedMath(f"environment {name}")

    def rows(self, split_cells: bool, name: str) -> list[list[list[etree._Element]]]:
        """The rows of an environment, each a list of cells (one cell when cells are not split)."""
        until = ("&", _ROW_BREAK, "\\end") if split_cells else (_ROW_BREAK, "\\end")
        rows, cells = [], []
        while True:
            cells.append(self.sequence(until))
            token = self.next()
            if token == "&":
                continue
            rows.append(cells)
            cells = []
            if token == "\\end":
                if self.raw_group().strip() != name:
                    raise UnsupportedMath("mismatched environment")
                break
        if len(rows[-1]) == 1 and not rows[-1][0] and len(rows) > 1:
            rows.pop()
        return rows

    @staticmethod
    def equation_array(rows: list[list[list[etree._Element]]]) -> etree._Element:
        return _el("eqArr", *(_holder("e", row[0]) for row in rows))


def _plain(char: str) -> str:
    return {"-": "\u2212", "'": "\u2032", "~": "\u00a0"}.get(char, char)


def latex_to_omml(code: str, env: str | None = None) -> etree._Element:
    """The ``m:oMath`` element for a LaTeX formula.

    Args:
        code: The formula without delimiters. A top-level ``\\\\`` starts a new line.
        env: The display environment it came from (``align``...); a formula with
            one is written as an equation array.

    Raises:
        UnsupportedMath: If the formula uses a command or construct not translated.
    """
    parser = _Parser(code)
    lines = [parser.sequence((_ROW_BREAK,))]
    while parser.peek() == _ROW_BREAK:
        parser.next()
        lines.append(parser.sequence((_ROW_BREAK,)))
    if parser.peek() is not None:
        raise UnsupportedMath("unbalanced formula")
    root = etree.Element(_m("oMath"), nsmap={"m": M_NS, "w": W_NS})
    if env or len(lines) > 1:
        root.append(parser.equation_array([[line] for line in lines]))
    else:
        root.extend(lines[0])
    return root
