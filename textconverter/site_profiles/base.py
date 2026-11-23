from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from ..ast import Document, Heading, Link, Node, Paragraph, Text, walk

if TYPE_CHECKING:
    from ..config import HtmlConfig


class SiteProfile(ABC):
    """A source-specific cleanup profile for HTML fetched from a known site.

    A profile class recognizes a page (``matches``) and builds an instance
    holding its own settings from the ``html`` config section and the page's
    URL (``from_config``). The instance then contributes two kinds of cleanup:

    - ``skip_subtree`` is consulted by the HTML pre-pass for every start tag; a
      truthy answer drops that element and its whole subtree before the AST is
      built. Use it for inline chrome identified by tag/class/id.
    - ``clean_ast`` runs once on the finished AST. Use it for structural edits
      that are awkward to express on the raw token stream, such as removing a
      heading together with the block of siblings that belongs to it.
    """

    name: str

    @classmethod
    @abstractmethod
    def matches(cls, url: str | None, html: str) -> bool:
        """Return True when this profile should clean the given page.

        Args:
            url: The originating URL, or None when the HTML came from a file or
                literal string.
            html: The raw HTML document.

        Returns:
            True to activate this profile for the page.
        """

    @classmethod
    @abstractmethod
    def from_config(cls, config: HtmlConfig, url: str | None = None) -> SiteProfile:
        """Build the profile with its settings from the ``html`` config section.

        Args:
            config: The loaded ``html`` configuration section.
            url: The page's URL, or None for file/string input.
        """

    @abstractmethod
    def skip_subtree(self, tag: str, attrs: dict[str, str | None]) -> bool:
        """Return True to drop this element and everything inside it.

        Args:
            tag: The lowercased tag name.
            attrs: The element's attributes as a dict; a valueless attribute
                maps to None.

        Returns:
            True to skip the subtree rooted at this element.
        """

    def clean_ast(self, doc: Document) -> None:
        """Edit the built AST in place. Default: no-op.

        Args:
            doc: The parsed document AST.
        """
        return None


class SelectorProfile(SiteProfile):
    """A profile for the pages of some hosts that drops elements by class and id.

    Subclasses declare ``hosts`` (subdomains included), optionally narrow the
    pages with ``matches_path``, and list the chrome in ``strip_classes``,
    ``strip_ids``, ``strip_class_prefixes`` (for class names a site's build
    suffixes with a hash, such as ``Button__x7Yz1q``) and ``strip_attrs``
    (attribute/value pairs, such as ``("data-testid", "sidebar")``; a value of
    None matches the attribute's presence), and
    ``strip_tags`` for whole element types (such as ``button``). The
    declared selectors are also what a check of the live sites looks for, to
    notice when a site stops using one.

    ``clean_ast`` makes the document's relative links absolute against the
    page's URL, so a reader of the result (a person or a model) can follow
    them; a subclass that overrides it calls ``super().clean_ast(doc)``.
    """

    hosts: tuple[str, ...] = ()
    strip_classes: frozenset[str] = frozenset()
    strip_ids: frozenset[str] = frozenset()
    strip_class_prefixes: tuple[str, ...] = ()
    strip_attrs: frozenset[tuple[str, str | None]] = frozenset()
    strip_tags: frozenset[str] = frozenset()

    def __init__(self, url: str | None = None):
        self.url = url

    @classmethod
    def matches(cls, url: str | None, html: str) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return any(host == h or host.endswith("." + h) for h in cls.hosts) and cls.matches_path(parsed.path)

    @classmethod
    def matches_path(cls, path: str) -> bool:
        """Return True when the profile handles a page at this URL path. Default: every page."""
        return True

    @classmethod
    def from_config(cls, config: HtmlConfig, url: str | None = None) -> SelectorProfile:
        return cls(url)

    def skip_subtree(self, tag: str, attrs: dict[str, str | None]) -> bool:
        classes = (attrs.get("class") or "").split()
        return (tag in self.strip_tags
                or (attrs.get("id") or "") in self.strip_ids
                or any(c in self.strip_classes or c.startswith(self.strip_class_prefixes) for c in classes)
                or any(name in attrs if value is None else attrs.get(name) == value
                       for name, value in self.strip_attrs))

    def clean_ast(self, doc: Document) -> None:
        if self.url:
            absolute_links(doc, self.url)


def absolute_links(doc: Document, base_url: str) -> None:
    """Resolve every relative link of the document against ``base_url``.

    A link to a fragment of the page itself (``#section``) is left as it is.
    """
    for node in walk(doc):
        if isinstance(node, Link) and node.url and not node.url.startswith("#"):
            node.url = urljoin(base_url, node.url)


def node_text(nodes: list[Node]) -> str:
    """The text of a list of nodes, descendants included."""
    return "".join(n.content for node in nodes for n in walk(node) if isinstance(n, Text))


def drop_empty_sections(doc: Document) -> None:
    """Remove the top-level headings that head no content.

    A heading is empty when the next block is a heading of the same or a
    higher level, or when it ends the document: what a page fills in with
    JavaScript leaves such headings behind. Empty paragraphs go too.
    """
    kept: list[Node] = []
    for node in reversed(doc.children):
        if isinstance(node, Paragraph) and not node.children:
            continue
        if isinstance(node, Heading):
            following = kept[-1] if kept else None
            if following is None or (isinstance(following, Heading) and following.level <= node.level):
                continue
        kept.append(node)
    doc.children = kept[::-1]
