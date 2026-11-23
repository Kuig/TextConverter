"""Cleanup for GitHub repository pages."""
from __future__ import annotations
from urllib.parse import urlparse

from ..ast import Document, Heading, Link, ListBlock, ListItem, Node, Paragraph, Table, Text
from .base import SelectorProfile, drop_empty_sections, node_text

# Sidebar links to pages about the repository rather than its content.
_SIDE_LINKS = ("/activity", "/custom-properties", "/contact/report-content")


class GitHubProfile(SelectorProfile):
    """Cleanup for the front page of a GitHub repository (``github.com/<owner>/<repo>``).

    Keeps the repository's name (as the main heading), its description,
    website, topics, license and counts (commits, stars, watchers, forks), the
    file tree as a list of links and the README. Drops the site's navigation,
    the buttons, the tooltips, the duplicate sidebar and the sections the page
    fills in with JavaScript (releases, contributors, languages). GitHub
    suffixes most class names with a build hash, so the selectors are its
    ``data-testid`` attributes and class prefixes.
    """

    name = "github"
    hosts = ("github.com",)
    strip_classes = frozenset({
        "react-directory-row-name-cell-small-screen", "react-directory-row-commit-cell",
    })
    strip_class_prefixes = (
        "prc-src-InternalVisuallyHidden-", "prc-TooltipV2-Tooltip-", "GlobalNav", "RefSelector",
        "FileResultsList__", "HideWhenNarrow__",
    )
    strip_attrs = frozenset([("data-testid", testid) for testid in (
        "top-nav-center", "top-nav-right", "github-avatar", "repo-name-wrapper", "repo-visibility-label",
        "repo-header-actions", "anchor-button", "loading", "latest-commit-details", "view-all-files-row",
    )])
    strip_tags = frozenset({"button"})

    @classmethod
    def matches_path(cls, path: str) -> bool:
        return len([part for part in path.split("/") if part]) == 2

    def clean_ast(self, doc: Document) -> None:
        super().clean_ast(doc)
        doc.children = [_file_list(node) if isinstance(node, Table) else node
                        for node in doc.children if not _side_link(node)]
        drop_empty_sections(doc)
        if self.url:
            name = "/".join(part for part in urlparse(self.url).path.split("/") if part)
            doc.children.insert(0, Heading(level=1, children=[Link(url=self.url, content=[Text(content=name)])]))


def _side_link(node: Node) -> bool:
    """Whether a paragraph is only a sidebar link to a page about the repository."""
    return (isinstance(node, Paragraph) and len(node.children) == 1 and isinstance(node.children[0], Link)
            and urlparse(node.children[0].url).path.endswith(_SIDE_LINKS))


def _file_list(table: Table) -> Node:
    """The "Folders and files" table as a list of links, one per entry; any other table as it is."""
    if not table.headers or node_text(table.headers[0].children).strip() != "Name":
        return table
    items = []
    for row in table.rows:
        links = [n for cell in row.cells for n in cell.children if isinstance(n, Link)]
        if links:
            items.append(ListItem(children=[Paragraph(children=[links[0]])]))
    return ListBlock(ordered=False, items=items) if items else table
