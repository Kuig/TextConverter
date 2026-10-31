"""The cleanup of an HTML page before it is parsed: noise dropped, main content isolated."""
from __future__ import annotations
import html
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Sequence

from ._html_tags import INLINE_TAGS, PARAGRAPH_CLOSERS, VOID_TAGS

if TYPE_CHECKING:
    from ..site_profiles.base import SiteProfile

_NOISE = frozenset(['script', 'style', 'nav', 'footer', 'header',
                    'aside', 'noscript', 'iframe', 'form', 'head'])
_SAFE_ATTRS = frozenset([
    'href', 'src', 'alt', 'title', 'class', 'id', 'role', 'encoding', 'display', 'colspan', 'rowspan',
    'data-src', 'data-lazy-src', 'srcset', 'data-srcset', 'data-label', 'start', 'type', 'checked',
])
# Opening tag -> (open tags it ends implicitly, tags that stop the search).
_IMPLIED_END: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    'li': (frozenset({'li'}), frozenset({'ul', 'ol'})),
    'dt': (frozenset({'dt', 'dd'}), frozenset({'dl'})),
    'dd': (frozenset({'dt', 'dd'}), frozenset({'dl'})),
    'tr': (frozenset({'tr', 'td', 'th'}), frozenset({'table', 'thead', 'tbody', 'tfoot'})),
    'td': (frozenset({'td', 'th'}), frozenset({'tr', 'table'})),
    'th': (frozenset({'td', 'th'}), frozenset({'tr', 'table'})),
    'thead': (frozenset({'thead', 'tbody', 'tfoot', 'tr', 'td', 'th'}), frozenset({'table'})),
    'tbody': (frozenset({'thead', 'tbody', 'tfoot', 'tr', 'td', 'th'}), frozenset({'table'})),
    'tfoot': (frozenset({'thead', 'tbody', 'tfoot', 'tr', 'td', 'th'}), frozenset({'table'})),
    'option': (frozenset({'option'}), frozenset({'select', 'datalist'})),
}


class _ContentExtractor(HTMLParser):
    """Pre-pass stdlib-only: removes noise, isolates the main content block.

    Strategy:
      1. Skip noise tags (and all their children)
      2. If <main>, <article>, or role=main is found -> return only that block
      3. Otherwise return the entire cleaned HTML

    Elements are tracked on a stack of open tags, so an omitted end tag
    (``</li>``, ``</p>``, ``</td>``, valid HTML5) or a stray one cannot shift
    where a skipped subtree or the main block ends. Text and attribute values
    are escaped again, since the parser decodes entities.

    ``profiles`` are the site profiles this page was recognized by; each can
    veto extra subtrees via ``skip_subtree``.
    """
    def __init__(self, profiles: Sequence[SiteProfile] = ()) -> None:
        super().__init__()
        self._profiles = list(profiles)
        self._open: list[str] = []
        # Stack index of the root of the subtree being skipped, or None.
        self._skip_at: int | None = None
        self._buf: list[str] = []       # Complete cleaned HTML buffer
        self._main_buf: list[str] = []  # Main content block buffer
        self._main_at: int | None = None

    def _is_dropped(self, tag: str, ad: dict[str, str | None]) -> bool:
        if tag in _NOISE:
            return True
        return any(profile.skip_subtree(tag, ad) for profile in self._profiles)

    def _emit(self, piece: str) -> None:
        self._buf.append(piece)
        if self._main_at is not None:
            self._main_buf.append(piece)

    def _pop_to(self, index: int) -> None:
        """Close the open elements from the top of the stack down to ``index``."""
        while len(self._open) > index:
            at = len(self._open) - 1
            tag = self._open.pop()
            if self._skip_at is not None:
                if at == self._skip_at:
                    self._skip_at = None  # Closed the root of the skipped subtree
                continue
            self._emit(f'</{tag}>')
            if at == self._main_at:
                self._main_at = None  # Exited the main content block

    def _close_implied(self, tag: str) -> None:
        if tag in PARAGRAPH_CLOSERS:
            # An open <p> with only inline elements above it ends here
            for i in range(len(self._open) - 1, -1, -1):
                if self._open[i] == 'p':
                    self._pop_to(i)
                    break
                if self._open[i] not in INLINE_TAGS:
                    break
        rule = _IMPLIED_END.get(tag)
        if rule is None:
            return
        ends, boundary = rule
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i] in ends:
                self._pop_to(i)
                return
            if self._open[i] in boundary:
                return

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = dict(attrs)
        self._close_implied(tag)
        void = tag in VOID_TAGS
        if self._skip_at is not None:
            if not void:
                self._open.append(tag)
            return
        if self._is_dropped(tag, ad):
            if not void:
                self._skip_at = len(self._open)
                self._open.append(tag)
            return

        if not void:
            self._open.append(tag)
            if self._main_at is None and (tag in ('main', 'article') or ad.get('role') == 'main'):
                self._main_at = len(self._open) - 1
        attr_str = ''.join(
            f' {k}="{html.escape(v, quote=True)}"' for k, v in attrs
            if k in _SAFE_ATTRS and v
        )
        self._emit(f'<{tag}{attr_str}>')

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i] == tag:
                self._pop_to(i)
                return
        # A stray end tag closes nothing

    def handle_data(self, data: str) -> None:
        if self._skip_at is not None:
            return
        self._emit(html.escape(data, quote=False))

    def get_html(self) -> str:
        return ''.join(self._main_buf or self._buf)


def extract_content(html_text: str, profiles: Sequence[SiteProfile] = ()) -> str:
    """Return the main content of an HTML page, without navigation and other chrome.

    Args:
        html_text: The page source.
        profiles: Active site profiles; their ``skip_subtree`` hooks drop
            site-specific chrome.
    """
    ex = _ContentExtractor(profiles)
    ex.feed(html_text)
    return ex.get_html()
