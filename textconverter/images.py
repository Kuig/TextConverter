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

from . import _net
from .ast import Image, Link, Node, child_lists, walk
from .logger import log_action, log_warning


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


def _store(data: bytes, target_dir: str, basename: str) -> str:
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
        """Make every relative local image path absolute."""
        for node in walk(doc):
            if isinstance(node, Image):
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
                self._rewrite(node, _store(download.data, target_dir, basename))
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


def remove_images(node: Node) -> None:
    """Recursively drop every Image node from the tree."""
    for lst in child_lists(node):
        lst[:] = [c for c in lst if not isinstance(c, Image)]
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
