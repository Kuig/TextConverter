"""What the Word and PowerPoint parsers share: which fonts mean code, and which paragraphs are code."""
from __future__ import annotations

from ..ast import CodeInline, LineBreak, Node, Text

# Fonts whose text is code; the lower-cased family name.
MONOSPACE = frozenset({
    "consolas", "courier new", "courier", "lucida console", "cascadia code", "cascadia mono", "menlo",
    "monaco", "source code pro", "dejavu sans mono", "liberation mono", "andale mono", "fira code",
    "fira mono", "jetbrains mono", "roboto mono", "ubuntu mono", "sf mono", "noto sans mono",
    "lucida sans typewriter", "monospace",
})


def is_code(nodes: list[Node]) -> bool:
    """Whether a paragraph's inline nodes are code and nothing else (blanks and line breaks aside)."""
    if not any(isinstance(n, CodeInline) and n.code.strip() for n in nodes):
        return False
    return all(isinstance(n, (CodeInline, LineBreak)) or (isinstance(n, Text) and not n.content.strip())
               for n in nodes)
