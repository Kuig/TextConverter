"""XML namespaces, slide geometry and shape flattening shared by the PowerPoint parser modules."""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from lxml import etree

from ._office import BoxFrame

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
NS = {
    "a": A, "p": P, "r": R, "mc": MC,
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "a14": "http://schemas.microsoft.com/office/drawing/2010/main",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
}

# The section the renderer puts the slides before the first heading in: not a section of the document.
DEFAULT_SECTION = "Default Section"
# Namespaces an ``mc:Choice`` can require that this parser reads; any other requirement means the Fallback is used.
_SUPPORTED_REQUIRES = frozenset({"a14", "p14", "p15", "a16"})


def a(name: str) -> str:
    return f"{{{A}}}{name}"


def p(name: str) -> str:
    return f"{{{P}}}{name}"


def xpath(el: etree._Element, expression: str, **variables: str) -> list:
    """Evaluate an XPath expression with the prefixes of ``NS`` and the given ``$variables``."""
    return etree.XPath(expression, namespaces=NS)(el, **variables)


def local(el: etree._Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


@dataclass(frozen=True)
class Rect:
    """A shape's frame on the slide, in EMU."""
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self) -> float:
        return self.w * self.h


@dataclass(frozen=True)
class Item:
    """A shape of a slide: the element and where it sits (None when it inherits its frame)."""
    el: etree._Element
    rect: Rect | None


@dataclass(frozen=True)
class _Transform:
    """Maps a group's child coordinates to the slide: ``slide = scale * child + offset``."""
    sx: float = 1.0
    sy: float = 1.0
    tx: float = 0.0
    ty: float = 0.0

    def apply(self, x: float, y: float, w: float, h: float) -> Rect:
        return Rect(self.sx * x + self.tx, self.sy * y + self.ty, self.sx * w, self.sy * h)

    def into(self, group: etree._Element) -> _Transform:
        """The transform of a group's children."""
        xfrm = group.find(f"{p('grpSpPr')}/{a('xfrm')}")
        if xfrm is None:
            return self
        off, ext = xfrm.find(a("off")), xfrm.find(a("ext"))
        ch_off, ch_ext = xfrm.find(a("chOff")), xfrm.find(a("chExt"))
        if off is None or ext is None or ch_off is None or ch_ext is None:
            return self
        kx = _num(ext, "cx") / _num(ch_ext, "cx") if _num(ch_ext, "cx") else 1.0
        ky = _num(ext, "cy") / _num(ch_ext, "cy") if _num(ch_ext, "cy") else 1.0
        return _Transform(
            self.sx * kx, self.sy * ky,
            self.sx * (_num(off, "x") - _num(ch_off, "x") * kx) + self.tx,
            self.sy * (_num(off, "y") - _num(ch_off, "y") * ky) + self.ty,
        )


def _num(el: etree._Element, attribute: str) -> float:
    try:
        return float(el.get(attribute, "0"))
    except ValueError:
        return 0.0


def _frame(shape: etree._Element) -> tuple[float, float, float, float] | None:
    """``(x, y, w, h)`` of a shape in its own coordinate space, None when it has no explicit frame."""
    xfrm = shape.find(p("xfrm")) if shape.tag == p("graphicFrame") else shape.find(f"{p('spPr')}/{a('xfrm')}")
    if xfrm is None:
        return None
    off, ext = xfrm.find(a("off")), xfrm.find(a("ext"))
    if off is None or ext is None:
        return None
    return _num(off, "x"), _num(off, "y"), _num(ext, "cx"), _num(ext, "cy")


def _alternative(content: etree._Element) -> list[etree._Element]:
    """The shapes of an ``mc:AlternateContent`` to read.

    The Choice, unless it needs a feature this parser cannot read or the Fallback is a picture standing
    in for a diagram or a chart: then the Fallback.
    """
    choice, fallback = content.find(f"{{{MC}}}Choice"), content.find(f"{{{MC}}}Fallback")
    if choice is None:
        return list(fallback) if fallback is not None else []
    required = (choice.get("Requires") or "").split()
    unsupported = any(prefix not in _SUPPORTED_REQUIRES for prefix in required)
    picture_stands_in = (fallback is not None and fallback.find(p("pic")) is not None
                         and choice.find(p("graphicFrame")) is not None)
    if fallback is not None and (unsupported or picture_stands_in):
        return list(fallback)
    return list(choice)


def iter_items(parent: etree._Element, transform: _Transform | None = None) -> Iterator[Item]:
    """The leaf shapes under ``parent`` in z-order, groups flattened with their frames mapped to the slide."""
    yield from _walk(list(parent), transform or _Transform())


def _walk(children: list[etree._Element], transform: _Transform) -> Iterator[Item]:
    for child in children:
        if not isinstance(child.tag, str):
            continue
        if child.tag == f"{{{MC}}}AlternateContent":
            yield from _walk(_alternative(child), transform)
        elif child.tag == p("grpSp"):
            yield from _walk(list(child), transform.into(child))
        elif child.tag in (p("sp"), p("pic"), p("graphicFrame"), p("cxnSp")):
            frame = _frame(child)
            yield Item(child, transform.apply(*frame) if frame else None)


def slide_frame(rect: Rect | None, slide_w: float, slide_h: float, font: float | None = None) -> BoxFrame:
    """A shape's frame as percentages of the slide."""
    if rect is None:
        return BoxFrame(font=font)
    return BoxFrame(x=round(100 * rect.x / slide_w), y=round(100 * rect.y / slide_h),
                    w=round(100 * rect.w / slide_w), h=round(100 * rect.h / slide_h), font=font)
