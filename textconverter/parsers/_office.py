"""What the Office parsers share: which fonts mean code, which paragraphs are code, the frame of a text box
and the crop of a picture."""
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


_DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/main"
_BOX = "Text box"
_PREAMBLE = re.compile(rf"^{_BOX} \((.+)\)$")


def src_rect(blip_fill) -> tuple[float, float, float, float] | None:
    """The crop of a picture's ``blipFill`` (``a:srcRect``) as fractions ``(left, top, right, bottom)``, else None.

    Word and PowerPoint write each side in thousandths of a percent: ``l="25000"`` cuts a quarter of the width.
    """
    rect = blip_fill.find(f"{{{_DRAWING}}}srcRect") if blip_fill is not None else None
    if rect is None:
        return None
    try:
        crop = tuple(int(rect.get(side) or 0) / 100000 for side in "ltrb")
    except ValueError:
        return None
    return crop if any(crop) else None


def vml_crop(imagedata) -> tuple[float, float, float, float] | None:
    """The crop of a VML picture (``cropleft="0.25"`` or ``cropleft="16384f"``, 65536ths) as ``src_rect`` gives it."""
    sides = []
    for name in ("cropleft", "croptop", "cropright", "cropbottom"):
        text = (imagedata.get(name) or "0").strip()
        try:
            sides.append(int(text[:-1]) / 65536 if text.endswith("f") else float(text))
        except ValueError:
            return None
    return tuple(sides) if any(sides) else None


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
