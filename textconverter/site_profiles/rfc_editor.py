"""Cleanup for RFC pages of the RFC Editor."""
from __future__ import annotations
import re

from ..ast import CodeBlock, Document, HorizontalRule, Node
from .base import SelectorProfile

_BLANK_RUN = re.compile(r"\n{3,}")


class RfcEditorProfile(SelectorProfile):
    """Cleanup for RFC pages (``rfc-editor.org/rfc/rfc<n>``).

    Keeps the title, topics, date, authors, status and the notice of the RFCs
    that update or obsolete it, then the document. Drops the buttons and the
    subscription counts and, in an RFC written in the current format, the
    ``¶`` link after each paragraph and the "Skip to TOC" link of each
    heading. An older RFC is plain text, one ``<pre>`` per printed page: the
    page headers and footers go and the pages become one code block.
    """

    name = "rfc_editor"
    hosts = ("rfc-editor.org",)
    strip_classes = frozenset({"pilcrow", "toc-link-back", "grey"})
    strip_attrs = frozenset({("data-reef-stats", None)})
    strip_tags = frozenset({"button"})

    @classmethod
    def matches_path(cls, path: str) -> bool:
        return path.startswith("/rfc/")

    def clean_ast(self, doc: Document) -> None:
        super().clean_ast(doc)
        doc.children = _join_pages(doc.children)


def _join_pages(children: list[Node]) -> list[Node]:
    """Merge the code blocks of consecutive pages (split by a rule) into one."""
    out: list[Node] = []
    for node in children:
        if isinstance(node, CodeBlock) and len(out) >= 2 and isinstance(out[-1], HorizontalRule) \
                and isinstance(out[-2], CodeBlock):
            out.pop()
            out[-1].code = out[-1].code.rstrip("\n") + "\n\n" + node.code.lstrip("\n")
        else:
            out.append(node)
    for node in out:
        if isinstance(node, CodeBlock):
            node.code = _BLANK_RUN.sub("\n\n", node.code)
    return out
