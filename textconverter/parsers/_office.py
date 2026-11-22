"""What the Office parsers share: which fonts mean code, which paragraphs are code, and the frame of a text box."""
from __future__ import annotations

import re

from ..ast import BoxFrame, CodeInline, LineBreak, Node, Text, frame_fields, parse_frame_fields

# Fonts whose text is code; the lower-cased family name.
MONOSPACE = frozenset({
    "consolas", "courier new", "courier", "lucida console", "cascadia code", "cascadia mono", "menlo",
    "monaco", "source code pro", "dejavu sans mono", "liberation mono", "andale mono", "fira code",
    "fira mono", "jetbrains mono", "roboto mono", "ubuntu mono", "sf mono", "noto sans mono",
    "lucida sans typewriter", "monospace",
})


_BOX = "Text box"
_PREAMBLE = re.compile(rf"^{_BOX} \((.+)\)$")


def box_preamble(frame: BoxFrame) -> str:
    """The first line of the quote a text box becomes."""
    fields = frame_fields(frame)
    return f"{_BOX} ({fields})" if fields else _BOX


def parse_box_preamble(text: str) -> BoxFrame | None:
    """The frame a line written by ``box_preamble`` gives, else None."""
    match = _PREAMBLE.match(text.strip())
    return parse_frame_fields(match.group(1)) if match else None


def is_code(nodes: list[Node]) -> bool:
    """Whether a paragraph's inline nodes are code and nothing else (blanks and line breaks aside)."""
    if not any(isinstance(n, CodeInline) and n.code.strip() for n in nodes):
        return False
    return all(isinstance(n, (CodeInline, LineBreak)) or (isinstance(n, Text) and not n.content.strip())
               for n in nodes)
