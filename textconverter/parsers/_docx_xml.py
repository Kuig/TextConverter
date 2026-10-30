"""XML namespaces and element helpers shared by the Word parser modules."""
from __future__ import annotations

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {
    "w": W, "m": M, "r": R,
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "v": "urn:schemas-microsoft-com:vml",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}

OFFICE = "urn:schemas-microsoft-com:office:office"

def w(name: str) -> str:
    return f"{{{W}}}{name}"


def xpath(el: etree._Element, expression: str) -> list:
    """Evaluate an XPath expression with the prefixes of ``NS`` (python-docx's own ``xpath`` has fixed ones)."""
    return etree.XPath(expression, namespaces=NS)(el)


def local(el: etree._Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def flag(el: etree._Element | None) -> bool:
    """An on/off run property: present, and not switched off with ``w:val``."""
    return el is not None and el.get(w("val"), "1").lower() not in ("0", "false", "off")


def val(el: etree._Element | None, default: str | None = None) -> str | None:
    return el.get(w("val"), default) if el is not None else default
