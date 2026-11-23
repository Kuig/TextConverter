"""Cleanup for arXiv abstract pages."""
from __future__ import annotations

from ..ast import Document, Heading, Paragraph, Text
from .base import SelectorProfile


class ArxivProfile(SelectorProfile):
    """Cleanup for arXiv abstract pages (``arxiv.org/abs/<id>``).

    Keeps the title, authors, dates, abstract, the comments/subjects/DOI table,
    the submission history and the links to the full text (PDF, HTML, TeX
    source); drops the breadcrumb, the browsing context, the citation tools,
    the bookmarks and the arXivLabs panels.
    """

    name = "arxiv"
    hosts = ("arxiv.org",)
    strip_classes = frozenset({
        "subheader", "header-breadcrumbs-mobile", "mobile-submission-download",
        "button-and-tooltip", "browse", "extra-ref-cite", "extra-general", "dblp",
        "bookmarks", "bib-modal", "endorsers",
    })
    strip_ids = frozenset({"labstabs"})

    @classmethod
    def matches_path(cls, path: str) -> bool:
        return path.startswith("/abs/")

    def clean_ast(self, doc: Document) -> None:
        super().clean_ast(doc)
        for node in doc.children:
            if isinstance(node, Heading) and node.level == 1:
                _drop_label(node.children, "Title:")
            elif isinstance(node, Paragraph):
                _drop_label(node.children, "Authors:")


def _drop_label(children: list, label: str) -> None:
    """Remove the ``Title:``-like label arXiv writes before a field's value."""
    if children and isinstance(children[0], Text) and children[0].content.startswith(label):
        children[0].content = children[0].content[len(label):].lstrip()
        if not children[0].content:
            del children[0]
