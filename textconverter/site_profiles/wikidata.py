"""Cleanup for Wikidata items."""
from __future__ import annotations

from .base import SelectorProfile


class WikidataProfile(SelectorProfile):
    """Cleanup for Wikidata items (``www.wikidata.org/wiki/Q<n>``).

    Works together with :class:`WikipediaProfile`, which recognizes every
    MediaWiki page and removes the wiki's own chrome. Keeps the labels,
    descriptions, aliases, statements and identifiers as they come; drops the
    references of each statement and the links to the item's pages on every
    other wiki, which make most of the page.
    """

    name = "wikidata"
    hosts = ("wikidata.org",)
    strip_classes = frozenset({
        "wikibase-statementview-references-container", "wikibase-statementview-rankselector",
        "wikibase-sitelinkgrouplistview",
    })
    strip_ids = frozenset({"sitelinks"})
