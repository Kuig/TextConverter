"""Site-specific HTML cleanup profiles, run offline on fixtures shaped like the real pages.

Usage: python -m unittest discover -s tests -p "test_site_profiles.py"
"""
from __future__ import annotations
from unittest.mock import patch

import textconverter
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR, read


def _render(html: str, url: str | None) -> str:
    """parse_html with the profiles matching ``url`` → markdown (no image passes)."""
    from textconverter.config import load_config
    from textconverter.parsers.html_parser import parse_html
    from textconverter.renderers.markdown_renderer import render_markdown
    from textconverter.site_profiles import resolve_profiles

    return render_markdown(parse_html(html, extract_html=True, profiles=resolve_profiles(url, html, load_config().html)))


def _profile_names(html: str, url: str | None) -> list[str]:
    from textconverter.config import load_config
    from textconverter.site_profiles import resolve_profiles

    return [profile.name for profile in resolve_profiles(url, html, load_config().html)]


class _ProfileTest(BaseConverterTest):
    """A fixture page and the URL it comes from."""

    FIXTURE = ""
    URL = ""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.html = read(INPUT_DIR / cls.FIXTURE)
        cls.md = _render(cls.html, cls.URL)

    def assert_gone(self, *texts: str) -> None:
        for text in texts:
            self.assertNotIn(text, self.md, f"{text!r} should be stripped")

    def assert_kept(self, *texts: str) -> None:
        for text in texts:
            self.assertIn(text, self.md, f"{text!r} should be kept")


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
        for gone in ("2 languages", "Italiano", "Toggle the table of contents"):
            self.assertNotIn(gone, md, f"{gone!r} should be stripped")
        for kept in ("# Example article", "## History", "history section body text", "Founded", "1861",
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


class TestArxivProfile(_ProfileTest):
    FIXTURE = "ArxivSample.html"
    URL = "https://arxiv.org/abs/1706.03762"

    def test_strips_chrome_keeps_the_paper(self):
        self.assert_gone("Computer Science >", "Title:", "Authors:", "Focus to learn more", "browse context",
                         "NASA ADS", "blog links", "DBLP", "Bookmark", "arXivLabs", "Bibliographic Explorer",
                         "endorsers", "View a PDF of the paper")
        self.assert_kept("# Attention Is All You Need", "Ashish Vaswani", "Submitted on 12 Jun 2017",
                         "The dominant sequence transduction models", "15 pages, 5 figures",
                         "https://doi.org/10.48550/arXiv.1706.03762", "## Submission history")

    def test_full_text_links_are_absolute(self):
        self.assert_kept("[View PDF](https://arxiv.org/pdf/1706.03762)",
                         "[TeX Source](https://arxiv.org/src/1706.03762)",
                         "(https://arxiv.org/html/1706.03762v7)")
        self.assertEqual(self.md.count("View PDF"), 1)

    def test_only_abstract_pages(self):
        self.assertEqual(_profile_names(self.html, self.URL), ["arxiv"])
        self.assertEqual(_profile_names(self.html, "https://arxiv.org/list/cs.CL/new"), [])
        self.assertEqual(_profile_names(self.html, "https://example.org/abs/1706.03762"), [])


class TestGitHubProfile(_ProfileTest):
    FIXTURE = "GitHubRepoSample.html"
    URL = "https://github.com/psf/requests"

    def test_strips_chrome(self):
        self.assert_gone("Repository navigation", "Sign in", "Public", "Sponsor", "Notifications",
                         "You must be signed in", "Go to file", "Open more actions menu", "Latest commit",
                         "View all files", "Activity", "Custom properties", "Report repository",
                         "sidebar copy", "Releases", "Contributors", "Languages", "Last commit message")

    def test_keeps_the_repository_data(self):
        self.assertTrue(self.md.startswith("# [psf/requests](https://github.com/psf/requests)\n"))
        self.assert_kept("A simple, yet elegant, HTTP library.", "requests.readthedocs.io",
                         "(https://github.com/topics/http)", "Apache-2.0 license", "**54.8k** stars",
                         "**1.3k** watching", "**10.9k** forks",
                         "[6,496 Commits](https://github.com/psf/requests/commits/main/)",
                         "[Branches](https://github.com/psf/requests/branches)")

    def test_file_tree_is_a_list_of_absolute_links(self):
        self.assert_kept("## Folders and files\n\n- [docs](https://github.com/psf/requests/tree/main/docs)\n"
                         "- [setup.py](https://github.com/psf/requests/blob/main/setup.py)\n")
        self.assertEqual(self.md.count("[docs]"), 1)

    def test_readme_follows(self):
        self.assert_kept("# Requests", "**Requests** is a simple, yet elegant, HTTP library.", ">>> import requests")
        self.assertLess(self.md.index("## Folders and files"), self.md.index("# Requests"))

    def test_only_repository_front_pages(self):
        for url in ("https://github.com/psf", "https://github.com/psf/requests/issues/1",
                    "https://gist.github.com/psf/abc/def"):
            self.assertEqual(_profile_names(self.html, url), [], url)


class TestMdnProfile(_ProfileTest):
    FIXTURE = "MdnSample.html"
    URL = "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise/all"

    def test_strips_chrome(self):
        self.assert_gone("Baseline", "well established", "Browser compatibility", "Enable JavaScript",
                         "Help improve MDN", "Was this page helpful", "Report a problem", "](#syntax)")
        self.assertNotRegex(self.md, r"(?m)^js$")

    def test_keeps_the_reference(self):
        self.assert_kept("# Promise.all()", "## Try it", "## Syntax", "```js\nPromise.all(iterable)",
                         "## See also",
                         "(https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise)")


class TestRfcEditorProfile(_ProfileTest):
    FIXTURE = "RfcSample.html"
    URL = "https://www.rfc-editor.org/rfc/rfc9110"

    def test_strips_chrome(self):
        self.assert_gone("Info", "Subscribe", "36 subscribed", "Add to Set", "\u00b6", "Skip to TOC")

    def test_keeps_the_document(self):
        self.assert_kept("# RFC 9110: HTTP Semantics", "June 2022.", "R. Fielding, Ed.", "Internet Standard",
                         "## Abstract", "## 1. Introduction", "stateless application-level protocol.\n",
                         "[RFC 9112](https://www.rfc-editor.org/rfc/rfc9112)",
                         "[Plain Text](https://www.rfc-editor.org/rfc/rfc9110.txt)")

    def test_plain_text_rfc_is_one_code_block(self):
        md = _render(read(INPUT_DIR / "RfcLegacySample.html"), "https://www.rfc-editor.org/rfc/rfc6749")
        self.assertEqual(md.count("```"), 2)
        for gone in ("[Page 1]", "OAuth 2.0                   October 2012", "\n\n\n"):
            self.assertNotIn(gone, md)
        for kept in ("# RFC 6749: The OAuth 2.0 Authorization Framework", "This RFC was updated, see",
                     "[RFC 8252](https://www.rfc-editor.org/info/rfc8252/)", "Obsoletes: 5849",
                     "described\n   in RFC 5849.", "Table of Contents"):
            self.assertIn(kept, md)


class TestWiktionaryProfile(_ProfileTest):
    FIXTURE = "WiktionarySample.html"
    URL = "https://en.wiktionary.org/wiki/serendipity"

    def test_runs_with_the_mediawiki_profile(self):
        self.assertEqual(_profile_names(self.html, self.URL), ["wikipedia", "wiktionary"])

    def test_strips_template_chrome(self):
        self.assert_gone("WOTD", "Etymology tree", "Proto-Indo-European", "Italiano")
        self.assert_kept("# serendipity", "## English", "### Etymology", "Coined by Horace Walpole",
                         "[_Serendip_](https://en.wiktionary.org/wiki/Serendip#English)",
                         "1. An unsought, unintended")


class TestWikidataProfile(_ProfileTest):
    FIXTURE = "WikidataSample.html"
    URL = "https://www.wikidata.org/wiki/Q42"

    def test_runs_with_the_mediawiki_profile(self):
        self.assertEqual(_profile_names(self.html, self.URL), ["wikipedia", "wikidata"])

    def test_strips_references_and_sitelinks(self):
        self.assert_gone("3 references", "stated in", "BnF authorities", "Sitelinks", "afwiki", "Normal rank")
        self.assert_kept("# Douglas Adams (Q42)", "British science fiction writer", "## Statements",
                         "[instance of](https://www.wikidata.org/wiki/Property:P31", "[human](")


class TestProfilesThroughConvert(BaseConverterTest):
    """The URL of a download reaches the profiles: matching and absolute links."""

    def test_convert_url_runs_the_profile(self):
        from textconverter import _net

        html = read(INPUT_DIR / "ArxivSample.html")
        download = _net.Download(data=html.encode("utf-8"), content_type="text/html", charset="utf-8")
        options = dict(extract_html=True, image_handling="discard")
        with patch.object(_net, "fetch", return_value=download):
            md = textconverter.convert("https://arxiv.org/abs/1706.03762", "markdown",
                                       textconverter.ConvertOptions(**options))
            plain = textconverter.convert("https://arxiv.org/abs/1706.03762", "markdown",
                                          textconverter.ConvertOptions(**options, site_cleanup=False))
        self.assertIn("[View PDF](https://arxiv.org/pdf/1706.03762)", md)
        self.assertNotIn("arXivLabs", md)
        self.assertIn("arXivLabs", plain)
        self.assertIn("[View PDF](/pdf/1706.03762)", plain)

    def test_new_profiles_need_their_host(self):
        """Without a URL only the MediaWiki fingerprint can match."""
        for fixture in ("ArxivSample.html", "GitHubRepoSample.html", "MdnSample.html", "RfcSample.html"):
            self.assertEqual(_profile_names(read(INPUT_DIR / fixture), None), [], fixture)
