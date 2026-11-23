"""Source-specific HTML cleanup profiles.

Each profile recognizes pages from one site and strips the residual chrome that
generic main-content extraction leaves behind. Profiles are registered in
``PROFILES``; :func:`resolve_profiles` returns the ones that match a page,
each built with its settings.
"""
from __future__ import annotations

from ..config import HtmlConfig
from .arxiv import ArxivProfile
from .base import SelectorProfile, SiteProfile
from .github import GitHubProfile
from .mdn import MdnProfile
from .rfc_editor import RfcEditorProfile
from .wikidata import WikidataProfile
from .wikipedia import WikipediaProfile
from .wiktionary import WiktionaryProfile

PROFILES: tuple[type[SiteProfile], ...] = (
    WikipediaProfile,
    ArxivProfile,
    GitHubProfile,
    MdnProfile,
    RfcEditorProfile,
    WiktionaryProfile,
    WikidataProfile,
)


def resolve_profiles(url: str | None, html: str, config: HtmlConfig) -> list[SiteProfile]:
    """Return the profiles that apply to a page, each built with its settings.

    Args:
        url: The originating URL, or None for file/string input.
        html: The raw HTML document.
        config: The loaded ``html`` configuration section.

    Returns:
        The matching profiles, empty when nothing matches.
    """
    return [profile.from_config(config, url) for profile in PROFILES if profile.matches(url, html)]


__all__ = ["SiteProfile", "SelectorProfile", "WikipediaProfile", "PROFILES", "resolve_profiles"]
