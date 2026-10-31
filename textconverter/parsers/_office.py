"""What the Office parsers share: which fonts mean code, which paragraphs are code, and the frame of a text box."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..ast import CodeInline, LineBreak, Node, Text

# Fonts whose text is code; the lower-cased family name.
MONOSPACE = frozenset({
    "consolas", "courier new", "courier", "lucida console", "cascadia code", "cascadia mono", "menlo",
    "monaco", "source code pro", "dejavu sans mono", "liberation mono", "andale mono", "fira code",
    "fira mono", "jetbrains mono", "roboto mono", "ubuntu mono", "sf mono", "noto sans mono",
    "lucida sans typewriter", "monospace",
})


_BOX = "Text box"
_PREAMBLE = re.compile(rf"^{_BOX} \((.+)\)$")
_PERCENT = re.compile(r"^([xywh]) (-?\d+)%$")
_FONT = re.compile(r"^font (\d+(?:\.\d+)?)pt$")
_CELLS = re.compile(r"^[A-Z]+\d+(?::[A-Z]+\d+)?$")


@dataclass(frozen=True)
class BoxFrame:
    """What a text box tells about itself; what is not known stays None.

    ``x``, ``y``, ``w`` and ``h`` are percentages of the slide or page, ``cells``
    the range of a sheet it covers, ``font`` the size of most of its text in points.
    """
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None
    cells: str | None = None
    font: float | None = None

    @property
    def placed(self) -> bool:
        """Whether the frame gives a complete place on a slide or page."""
        return None not in (self.x, self.y, self.w, self.h)


def box_preamble(frame: BoxFrame) -> str:
    """The first line of the quote a text box becomes."""
    fields = [frame.cells] if frame.cells else []
    fields.extend(f"{name} {getattr(frame, name)}%" for name in "xywh" if getattr(frame, name) is not None)
    if frame.font:
        fields.append(f"font {frame.font:g}pt")
    return f"{_BOX} ({', '.join(fields)})" if fields else _BOX


def parse_box_preamble(text: str) -> BoxFrame | None:
    """The frame a line written by ``box_preamble`` gives, else None."""
    match = _PREAMBLE.match(text.strip())
    if match is None:
        return None
    values: dict[str, object] = {}
    for field_text in match.group(1).split(", "):
        percent, font = _PERCENT.match(field_text), _FONT.match(field_text)
        if percent:
            values[percent.group(1)] = int(percent.group(2))
        elif font:
            values["font"] = float(font.group(1))
        elif _CELLS.match(field_text):
            values["cells"] = field_text
        else:
            return None
    return BoxFrame(**values)


def is_code(nodes: list[Node]) -> bool:
    """Whether a paragraph's inline nodes are code and nothing else (blanks and line breaks aside)."""
    if not any(isinstance(n, CodeInline) and n.code.strip() for n in nodes):
        return False
    return all(isinstance(n, (CodeInline, LineBreak)) or (isinstance(n, Text) and not n.content.strip())
               for n in nodes)
