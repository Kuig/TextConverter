"""Office Math (OMML) to LaTeX, for the equations of Word documents.

Only the constructs equations are mostly made of are translated: fractions,
scripts, radicals, n-ary operators (sums, integrals), delimiters, functions,
accents, bars, matrices and equation arrays. Any other element contributes
the text of its content.
"""
from __future__ import annotations

import re
import unicodedata

from lxml import etree

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

# Characters that need a command (or an escape) in LaTeX math.
_SYMBOLS = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta", "ε": r"\epsilon", "ϵ": r"\varepsilon",
    "ζ": r"\zeta", "η": r"\eta", "θ": r"\theta", "ϑ": r"\vartheta", "ι": r"\iota", "κ": r"\kappa",
    "λ": r"\lambda", "μ": r"\mu", "ν": r"\nu", "ξ": r"\xi", "π": r"\pi", "ϖ": r"\varpi", "ρ": r"\rho",
    "ϱ": r"\varrho", "σ": r"\sigma", "ς": r"\varsigma", "τ": r"\tau", "υ": r"\upsilon", "φ": r"\phi",
    "ϕ": r"\varphi", "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega",
    "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda", "Ξ": r"\Xi", "Π": r"\Pi",
    "Σ": r"\Sigma", "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega",
    "∞": r"\infty", "∂": r"\partial", "∇": r"\nabla", "∅": r"\emptyset", "ℏ": r"\hbar", "ℓ": r"\ell",
    "ℝ": r"\mathbb{R}", "ℕ": r"\mathbb{N}", "ℤ": r"\mathbb{Z}", "ℚ": r"\mathbb{Q}", "ℂ": r"\mathbb{C}",
    "±": r"\pm", "∓": r"\mp", "×": r"\times", "÷": r"\div", "·": r"\cdot", "⋅": r"\cdot", "∗": r"*",
    "∘": r"\circ", "⊕": r"\oplus", "⊗": r"\otimes", "−": "-", "–": "-",
    "≤": r"\leq", "≥": r"\geq", "≠": r"\neq", "≈": r"\approx", "≡": r"\equiv", "∼": r"\sim",
    "≃": r"\simeq", "≪": r"\ll", "≫": r"\gg", "∝": r"\propto", "≅": r"\cong",
    "∈": r"\in", "∉": r"\notin", "∋": r"\ni", "⊂": r"\subset", "⊃": r"\supset", "⊆": r"\subseteq",
    "⊇": r"\supseteq", "∪": r"\cup", "∩": r"\cap", "∖": r"\setminus", "∀": r"\forall", "∃": r"\exists",
    "¬": r"\neg", "∧": r"\wedge", "∨": r"\vee", "→": r"\to", "←": r"\leftarrow", "↔": r"\leftrightarrow",
    "⇒": r"\Rightarrow", "⇐": r"\Leftarrow", "⇔": r"\Leftrightarrow", "↦": r"\mapsto",
    "…": r"\ldots", "⋯": r"\cdots", "⋮": r"\vdots", "⋱": r"\ddots", "′": "'", "∠": r"\angle",
    "⊥": r"\perp", "∥": r"\parallel", "∑": r"\sum", "∏": r"\prod", "∫": r"\int",
    "#": r"\#", "%": r"\%", "&": r"\&", "$": r"\$", "_": r"\_", "{": r"\{", "}": r"\}",
}
# The n-ary operator characters.
_NARY = {
    "∑": r"\sum", "∏": r"\prod", "∐": r"\coprod", "∫": r"\int", "∬": r"\iint", "∭": r"\iiint",
    "∮": r"\oint", "⋃": r"\bigcup", "⋂": r"\bigcap", "⋁": r"\bigvee", "⋀": r"\bigwedge",
    "⨁": r"\bigoplus", "⨂": r"\bigotimes",
}
_ACCENTS = {
    "̂": r"\hat", "^": r"\hat", "̃": r"\tilde", "~": r"\tilde", "̄": r"\bar",
    "‾": r"\bar", "¯": r"\bar", "̇": r"\dot", "˙": r"\dot", "̈": r"\ddot",
    "¨": r"\ddot", "⃗": r"\vec", "→": r"\vec", "̆": r"\breve", "˘": r"\breve",
    "́": r"\acute", "´": r"\acute", "̀": r"\grave", "`": r"\grave", "̌": r"\check",
}
# Delimiter characters that need a command after \left / \right.
_DELIMITERS = {
    "{": r"\{", "}": r"\}", "‖": r"\|", "⟨": r"\langle", "⟩": r"\rangle", "⌊": r"\lfloor",
    "⌋": r"\rfloor", "⌈": r"\lceil", "⌉": r"\rceil", "": ".",
}
_FUNCTIONS = frozenset(
    "sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh coth log ln lg exp lim limsup liminf "
    "max min sup inf det gcd arg deg dim ker hom Pr".split()
)
# Child elements that describe an element instead of being part of its content.
_PROPERTIES = re.compile(r"^(?:\w+Pr|ctrlPr)$")


def _local(el: etree._Element) -> str:
    return etree.QName(el).localname


def _child(el: etree._Element, name: str) -> etree._Element | None:
    return el.find(f"{{{M_NS}}}{name}")


def _prop(el: etree._Element, props: str, name: str, default: str | None = None) -> str | None:
    """The ``m:val`` of ``el/props/name``, else ``default``."""
    node = el.find(f"{{{M_NS}}}{props}/{{{M_NS}}}{name}")
    if node is None:
        return default
    return node.get(f"{{{M_NS}}}val", default)


def _flag(el: etree._Element, props: str, name: str) -> bool:
    """True when the on/off property ``el/props/name`` is present and on (a bare element is on)."""
    node = el.find(f"{{{M_NS}}}{props}/{{{M_NS}}}{name}")
    return node is not None and node.get(f"{{{M_NS}}}val", "1") in ("1", "on", "true")


def _join(parts: list[str]) -> str:
    """Concatenate LaTeX pieces, keeping a command apart from a letter that follows it."""
    out = ""
    for part in parts:
        if out and part and re.search(r"\\[A-Za-z]+$", out) and part[0].isalpha():
            out += " "
        out += part
    return out


def _arg(code: str) -> str:
    """A script or base: bare when it is one character or one command, else braced."""
    if len(code) == 1 or re.fullmatch(r"\\[A-Za-z]+", code):
        return code
    return "{" + code + "}"


def _text(raw: str) -> str:
    """A run's text as LaTeX."""
    parts = []
    for ch in raw:
        if 0x1D400 <= ord(ch) <= 0x1D7FF:
            ch = unicodedata.normalize("NFKC", ch)
        parts.append(_SYMBOLS.get(ch, ch))
    return _join(parts)


def _content(el: etree._Element) -> str:
    """The LaTeX of an element's children, in order."""
    return _join([_convert(c) for c in el if isinstance(c.tag, str) and not _PROPERTIES.match(_local(c))])


def _sub(el: etree._Element, name: str) -> str:
    node = _child(el, name)
    return _content(node) if node is not None else ""


def _scripts(base: str, sub: str, sup: str) -> str:
    out = _arg(base) if base else "{}"
    if sub:
        out += "_" + _arg(sub)
    if sup:
        out += "^" + _arg(sup)
    return out


def _run(el: etree._Element) -> str:
    raw = "".join(t.text or "" for t in el.iterfind(f"{{{M_NS}}}t"))
    if not raw.strip():
        return ""
    text = _text(raw)
    if _flag(el, "rPr", "nor"):
        return r"\text{" + raw + "}"
    return text


def _fraction(el: etree._Element) -> str:
    num, den = _sub(el, "num"), _sub(el, "den")
    kind = _prop(el, "fPr", "type", "bar")
    if kind == "noBar":
        return r"\binom{" + num + "}{" + den + "}"
    if kind == "lin":
        return _arg(num) + "/" + _arg(den)
    return r"\frac{" + num + "}{" + den + "}"


def _radical(el: etree._Element) -> str:
    degree = _sub(el, "deg")
    if _flag(el, "radPr", "degHide") or not degree:
        return r"\sqrt{" + _sub(el, "e") + "}"
    return r"\sqrt[" + degree + "]{" + _sub(el, "e") + "}"


def _nary(el: etree._Element) -> str:
    op = _NARY.get(_prop(el, "naryPr", "chr", "∫"), _prop(el, "naryPr", "chr", "∫"))
    sub = "" if _flag(el, "naryPr", "subHide") else _sub(el, "sub")
    sup = "" if _flag(el, "naryPr", "supHide") else _sub(el, "sup")
    out = op
    if sub:
        out += "_" + _arg(sub)
    if sup:
        out += "^" + _arg(sup)
    body = _sub(el, "e")
    return _join([out, " " + body]) if body else out


def _delimiter(raw: str) -> str:
    return _DELIMITERS.get(raw, raw)


def _delimited(el: etree._Element) -> str:
    left = _delimiter(_prop(el, "dPr", "begChr", "("))
    right = _delimiter(_prop(el, "dPr", "endChr", ")"))
    separator = _text(_prop(el, "dPr", "sepChr", "|") or "|")
    items = [_content(e) for e in el.iterfind(f"{{{M_NS}}}e")]
    return r"\left" + left + f" {separator} ".join(items) + r"\right" + right


def _function(el: etree._Element) -> str:
    name = _sub(el, "fName").strip()
    plain = name.lstrip("\\")
    if plain in _FUNCTIONS:
        command = "\\" + plain
    elif name.startswith("\\") or not name:
        command = name
    else:
        command = r"\operatorname{" + plain + "}"
    body = _sub(el, "e")
    return _join([command, " " + body]) if body else command


def _accent(el: etree._Element) -> str:
    command = _ACCENTS.get(_prop(el, "accPr", "chr", "̂") or "̂", r"\hat")
    return command + "{" + _sub(el, "e") + "}"


def _bar(el: etree._Element) -> str:
    command = r"\underline" if _prop(el, "barPr", "pos", "top") == "bot" else r"\overline"
    return command + "{" + _sub(el, "e") + "}"


def _matrix(el: etree._Element) -> str:
    rows = [" & ".join(_content(e) for e in row.iterfind(f"{{{M_NS}}}e"))
            for row in el.iterfind(f"{{{M_NS}}}mr")]
    return r"\begin{matrix} " + r" \\ ".join(rows) + r" \end{matrix}"


def _array(el: etree._Element) -> str:
    rows = [_content(e) for e in el.iterfind(f"{{{M_NS}}}e")]
    return r"\begin{aligned} " + r" \\ ".join(rows) + r" \end{aligned}"


def _limit(el: etree._Element, below: bool) -> str:
    base, limit = _sub(el, "e"), _sub(el, "lim")
    if below and base.lstrip("\\") in _FUNCTIONS:
        return base + "_" + _arg(limit)
    return (r"\underset{" if below else r"\overset{") + limit + "}{" + base + "}"


_HANDLERS = {
    "r": _run,
    "f": _fraction,
    "rad": _radical,
    "nary": _nary,
    "d": _delimited,
    "func": _function,
    "acc": _accent,
    "bar": _bar,
    "m": _matrix,
    "eqArr": _array,
    "sSup": lambda el: _scripts(_sub(el, "e"), "", _sub(el, "sup")),
    "sSub": lambda el: _scripts(_sub(el, "e"), _sub(el, "sub"), ""),
    "sSubSup": lambda el: _scripts(_sub(el, "e"), _sub(el, "sub"), _sub(el, "sup")),
    "sPre": lambda el: _scripts("", _sub(el, "sub"), _sub(el, "sup")) + _arg(_sub(el, "e")),
    "limLow": lambda el: _limit(el, below=True),
    "limUpp": lambda el: _limit(el, below=False),
}


def _convert(el: etree._Element) -> str:
    handler = _HANDLERS.get(_local(el))
    return handler(el) if handler else _content(el)


def omml_to_latex(math: etree._Element) -> str:
    """The LaTeX of an ``m:oMath`` element.

    Args:
        math: The ``m:oMath`` element.

    Returns:
        The formula without delimiters, with surrounding spaces removed.
    """
    return re.sub(r"[ \t\n]+", " ", _content(math)).strip()
