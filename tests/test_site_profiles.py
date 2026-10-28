"""Site-specific HTML cleanup profiles (Wikipedia), run offline on a fixture.

Usage: python -m unittest discover -s tests -p "test_site_profiles.py"
"""
from __future__ import annotations

import textconverter
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR, read


class TestWikipediaCleanup(BaseConverterTest):

    WIKI_URL = "https://en.wikipedia.org/wiki/Example"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.html = read(INPUT_DIR / "WikipediaSample.html")

    def _render(self, *, url=None, profiles=None):
        """parse_html → markdown, driving profiles explicitly (offline)."""
        from textconverter.parsers.html_parser import parse_html
        from textconverter.renderers.markdown_renderer import render_markdown
        from textconverter.config import load_config
        from textconverter.site_profiles import resolve_profiles

        if profiles is None:
            profiles = resolve_profiles(url, self.html, load_config().html)
        return render_markdown(parse_html(self.html, extract_html=True, profiles=profiles))

    def test_profile_strips_chrome_keeps_content(self):
        """Wikipedia URL → edit links, navbox, banners, categories, [n] markers gone; prose/infobox/reflist kept."""
        md = self._render(url=self.WIKI_URL)
        for gone in ("[edit]", "Navlink A", "additional citations", "Categories",
                     "cite_note", "[[1]]", "From Wikipedia", "For other uses"):
            self.assertNotIn(gone, md, f"{gone!r} should be stripped")
        for kept in ("## History", "history section body text", "Founded", "1861",
                     "/media/pic.jpg", "Full citation text", "## References"):
            self.assertIn(kept, md, f"{kept!r} should be kept")

    def test_end_sections_pruned_multilingual(self):
        """Default drop_sections removes 'See also' and its localized 'Voci correlate'."""
        md = self._render(url=self.WIKI_URL)
        self.assertNotIn("See also", md)
        self.assertNotIn("Related topic", md)
        self.assertNotIn("Voci correlate", md)
        self.assertNotIn("Altro argomento", md)

    def test_not_triggered_without_profile(self):
        """extract_html alone (no matching profile) leaves Wikipedia chrome in place."""
        md = self._render(profiles=())
        self.assertIn("Navlink A", md)
        self.assertIn("See also", md)
        self.assertIn(r"[<sup>\[1\]</sup>](#cite_note-1)", md)

    def test_fingerprint_activation_via_convert(self):
        """No URL: the <body class="mediawiki"> fingerprint still activates the profile."""
        md = textconverter.convert_text(self.html, "html", "markdown", textconverter.ConvertOptions(extract_html=True))
        self.assertNotIn("Navlink A", md)
        self.assertNotIn("[edit]", md)
        self.assertIn("## History", md)

    def test_site_cleanup_opt_out(self):
        """site_cleanup=False downgrades to generic extraction even on a Wikipedia page."""
        md = textconverter.convert_text(self.html, "html", "markdown", textconverter.ConvertOptions(extract_html=True, site_cleanup=False))
        self.assertIn("Navlink A", md)
        self.assertIn("See also", md)

    def test_config_toggles(self):
        """keep_reference_list / drop_citation_marks / extra_strip_selectors honoured."""
        from textconverter.config import WikipediaCleanupConfig
        from textconverter.site_profiles import WikipediaProfile

        md = self._render(profiles=[WikipediaProfile(WikipediaCleanupConfig(keep_reference_list=False))])
        self.assertNotIn("Full citation text", md)

        md = self._render(profiles=[WikipediaProfile(WikipediaCleanupConfig(drop_citation_marks=False))])
        self.assertIn(r"[<sup>\[1\]</sup>](#cite_note-1)", md)

        md = self._render(profiles=[WikipediaProfile(WikipediaCleanupConfig(extra_strip_selectors=["infobox"]))])
        self.assertNotIn("Founded", md)
