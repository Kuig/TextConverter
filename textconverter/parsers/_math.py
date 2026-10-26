"""Math delimiters shared by the HTML parser and the transcription parser."""
from __future__ import annotations

# (opening, closing, display) for every delimiter a formula may arrive in.
MATH_DELIMITERS = (
    ("$$", "$$", True),
    (r"\[", r"\]", True),
    (r"\begin{equation}", r"\end{equation}", True),
    (r"\begin{align}", r"\end{align}", True),
    (r"\begin{displaymath}", r"\end{displaymath}", True),
    (r"\(", r"\)", False),
)


def unwrap_math(code: str, display_only: bool = False) -> str | None:
    """Return the formula inside one pair of math delimiters, or None.

    The text must be exactly one delimited formula: ``$$a$$ and $$b$$`` is two
    formulas and returns None.

    Args:
        code: Stripped text.
        display_only: Accept only display delimiters (not ``\\(...\\)``).
    """
    for start, end, display in MATH_DELIMITERS:
        if display_only and not display:
            continue
        if not (code.startswith(start) and code.endswith(end)) or len(code) <= len(start) + len(end):
            continue
        inner = code[len(start):-len(end)]
        if start in inner or end in inner:
            return None
        return inner.strip()
    return None


def strip_displaystyle(code: str) -> str:
    """Remove a ``\\displaystyle`` wrapper (MediaWiki adds one to every formula)."""
    code = code.strip()
    if code.startswith(r'{\displaystyle') and code.endswith('}'):
        return code[len(r'{\displaystyle'):-1].strip()
    if code.startswith(r'\displaystyle'):
        return code[len(r'\displaystyle'):].strip()
    return code
