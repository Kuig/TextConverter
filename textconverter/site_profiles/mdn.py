"""Cleanup for MDN Web Docs pages."""
from __future__ import annotations

from ..ast import Document
from .base import SelectorProfile, drop_empty_sections


class MdnProfile(SelectorProfile):
    """Cleanup for MDN Web Docs pages (``developer.mozilla.org``).

    Drops the browser-support banner, the language label over each code
    example (the code block keeps the language), the feedback and edit links
    at the end, and the headings of sections the page fills in with
    JavaScript (the browser compatibility table).
    """

    name = "mdn"
    hosts = ("developer.mozilla.org",)
    strip_classes = frozenset({"baseline-indicator", "example-header", "article-footer"})
    strip_tags = frozenset({"interactive-example"})

    def clean_ast(self, doc: Document) -> None:
        super().clean_ast(doc)
        drop_empty_sections(doc)
