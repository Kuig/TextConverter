from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any

from ..ast import Document


class SiteProfile(ABC):
    """A source-specific cleanup profile for HTML fetched from a known site.

    A profile self-activates on a page it recognizes (``matches``) and then
    contributes two kinds of cleanup:

    - ``skip_subtree`` is consulted by the HTML pre-pass for every start tag; a
      truthy answer drops that element and its whole subtree before the AST is
      built. Use it for inline chrome identified by tag/class/id.
    - ``clean_ast`` runs once on the finished AST. Use it for structural edits
      that are awkward to express on the raw token stream, such as removing a
      heading together with the block of siblings that belongs to it.

    ``cfg`` is the profile's own configuration object (a dataclass owned by
    :mod:`textconverter.config`); each profile documents its shape.
    """

    name: str

    @abstractmethod
    def matches(self, url: str | None, html: str) -> bool:
        """Return True when this profile should clean the given page.

        Args:
            url: The originating URL, or None when the HTML came from a file or
                literal string.
            html: The raw HTML document.

        Returns:
            True to activate this profile for the page.
        """

    @abstractmethod
    def skip_subtree(self, tag: str, attrs: dict[str, str | None], cfg: Any) -> bool:
        """Return True to drop this element and everything inside it.

        Args:
            tag: The lowercased tag name.
            attrs: The element's attributes as a dict; a valueless attribute
                maps to None.
            cfg: The profile's configuration object.

        Returns:
            True to skip the subtree rooted at this element.
        """

    def clean_ast(self, doc: Document, cfg: Any) -> None:
        """Edit the built AST in place. Default: no-op.

        Args:
            doc: The parsed document AST.
            cfg: The profile's configuration object.
        """
        return None
