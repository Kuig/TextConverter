from __future__ import annotations
import base64
import mimetypes
import os
import pathlib
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace

from . import _net
from .ast import Document, Image, Link, Node, child_lists, walk

from .parsers.markdown_parser import parse_markdown
from .parsers.html_parser import parse_html
from .parsers.latex_parser import parse_latex
from .parsers.pdf_parser import parse_pdf
from .parsers.image_parser import parse_image
from .parsers.json_parser import parse_json

from .renderers.markdown_renderer import render_markdown
from .renderers.html_renderer import render_html
from .renderers.latex_renderer import render_latex
from .renderers.json_renderer import render_json

from .site_profiles import resolve_profiles
from .config import AppConfig, load_config
from .formats import (
    INPUT_FORMATS, OUTPUT_FORMATS, TEXT_OUTPUT_FORMATS, check_choice,
    infer_input_format, infer_output_format,
)
from .options import ConvertOptions

# HTML template that PDF output is printed from.
PDF_TEMPLATE = "light"

def _extract_image_filename(url: str) -> str:
    """Extracts a clean filename from a remote URL, handling nested/proxied URL structures.

    Args:
        url: The full remote URL.

    Returns:
        The extracted basename (filename).
    """
    import urllib.parse
    import hashlib

    parsed_url = urllib.parse.urlparse(url)
    # Unquote to resolve any percent-encoded path segments or nested URLs
    unquoted_path = urllib.parse.unquote(parsed_url.path)
    # Split by '/' and take the last non-empty segment
    segments = [s.strip() for s in unquoted_path.split('/') if s.strip()]
    
    basename = segments[-1] if segments else ""
    if not basename or "." not in basename:
        ext = ".png"
        basename = f"image_{hashlib.md5(url.encode('utf-8')).hexdigest()[:8]}{ext}"
        
    return basename


def _sanitize_filename(name: str) -> str:
    """Sanitizes a remote filename by replacing special characters.

    Args:
        name: The raw filename.

    Returns:
        A sanitized filename containing only alphanumeric characters, dots, dashes, and underscores.
    """
    import re
    import os

    base, ext = os.path.splitext(name)
    base = re.sub(r'[^a-zA-Z0-9._-]', '_', base)
    if len(base) > 80:
        base = base[:80]
    ext = re.sub(r'[^a-zA-Z0-9.]', '', ext)[:10]
    return f"{base}{ext}"


def _discard_links(node: object) -> None:
    """Recursively replace every Link node with its inline content.

    The link text (and any image it wrapped) is kept in place; the URL is
    dropped.

    Args:
        node: An AST node to descend into.
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
            _discard_links(c)


def _remove_images(node: Node) -> None:
    """Recursively drop every Image node from the tree."""
    for lst in child_lists(node):
        lst[:] = [c for c in lst if not isinstance(c, Image)]
        for c in lst:
            _remove_images(c)


def _download_remote_images(doc: Document, output_dir: str | None, image_dir_name: str | None, is_url: bool, source: str) -> None:
    """Recursively traverses the AST, downloads remote images, and rewrites their paths.

    Args:
        doc: Root Document AST node.
        output_dir: Optional output base directory.
        image_dir_name: Optional image subdirectory name.
        is_url: True if the source was a URL.
        source: The original source text or file path.
    """
    import urllib.request
    import urllib.parse
    import os
    from .logger import log_action, log_warning

    base_dir = os.getcwd()
    if output_dir:
        base_dir = output_dir
    elif os.path.exists(source) and os.path.isfile(source):
        base_dir = os.path.dirname(os.path.abspath(source))

    target_dir = base_dir
    if image_dir_name:
        target_dir = os.path.join(base_dir, image_dir_name)
    
    dir_created = False

    def _process(node: Node) -> None:
        nonlocal dir_created
        if isinstance(node, Image):
            is_node_url = node.src.startswith(("http://", "https://"))
            is_relative_remote = is_url and not node.src.startswith(("data:", "http://", "https://"))

            if is_node_url or is_relative_remote:
                try:
                    img_url = node.src
                    if is_relative_remote:
                        img_url = urllib.parse.urljoin(source, node.src)

                    basename = _extract_image_filename(img_url)
                    basename = _sanitize_filename(basename)
                    
                    if not dir_created:
                        os.makedirs(target_dir, exist_ok=True)
                        dir_created = True

                    local_path = os.path.join(target_dir, basename)
                    is_identical = False

                    log_action(f"Downloading remote image: {img_url}")
                    req = urllib.request.Request(img_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with _net.open_url(req, timeout=15) as response:
                        img_data = response.read()
                        content_type = response.headers.get('Content-Type', '')

                    # Resolve correct extension from Content-Type
                    import mimetypes
                    mime_type = content_type.split(';')[0].strip().lower()
                    inferred_ext = mimetypes.guess_extension(mime_type)
                    if mime_type == 'image/svg+xml':
                        inferred_ext = '.svg'

                    if inferred_ext:
                        base, ext = os.path.splitext(basename)
                        if not ext or ext.lower() != inferred_ext.lower():
                            basename = f"{base}{inferred_ext}"

                    local_path = os.path.join(target_dir, basename)
                    is_identical = False

                    # Check if an identical file already exists at the target path (basename)
                    if os.path.exists(local_path):
                        try:
                            with open(local_path, "rb") as f:
                                if f.read() == img_data:
                                    is_identical = True
                                    local_name = basename
                        except Exception:
                            pass

                    if not is_identical:
                        base, ext = os.path.splitext(basename)
                        counter = 0
                        local_name = basename
                        # Look for either a non-existent path or an existing file with the exact same content
                        while os.path.exists(local_path):
                            try:
                                with open(local_path, "rb") as f:
                                    if f.read() == img_data:
                                        is_identical = True
                                        break
                            except Exception:
                                     pass
                            counter += 1
                            local_name = f"{base}_{counter}{ext}"
                            local_path = os.path.join(target_dir, local_name)

                    if not is_identical:
                        with open(local_path, "wb") as f:
                            f.write(img_data)

                    node.src = f"{image_dir_name}/{local_name}" if image_dir_name else local_name
                except Exception as exc:
                    log_warning(f"Failed to download remote image {node.src}: {exc}")

    for node in walk(doc):
        _process(node)


def _is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _parse(
    from_format: str,
    options: ConvertOptions,
    config: AppConfig,
    *,
    text: str | None = None,
    path: str | None = None,
    output_dir: str | None = None,
    image_dir_name: str | None = None,
    source_url: str | None = None,
) -> Document:
    """Run the parser for ``from_format``: binary formats read ``path``, the others ``text``."""
    if from_format == "pdf":
        return parse_pdf(
            path, config=config, pdf_mode=options.pdf_mode, code_parsing=options.code_parsing,
            output_dir=output_dir, image_dir_name=image_dir_name,
            write_images=options.image_handling != "discard",
        )
    if from_format == "image":
        return parse_image(path, config=config)
    if from_format == "markdown":
        return parse_markdown(text, code_parsing=options.code_parsing)
    if from_format == "html":
        use_profiles = config.html.site_cleanup if options.site_cleanup is None else options.site_cleanup
        profiles = (
            resolve_profiles(source_url, text, config.html)
            if (options.extract_html and use_profiles) else ()
        )
        return parse_html(text, extract_html=options.extract_html, profiles=profiles)
    if from_format == "latex":
        return parse_latex(text)
    return parse_json(text)


_RENDERERS = {
    "markdown": lambda doc, options: render_markdown(doc),
    "html": lambda doc, options: render_html(doc, template_name=options.template),
    "latex": lambda doc, options: render_latex(doc),
    "json": lambda doc, options: render_json(doc),
}


def _image_base_dir(from_format: str, output_dir: str | None, source_url: str | None, source_path: str | None) -> str:
    """Directory that relative image paths resolve against for embed/describe."""
    if (from_format == "pdf" or source_url) and output_dir:
        return output_dir
    if source_path:
        return os.path.dirname(os.path.abspath(source_path))
    return os.getcwd()


def _embed_images(doc: Document, base_dir: str) -> None:
    """Replace the src of every local image with a base64 data URL."""
    from .logger import log_warning
    for node in walk(doc):
        if isinstance(node, Image):
            img_path = node.src
            if not os.path.isabs(img_path):
                img_path = os.path.join(base_dir, img_path)
            if os.path.exists(img_path):
                try:
                    mime_type, _ = mimetypes.guess_type(img_path)
                    if not mime_type:
                        mime_type = "image/png"
                    with open(img_path, "rb") as f:
                        img_b64 = base64.b64encode(f.read()).decode("utf-8")
                    node.src = f"data:{mime_type};base64,{img_b64}"
                except OSError as exc:
                    log_warning(f"Could not embed image {img_path}: {exc}")


def _transform_and_render(
    doc: Document,
    from_format: str,
    to_format: str,
    options: ConvertOptions,
    config: AppConfig,
    *,
    output_dir: str | None,
    image_dir_name: str | None,
    source_url: str | None,
    source_path: str | None,
) -> str:
    """Apply the image and link passes to a parsed document, then render it."""
    handling = options.image_handling
    if from_format != "json" and handling != "discard":
        _download_remote_images(doc, output_dir, image_dir_name, source_url is not None,
                                source_url or source_path or "")

    if handling == "auto":
        handling = OUTPUT_FORMATS[to_format].auto_images

    if from_format != "json":
        if handling in ("describe", "embed", "auto_latex"):
            base_dir = _image_base_dir(from_format, output_dir, source_url, source_path)
            if handling == "embed":
                _embed_images(doc, base_dir)
            else:
                from .image_describer import process_images
                process_images(doc, base_dir, config=config, latex_auto=handling == "auto_latex")
        elif handling == "discard":
            _remove_images(doc)

    if options.discard_links:
        _discard_links(doc)

    return _RENDERERS[to_format](doc, options)


def _check_formats(from_format: str | None, to_format: str) -> None:
    check_choice("to_format", to_format, TEXT_OUTPUT_FORMATS)
    if from_format is not None:
        check_choice("from_format", from_format, INPUT_FORMATS)


def convert_text(
    text: str,
    from_format: str,
    to_format: str,
    options: ConvertOptions | None = None,
    *,
    output_dir: str | None = None,
    image_dir_name: str | None = None,
    config: AppConfig | None = None,
) -> str:
    """Convert a document given as text and return the result as a string.

    Args:
        text: The source document.
        from_format: Its format: a non-binary name in ``formats.INPUT_FORMATS``
            (``"markdown"``, ``"html"``, ``"latex"``, ``"json"``).
        to_format: Target format (``"markdown"``, ``"html"``, ``"latex"``, ``"json"``).
        options: Conversion options; defaults when None.
        output_dir: Directory where remote images are downloaded (current
            directory when None).
        image_dir_name: Subdirectory of ``output_dir`` for those images.
        config: Configuration to use instead of config.json.

    Returns:
        The converted document.

    Raises:
        ValueError: If a format is unknown, or ``from_format`` needs a file
            (PDF, image).
        ImportError: If the image handling needs ``unified_ai_client`` and it
            is not installed.
    """
    _check_formats(from_format, to_format)
    if INPUT_FORMATS[from_format].binary:
        raise ValueError(f"{from_format} input needs a file: call convert() with its path.")
    options = options or ConvertOptions()
    config = config or load_config()
    doc = _parse(from_format, options, config, text=text)
    return _transform_and_render(doc, from_format, to_format, options, config,
                                 output_dir=output_dir, image_dir_name=image_dir_name,
                                 source_url=None, source_path=None)


def convert(
    source: str,
    to_format: str,
    options: ConvertOptions | None = None,
    *,
    from_format: str | None = None,
    output_dir: str | None = None,
    image_dir_name: str | None = None,
    config: AppConfig | None = None,
) -> str:
    """Convert a file or a remote URL and return the result as a string.

    For text given directly, use ``convert_text``.

    Args:
        source: A file path, or an ``http://``/``https://`` URL.
        to_format: Target format (``"markdown"``, ``"html"``, ``"latex"``,
            ``"json"``); PDF output goes through ``save_to_file``.
        options: Conversion options; defaults when None.
        from_format: Source format; inferred from the file or URL extension
            when None (a URL without a known extension is read as HTML).
        output_dir: Directory for downloaded and extracted images.
        image_dir_name: Subdirectory of ``output_dir`` for those images.
        config: Configuration to use instead of config.json.

    Returns:
        The converted document.

    Raises:
        FileNotFoundError: If ``source`` is neither a URL nor an existing file.
        ValueError: If a format is unknown or cannot be inferred.
        RuntimeError: If the URL cannot be downloaded.
        ImportError: If the conversion needs ``unified_ai_client`` and it is
            not installed.
    """
    _check_formats(from_format, to_format)
    options = options or ConvertOptions()
    config = config or load_config()
    if _is_url(source):
        if from_format is None:
            from_format = infer_input_format(urllib.parse.urlparse(source).path) or "html"
        return _convert_url(source, from_format, to_format, options, config,
                            output_dir=output_dir, image_dir_name=image_dir_name)

    if not os.path.isfile(source):
        raise FileNotFoundError(f"Source file not found: {source}")
    if from_format is None:
        from_format = infer_input_format(source)
        if from_format is None:
            raise ValueError(f"Could not infer the input format from the extension of {source}; pass from_format.")
    if INPUT_FORMATS[from_format].binary:
        doc = _parse(from_format, options, config, path=source,
                     output_dir=output_dir, image_dir_name=image_dir_name)
    else:
        doc = _parse(from_format, options, config, text=_read_text(source))
    return _transform_and_render(doc, from_format, to_format, options, config,
                                 output_dir=output_dir, image_dir_name=image_dir_name,
                                 source_url=None, source_path=source)


def _convert_url(
    url: str,
    from_format: str,
    to_format: str,
    options: ConvertOptions,
    config: AppConfig,
    *,
    output_dir: str | None,
    image_dir_name: str | None,
) -> str:
    """Download ``url`` (to a temporary file for binary formats) and convert it."""
    from .logger import log_action, log_warning

    log_action(f"Downloading remote source: {url}")
    temp_file_path = None
    text = None
    try:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            if INPUT_FORMATS[from_format].binary:
                suffix = (os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
                          or INPUT_FORMATS[from_format].extensions[0])
                fd, temp_file_path = tempfile.mkstemp(suffix=suffix, dir=output_dir or os.getcwd())
                with _net.open_url(req, timeout=30) as response:
                    with os.fdopen(fd, "wb") as f:
                        f.write(response.read())
            else:
                with _net.open_url(req, timeout=30) as response:
                    text = response.read().decode('utf-8', errors='ignore')
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                raise RuntimeError(
                    f"Failed to download source URL {url}: HTTP Error 403 Forbidden/Blocked. "
                    "This server blocks automated scrapers. "
                    "Please download the file manually and convert the local file."
                ) from exc
            raise RuntimeError(f"Failed to download source URL {url}: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"Failed to download source URL {url}: {exc}") from exc

        doc = _parse(from_format, options, config, text=text, path=temp_file_path,
                     output_dir=output_dir, image_dir_name=image_dir_name, source_url=url)
        return _transform_and_render(doc, from_format, to_format, options, config,
                                     output_dir=output_dir, image_dir_name=image_dir_name,
                                     source_url=url, source_path=temp_file_path)
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError as exc:
                log_warning(f"Could not remove temporary file {temp_file_path}: {exc}")


def save_to_file(
    source: str,
    output_path: str,
    options: ConvertOptions | None = None,
    *,
    from_format: str | None = None,
    config: AppConfig | None = None,
) -> None:
    """Convert a file or a remote URL and write the result to ``output_path``.

    The output format comes from the extension of ``output_path``; images are
    written to a ``<output stem>_images`` folder next to it. A ``.pdf`` output
    is the HTML rendering with the light template, printed by
    ``renderers.pdf_renderer.render_pdf``: ``options.template`` is ignored and
    images are embedded (``auto`` and ``link`` both act as ``embed``), so the
    PDF is self-contained and no image folder is left next to it.

    Args:
        source: A file path, or an ``http://``/``https://`` URL.
        output_path: Where to write the result.
        options: Conversion options; defaults when None.
        from_format: Source format; inferred from the extension when None.
        config: Configuration to use instead of config.json.

    Raises:
        ValueError: If the output format cannot be inferred, or the output
            path is the source file itself.
        FileNotFoundError, RuntimeError, ImportError: As ``convert``.
    """
    options = options or ConvertOptions()
    to_format = infer_output_format(output_path)
    if to_format is None:
        raise ValueError(f"Could not infer the output format from the extension of {output_path}.")
    if (not _is_url(source) and os.path.exists(source) and os.path.exists(output_path)
            and os.path.samefile(source, output_path)):
        raise ValueError(f"The output path is the source file itself: {output_path}")

    out_path = pathlib.Path(output_path)
    if to_format == "pdf":
        from .renderers.pdf_renderer import render_pdf
        handling = "embed" if options.image_handling in ("auto", "link") else options.image_handling
        pdf_options = replace(options, template=PDF_TEMPLATE, image_handling=handling)
        with tempfile.TemporaryDirectory(prefix="textconverter_pdf_") as tmp:
            html = convert(source, "html", pdf_options, from_format=from_format,
                           output_dir=tmp, image_dir_name="images", config=config)
            render_pdf(html, output_path, base_dir=tmp)
        return

    result = convert(source, to_format, options, from_format=from_format,
                     output_dir=str(out_path.parent), image_dir_name=f"{out_path.stem}_images",
                     config=config)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(result)
