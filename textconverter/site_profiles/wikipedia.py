from __future__ import annotations
from urllib.parse import urlparse

from ..ast import Document, Heading, Node, Text
from ..config import WikipediaCleanupConfig
from .base import SiteProfile

# MediaWiki generates these class/id hooks from software, not from article text,
# so they are identical across every language edition.
_STRIP_CLASSES = frozenset({
    "mw-editsection", "mw-editsection-bracket", "navbox", "navbox-inner",
    "navbox-styles", "vertical-navbox", "navbar", "ambox", "ombox", "mbox-small",
    "hatnote", "dablink", "rellink", "noprint", "printfooter", "catlinks",
    "mw-jump-link", "toc", "toccolours", "shortdescription", "mw-empty-elt",
    "sistersitebox", "side-box", "navigation-not-searchable", "portal",
})
_STRIP_IDS = frozenset({
    "toc", "catlinks", "mw-navigation", "mw-panel", "siteSub", "contentSub",
    "jump-to-nav", "p-lang",
})
# Full citation apparatus (kept unless keep_reference_list is turned off).
_REFERENCE_LIST_CLASSES = frozenset({
    "reflist", "references", "refbegin", "mw-references-wrap",
})

# End-matter section titles, keyed by their English canonical form. A
# drop_sections entry that is one of these keys expands to the whole set;
# any other entry is matched literally. Best-effort, extend via config.
_SECTION_SYNONYMS: dict[str, frozenset[str]] = {
    "see also": frozenset({
        "see also", "voci correlate", "siehe auch", "voir aussi",
        "articles connexes", "véase también", "vea también", "ver também",
        "zie ook", "zobacz też", "см. также", "також", "se även", "se også",
        "související články", "关连项目", "关联项目", "参见", "參見",
        "関連項目", "vegeu també", "katso myös", "див. також", "lásd még",
        "δείτε επίσης", "ayrıca bakınız",
    }),
    "external links": frozenset({
        "external links", "external link", "collegamenti esterni", "weblinks",
        "liens externes", "enlaces externos", "ligações externas",
        "ligacoes externas", "externe links", "externe link",
        "linki zewnętrzne", "ссылки", "externa länkar", "eksterne lenker",
        "eksterne henvisninger", "externí odkazy", "外部链接", "外部連結",
        "外部リンク", "enllaços externs", "aiheesta muualla", "посилання",
        "külső hivatkozások", "εξωτερικοί σύνδεσμοι", "dış bağlantılar",
    }),
    "further reading": frozenset({
        "further reading", "weiterführende literatur",
    }),
}


def _normalize(text: str) -> str:
    """Lowercase and collapse internal whitespace for heading comparison."""
    return " ".join(text.split()).strip().lower()


def _node_text(nodes: list[Node]) -> str:
    """Concatenate the visible text of a list of inline nodes."""
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, Text):
            parts.append(node.content)
        elif isinstance(getattr(node, "content", None), list):
            parts.append(_node_text(node.content))
        elif isinstance(getattr(node, "children", None), list):
            parts.append(_node_text(node.children))
    return "".join(parts)


class WikipediaProfile(SiteProfile):
    """Cleanup for Wikipedia / MediaWiki article pages, in any language.

    Config: :class:`textconverter.config.WikipediaCleanupConfig`.
    Removes edit links, navboxes, maintenance banners, the table of contents,
    category footers and (optionally) inline ``[n]`` citation markers, and
    prunes a configurable set of end-matter sections. Images are left untouched
    so the caller's image handling stays in control.
    """

    name = "wikipedia"

    def matches(self, url: str | None, html: str) -> bool:
        if url:
            host = (urlparse(url).hostname or "").lower()
            if host == "wikipedia.org" or host.endswith(".wikipedia.org"):
                return True
        head = html[:50000]
        return 'class="mediawiki' in head or 'id="mw-content-text"' in head

    def skip_subtree(self, tag: str, attrs: dict[str, str | None], cfg: WikipediaCleanupConfig) -> bool:
        classes = frozenset((attrs.get("class") or "").split())
        node_id = attrs.get("id") or ""
        if classes & _STRIP_CLASSES or node_id in _STRIP_IDS:
            return True
        for selector in cfg.extra_strip_selectors:
            if selector in classes or selector == node_id:
                return True
        if tag == "sup" and "reference" in classes and cfg.drop_citation_marks:
            return True
        if not cfg.keep_reference_list and classes & _REFERENCE_LIST_CLASSES:
            return True
        return False

    def clean_ast(self, doc: Document, cfg: WikipediaCleanupConfig) -> None:
        drop_titles = self._resolve_drop_titles(cfg.drop_sections)
        if not drop_titles:
            return
        kept: list[Node] = []
        dropping_level: int | None = None
        for child in doc.children:
            if isinstance(child, Heading):
                if dropping_level is not None and child.level <= dropping_level:
                    dropping_level = None
                if dropping_level is None and _normalize(_node_text(child.children)) in drop_titles:
                    dropping_level = child.level
                    continue
            if dropping_level is not None:
                continue
            kept.append(child)
        doc.children = kept

    @staticmethod
    def _resolve_drop_titles(configured: list[str]) -> set[str]:
        titles: set[str] = set()
        for entry in configured:
            key = _normalize(entry)
            titles |= _SECTION_SYNONYMS.get(key, frozenset({key}))
        return titles
