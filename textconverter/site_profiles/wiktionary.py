"""Cleanup for Wiktionary entries."""
from __future__ import annotations

from .base import SelectorProfile


class WiktionaryProfile(SelectorProfile):
    """Cleanup for Wiktionary entries (``*.wiktionary.org``).

    Works together with :class:`WikipediaProfile`, which recognizes every
    MediaWiki page and removes the wiki's own chrome; this one drops what
    Wiktionary's templates add: the etymology tree widget and the "word of
    the day" banner.
    """

    name = "wiktionary"
    hosts = ("wiktionary.org",)
    strip_classes = frozenset({"etytree", "was-wotd"})
