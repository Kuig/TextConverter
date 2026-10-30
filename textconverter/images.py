"""Image and link passes on a parsed document: download, embed, remove, path handling.

During a conversion every local image path is made absolute first
(``ImagePaths.absolutize``), so downloads, embedding and the AI describer all
read the same file whatever directory the source, the output and the current
directory are in. Just before rendering, ``ImagePaths.relativize`` turns the
paths it rewrote back into paths relative to the output location.
"""
from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import re
import urllib.parse

from collections.abc import Callable
from dataclasses import dataclass, replace

from . import _net
from .ast import (
    DESCRIPTION_END, DESCRIPTION_START, Abstract, BlockQuote, Document, Equation, Image,
    LineBreak, Link, ListItem, Node, Paragraph, Text, child_lists, walk,
)
from .logger import log_action, log_warning
from .renderers._common import caption_paragraphs


# Content types that say nothing about the payload: a download with one of
# them may still be an image.
_UNTYPED = ("", "application/octet-stream", "binary/octet-stream")


def is_remote(src: str) -> bool:
    """True for an ``http(s)://`` or protocol-relative (``//host/...``) image source."""
    return src.startswith(("http://", "https://", "//"))


def _has_scheme(src: str) -> bool:
    # A one-letter scheme is a Windows drive ("C:\..."), not a URL scheme.
    return len(urllib.parse.urlparse(src).scheme) > 1


def resolve_local(src: str, base_dir: str) -> str | None:
    """Return the file path an image source points to, or None if it is not a local file.

    URLs (``http:``, ``data:``, ...) and protocol-relative sources are not
    local; a relative path resolves against ``base_dir``.
    """
    if not src or src.startswith("//") or _has_scheme(src):
        return None
    return src if os.path.isabs(src) else os.path.join(base_dir, src)


def _extract_image_filename(url: str) -> str:
    """Return a clean filename for a remote image URL, handling nested/proxied URLs."""
    unquoted_path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    segments = [s.strip() for s in unquoted_path.split('/') if s.strip()]
    basename = segments[-1] if segments else ""
    if not basename or "." not in basename:
        basename = f"image_{hashlib.md5(url.encode('utf-8')).hexdigest()[:8]}.png"
    return basename


def _sanitize_filename(name: str) -> str:
    """Keep only alphanumerics, dots, dashes and underscores; cap the length."""
    base, ext = os.path.splitext(name)
    base = re.sub(r'[^a-zA-Z0-9._-]', '_', base)[:80]
    ext = re.sub(r'[^a-zA-Z0-9.]', '', ext)[:10]
    return f"{base}{ext}"


def _with_image_extension(basename: str, content_type: str) -> str:
    """Fix the extension from an ``image/*`` content type; other types keep the URL's."""
    if not content_type.startswith("image/"):
        return basename
    ext = ".svg" if content_type == "image/svg+xml" else mimetypes.guess_extension(content_type)
    base, current = os.path.splitext(basename)
    if ext and current.lower() != ext.lower():
        return f"{base}{ext}"
    return basename


def _same_content(path: str, data: bytes) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read() == data
    except OSError as exc:
        log_warning(f"Could not read {path} to compare with a downloaded image: {exc}")
        return False


def store_image(data: bytes, target_dir: str, basename: str) -> str:
    """Write ``data`` to ``target_dir`` and return the path.

    An existing file with the same content is reused; one with different
    content gets a numbered sibling (``name_1.png``, ...).
    """
    os.makedirs(target_dir, exist_ok=True)
    base, ext = os.path.splitext(basename)
    name, counter = basename, 0
    while True:
        path = os.path.join(target_dir, name)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(data)
            return path
        if _same_content(path, data):
            return path
        counter += 1
        name = f"{base}_{counter}{ext}"


class ImageStore:
    """Writes the images an Office parser extracts, one file per distinct content.

    Args:
        output_dir: Parent of the image folder; the current directory when None.
        image_dir_name: Name of the image folder inside ``output_dir``.
    """

    def __init__(self, output_dir: str | None, image_dir_name: str | None):
        self.image_dir_name = image_dir_name
        self.target_dir = os.path.join(output_dir or os.getcwd(), image_dir_name or "")
        self._by_digest: dict[str, str] = {}

    def save(self, blob: bytes, extension: str) -> str:
        """Write ``blob`` as ``image_<n>.<extension>`` and return the ``src`` for the Image node."""
        digest = hashlib.sha1(blob).hexdigest()
        if digest not in self._by_digest:
            ext = re.sub(r"[^a-z0-9]", "", extension.lower()) or "bin"
            if ext in ("emf", "wmf"):
                log_warning(f"Image in {ext.upper()} format kept as a file, but most viewers cannot show it.")
            path = store_image(blob, self.target_dir, f"image_{len(self._by_digest) + 1}.{ext}")
            basename = os.path.basename(path)
            self._by_digest[digest] = f"{self.image_dir_name}/{basename}" if self.image_dir_name else basename
        return self._by_digest[digest]


class ImagePaths:
    """Tracks the image paths rewritten during one conversion.

    Args:
        doc_dir: Directory the document's relative image paths resolve against.
    """

    def __init__(self, doc_dir: str):
        self.doc_dir = os.path.abspath(doc_dir)
        # id(node) -> (node, original src); holding the node keeps its id unique.
        self._original: dict[int, tuple[Image, str]] = {}

    def _rewrite(self, node: Image, new_src: str) -> None:
        self._original.setdefault(id(node), (node, node.src))
        node.src = new_src

    def absolutize(self, doc: Node) -> None:
        """Make every relative local image path absolute.

        A root-relative source (``/media/x.png``) is a path on the site the
        document came from, not next to it, and stays as it is.
        """
        for node in walk(doc):
            if isinstance(node, Image) and not node.src.startswith(("/", "\\")):
                path = resolve_local(node.src, self.doc_dir)
                if path and not os.path.isabs(node.src):
                    self._rewrite(node, os.path.abspath(path))

    def download(self, doc: Node, target_dir: str, page_url: str | None) -> None:
        """Download remote images into ``target_dir`` and point the nodes at the files.

        Protocol-relative sources take the page's scheme (https without a
        page). On a URL page, relative sources resolve against ``page_url``.
        Empty and fragment-only sources are skipped, and so is a response
        typed as something other than an image (an HTML error page, say). A
        failed download keeps the absolute URL, with a warning.
        """
        scheme = urllib.parse.urlparse(page_url).scheme if page_url else "https"
        for node in walk(doc):
            if not isinstance(node, Image) or not node.src or node.src.startswith("#"):
                continue
            if node.src.startswith("//"):
                url = f"{scheme}:{node.src}"
            elif node.src.startswith(("http://", "https://")):
                url = node.src
            elif page_url and not _has_scheme(node.src):
                url = urllib.parse.urljoin(page_url, node.src)
            else:
                continue

            log_action(f"Downloading remote image: {url}")
            try:
                download = _net.fetch(url, timeout=15)
            except _net.DownloadError as exc:
                log_warning(str(exc))
                self._rewrite(node, url)
                continue
            if download.content_type not in _UNTYPED and not download.content_type.startswith("image/"):
                log_warning(f"Not an image ({download.content_type}), keeping the link: {url}")
                self._rewrite(node, url)
                continue
            basename = _with_image_extension(_sanitize_filename(_extract_image_filename(url)),
                                             download.content_type)
            try:
                self._rewrite(node, store_image(download.data, target_dir, basename))
            except OSError as exc:
                log_warning(f"Could not save image {url}: {exc}")
                self._rewrite(node, url)

    def relativize(self, doc: Node, base_dir: str) -> None:
        """Make the paths this object rewrote relative to ``base_dir``.

        A path that resolves to the same file as the original source keeps
        the original spelling; one on another drive stays absolute.
        """
        base_dir = os.path.abspath(base_dir)
        for node in walk(doc):
            if not isinstance(node, Image) or id(node) not in self._original:
                continue
            if not os.path.isabs(node.src):
                continue
            original = self._original[id(node)][1]
            try:
                rel = os.path.relpath(node.src, base_dir).replace(os.sep, "/")
            except ValueError:
                continue
            same = (not is_remote(original) and not _has_scheme(original)
                    and os.path.normpath(original) == os.path.normpath(rel))
            node.src = original if same else rel


def embed_images(doc: Node) -> None:
    """Replace the src of every local image file with a base64 data URL.

    Image paths must already be absolute (see ``ImagePaths.absolutize``).
    Remote and ``data:`` sources are left alone; a missing file is reported.
    """
    for node in walk(doc):
        if not isinstance(node, Image):
            continue
        path = resolve_local(node.src, os.getcwd())
        if path is None:
            continue
        if not os.path.exists(path):
            if node.src.startswith(("/", "\\")) and not os.path.splitdrive(node.src)[0]:
                log_warning(f"Image not embedded: {node.src} is relative to the root of the site the page "
                            "came from; convert the page from its URL to download its images.")
            else:
                log_warning(f"Image file not found, not embedded: {path}")
            continue
        try:
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
        except OSError as exc:
            log_warning(f"Could not embed image {path}: {exc}")
            continue
        mime_type = mimetypes.guess_type(path)[0] or "image/png"
        node.src = f"data:{mime_type};base64,{data}"


# Nodes whose children are blocks: a paragraph in them can be split in two.
_BLOCK_CONTAINERS = (Document, BlockQuote, Abstract, ListItem)


@dataclass
class Expansion:
    """What replaces an image: blocks, and what stays in its place where blocks cannot go.

    An image in a paragraph splits it around ``blocks``. Inside a link, a
    table cell or a heading, ``inline`` takes its place and ``blocks`` follow
    the paragraph, table or heading; with ``inline`` None, an inline form of
    the blocks takes its place instead (see ``_as_inline``) and nothing follows.
    """
    blocks: list[Node]
    inline: list[Node] | None = None


# Returns what replaces an image, or None to keep the image.
Expander = Callable[[Image], "Expansion | None"]


def _has_content(inlines: list[Node]) -> bool:
    return any(not isinstance(n, LineBreak) and not (isinstance(n, Text) and not n.content.strip())
               for n in inlines)


def _as_inline(blocks: list[Node]) -> list[Node]:
    """Inline stand-in for blocks, where blocks cannot go (table cell, heading, link)."""
    if len(blocks) == 1 and isinstance(blocks[0], Paragraph):
        return blocks[0].children
    if len(blocks) == 1 and isinstance(blocks[0], Equation):
        return [Equation(code=blocks[0].code, inline=True)]
    text = " ".join(n.content.strip() for b in blocks for n in walk(b) if isinstance(n, Text))
    return [Text(content=text)] if text else []


def _expand(img: Image, expand: Expander) -> Expansion | None:
    """The image's expansion; a figure's caption follows its blocks as a ``Figure: ...`` paragraph."""
    expansion = expand(img)
    if expansion is not None and (img.caption or img.label):
        caption = caption_paragraphs(Paragraph(children=[img]))
        expansion = replace(expansion, blocks=[*expansion.blocks, *caption])
    return expansion


def _split_paragraph(par: Paragraph, expand: Expander) -> list[Node]:
    """The paragraph, split around each image that ``expand`` turns into blocks.

    The blocks of images nested deeper (in a link) follow the part of the
    paragraph they were in.
    """
    result: list[Node] = []
    current: list[Node] = []
    deferred: list[Node] = []
    split = False

    def flush() -> None:
        if _has_content(current):
            result.append(Paragraph(children=list(current)))
        current.clear()
        result.extend(deferred)
        deferred.clear()

    for child in par.children:
        expansion = _expand(child, expand) if isinstance(child, Image) else None
        if expansion is None:
            if not isinstance(child, Image):
                _expand_within(child, expand, deferred)
            current.append(child)
            continue
        split = True
        flush()
        result.extend(expansion.blocks)
    if not split:
        return [par, *deferred]
    flush()
    return result


def expand_images(node: Node, expand: Expander) -> None:
    """Replace images with what ``expand`` returns for them, in place (see ``Expansion``).

    An image in a paragraph splits it: the text before and after the image
    stays in paragraphs of its own around the blocks.
    """
    _expand_within(node, expand, [])


def _expand_within(node: Node, expand: Expander, pending: list[Node]) -> None:
    """``expand_images`` below ``node``; blocks that cannot stay where their image was go to ``pending``."""
    if isinstance(node, _BLOCK_CONTAINERS):
        out: list[Node] = []
        for child in node.children:
            if isinstance(child, Paragraph):
                out.extend(_split_paragraph(child, expand))
                continue
            deferred: list[Node] = []
            _expand_within(child, expand, deferred)
            out.extend([child, *deferred])
        node.children[:] = out
        return
    for lst in child_lists(node):
        out = []
        for child in lst:
            expansion = _expand(child, expand) if isinstance(child, Image) else None
            if expansion is None:
                if not isinstance(child, Image):
                    _expand_within(child, expand, pending)
                out.append(child)
            elif expansion.inline is None:
                out.extend(_as_inline(expansion.blocks))
            else:
                out.extend(expansion.inline)
                pending.extend(expansion.blocks)
        lst[:] = out


def _description_blocks(img: Image) -> Expansion | None:
    """A described image as its reference line and description; in a link the reference stays there."""
    from .parsers.transcription_parser import transcription_nodes
    if not img.description:
        return None
    body = transcription_nodes(img.description, img.category)
    if not img.render_metadata:
        return Expansion(body, inline=[replace(img, description=None)])
    category = f" - Class: {img.category}" if img.category else ""
    reference = Text(content=f"[Image Reference: {img.src}{category}]", bold=True)
    header = Paragraph(children=[replace(reference), LineBreak(), Text(content=DESCRIPTION_START, bold=True)])
    return Expansion([header, *body, Paragraph(children=[Text(content=DESCRIPTION_END, bold=True)])],
                     inline=[reference])


def lower_image_descriptions(doc: Node) -> None:
    """Turn every described image into ordinary nodes, so renderers need no image metadata.

    An image with a ``description`` becomes a reference line and the
    description between ``DESCRIPTION_START`` / ``DESCRIPTION_END`` markers,
    parsed like a transcription (tables, formulas and formatting become real
    nodes); with ``render_metadata`` off, only the parsed description. In a
    link, a table cell or a heading the reference line (or the image) stays in
    place and the description follows the paragraph, table or heading. A
    figure's caption follows the description. Run before rendering text
    formats; the JSON output keeps the images as they are.
    """
    expand_images(doc, _description_blocks)


def remove_images(node: Node) -> None:
    """Recursively drop every Image node from the tree; a figure's caption stays as text."""
    for lst in child_lists(node):
        lst[:] = [k for c in lst for k in (c.caption if isinstance(c, Image) else [c])]
        for c in lst:
            remove_images(c)


def discard_links(node: Node) -> None:
    """Recursively replace every Link node with its inline content.

    The link text (and any image it wrapped) is kept in place; the URL is
    dropped.
    """
    def _unwrap(nodes: list) -> list:
        out: list = []
        for n in nodes:
            if isinstance(n, Link):
                out.extend(_unwrap(n.content))
            else:
                out.append(n)
        return out

    for lst in child_lists(node):
        lst[:] = _unwrap(lst)
        for c in lst:
            discard_links(c)
