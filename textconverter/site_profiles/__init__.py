"""Source-specific HTML cleanup profiles.

Each profile recognizes pages from one site and strips the residual chrome that
generic main-content extraction leaves behind. Profiles are registered in
``PROFILES``; :func:`resolve_profiles` returns the ones that match a page,
paired with their configuration.
"""
from __future__ import annotations

from ..config import HtmlConfig
from .base import SiteProfile
from .wikipedia import WikipediaProfile

PROFILES: tuple[SiteProfile, ...] = (
    WikipediaProfile(),
)


def resolve_profiles(
    url: str | None, html: str, config: HtmlConfig
) -> list[tuple[SiteProfile, object]]:
    """Return the profiles that apply to a page, each with its config object.

    Args:
        url: The originating URL, or None for file/string input.
        html: The raw HTML document.
        config: The loaded ``html`` configuration section.

    Returns:
        A list of ``(profile, profile_config)`` pairs, empty when nothing matches.
    """
    active: list[tuple[SiteProfile, object]] = []
    for profile in PROFILES:
        if profile.matches(url, html):
            active.append((profile, getattr(config, profile.name)))
    return active


__all__ = ["SiteProfile", "WikipediaProfile", "PROFILES", "resolve_profiles"]
