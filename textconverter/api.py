from __future__ import annotations
import pathlib
from .ast import Document

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
    from .ast import Image
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

    def _process(node):
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
                    with urllib.request.urlopen(req, timeout=15) as response:
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

        if hasattr(node, 'children'):
            for c in node.children: _process(c)
        if hasattr(node, 'content') and isinstance(node.content, list):
            for c in node.content: _process(c)
        if hasattr(node, 'items'):
            for c in node.items: _process(c)
        if hasattr(node, 'rows'):
            for c in node.rows: _process(c)
        if hasattr(node, 'cells'):
            for c in node.cells: _process(c)
        if hasattr(node, 'headers') and getattr(node, 'headers', None):
            for c in node.headers: _process(c)

    _process(doc)



def convert(source: str, to_format: str, from_format: str | None = None, template: str = "plain", is_file: bool = False, output_dir: str | None = None, image_dir_name: str | None = None, image_handling: str = "auto", code_parsing: bool = False, extract_html: bool = False) -> str:
    """
    Convert text or file to a specific format.
    If is_file is True, source is presumed to be a file path.
    Otherwise, if source ends with .pdf, .md, .html, .tex, it will try to infer it if from_format is not given.
    """
    is_url = source.startswith(("http://", "https://"))
    original_source = source
    if from_format is None:
        if is_url:
            import urllib.parse
            parsed_url = urllib.parse.urlparse(source)
            ext = pathlib.Path(parsed_url.path).suffix.lower()
            if ext == '.pdf': from_format = 'pdf'
            elif ext in ('.md', '.markdown'): from_format = 'markdown'
            elif ext in ('.html', '.htm'): from_format = 'html'
            elif ext in ('.tex', '.latex'): from_format = 'latex'
            elif ext == '.json': from_format = 'json'
            elif ext in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'): from_format = 'image'
            else:
                from_format = 'html'
        elif is_file or pathlib.Path(source).exists():
            ext = pathlib.Path(source).suffix.lower()
            if ext == '.pdf': from_format = 'pdf'
            elif ext in ('.md', '.markdown'): from_format = 'markdown'
            elif ext in ('.html', '.htm'): from_format = 'html'
            elif ext in ('.tex', '.latex'): from_format = 'latex'
            elif ext == '.json': from_format = 'json'
            elif ext in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'): from_format = 'image'
            else:
                raise ValueError(f"Could not infer from_format from source file extension: {ext}")
        else:
            raise ValueError("from_format must be specified when parsing raw text.")

    # 1. Parse into AST
    temp_file_path = None
    try:
        if is_url:
            import urllib.request
            import tempfile
            import os
            import urllib.parse
            from .logger import log_action

            log_action(f"Downloading remote source: {source}")
            try:
                import urllib.error
                req = urllib.request.Request(source, headers={'User-Agent': 'Mozilla/5.0'})
                if from_format in ('pdf', 'image', 'json'):
                    parsed_url = urllib.parse.urlparse(source)
                    suffix = os.path.splitext(parsed_url.path)[1].lower() or f".{from_format}"
                    fd, temp_file_path = tempfile.mkstemp(suffix=suffix, dir=output_dir or os.getcwd())
                    with urllib.request.urlopen(req, timeout=30) as response:
                        with os.fdopen(fd, "wb") as f:
                            f.write(response.read())
                    source = temp_file_path
                    is_file = True
                else:
                    with urllib.request.urlopen(req, timeout=30) as response:
                        text = response.read().decode('utf-8', errors='ignore')
                    source = text
                    is_file = False
            except urllib.error.HTTPError as exc:
                if exc.code == 403:
                    raise RuntimeError(
                        f"Failed to download source URL {source}: HTTP Error 403 Forbidden/Blocked. "
                        "This server blocks automated scrapers. "
                        "Please download the file manually and convert the local file."
                    ) from exc
                raise RuntimeError(f"Failed to download source URL {source}: {exc}") from exc
            except Exception as exc:
                raise RuntimeError(f"Failed to download source URL {source}: {exc}")

        # 1. Parse into AST
        doc = Document()
        if from_format == 'pdf':
            if not is_file and not pathlib.Path(source).exists():
                raise ValueError("PDF parsing requires a file path.")
            doc = parse_pdf(source, output_dir, image_dir_name, write_images=(image_handling != 'discard'), code_parsing=code_parsing)
        elif from_format == 'image':
            if not is_file and not pathlib.Path(source).exists():
                raise ValueError("Image parsing requires a file path.")
            doc = parse_image(source)
        elif from_format == 'json':
            doc = parse_json(source)
        else:
            text = source
            if is_file or pathlib.Path(source).exists():
                with open(source, 'r', encoding='utf-8') as f:
                    text = f.read()

            if from_format == 'markdown':
                doc = parse_markdown(text, code_parsing=code_parsing)
            elif from_format == 'html':
                doc = parse_html(text, extract=extract_html)
            elif from_format == 'latex':
                doc = parse_latex(text)
            else:
                raise ValueError(f"Unknown input format: {from_format}")

        if from_format != 'json' and image_handling != 'discard':
            _download_remote_images(doc, output_dir, image_dir_name, is_url, original_source)

        if image_handling == "auto":
            if to_format == "html":
                image_handling = "embed"
            elif to_format == "latex":
                image_handling = "auto_latex"
            elif to_format == "markdown":
                image_handling = "link"
            elif to_format == "json":
                image_handling = "auto_latex"

        if from_format != 'json':
            if image_handling in ("describe", "embed", "auto_latex"):
                import os
                base_dir = os.getcwd()
                if (from_format == 'pdf' or is_url) and output_dir:
                    base_dir = output_dir
                elif is_file:
                    base_dir = os.path.dirname(os.path.abspath(source))
                    
                if image_handling == "describe":
                    from .image_describer import process_images
                    process_images(doc, base_dir)
                elif image_handling == "auto_latex":
                    from .image_describer import process_images
                    process_images(doc, base_dir, latex_auto=True)
                elif image_handling == "embed":
                    import base64
                    import mimetypes
                    from .ast import Image
                    def _embed(node):
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
                                except Exception:
                                    pass
                        if hasattr(node, 'children'):
                            for c in node.children: _embed(c)
                        if hasattr(node, 'content') and isinstance(node.content, list):
                            for c in node.content: _embed(c)
                        if hasattr(node, 'items'):
                            for c in node.items: _embed(c)
                        if hasattr(node, 'rows'):
                            for c in node.rows: _embed(c)
                        if hasattr(node, 'cells'):
                            for c in node.cells: _embed(c)
                        if hasattr(node, 'headers') and getattr(node, 'headers', None):
                            for c in node.headers: _embed(c)
                    _embed(doc)
                    
            elif image_handling == "discard":
                from .ast import Image
                def _remove_images(node):
                    if hasattr(node, 'children'):
                        node.children = [c for c in node.children if not isinstance(c, Image)]
                        for c in node.children: _remove_images(c)
                    if hasattr(node, 'content') and isinstance(node.content, list):
                        node.content = [c for c in node.content if not isinstance(c, Image)]
                        for c in node.content: _remove_images(c)
                    if hasattr(node, 'items'):
                        for c in node.items: _remove_images(c)
                    if hasattr(node, 'rows'):
                        for c in node.rows: _remove_images(c)
                    if hasattr(node, 'cells'):
                        for c in node.cells: _remove_images(c)
                    if hasattr(node, 'headers') and getattr(node, 'headers', None):
                        for c in node.headers: _remove_images(c)
                _remove_images(doc)

        # 2. Render from AST
        if to_format == 'markdown':
            return render_markdown(doc)
        elif to_format == 'html':
            return render_html(doc, template_name=template)
        elif to_format == 'latex':
            return render_latex(doc, image_handling=image_handling)
        elif to_format == 'json':
            return render_json(doc)
        else:
            raise ValueError(f"Unknown output format: {to_format}")

    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass

def save_to_file(source: str, output_path: str, template: str = "plain", image_handling: str = "auto", code_parsing: bool = False, extract_html: bool = False) -> None:
    """
    Convert and save directly to file, inferring to_format and from_format.
    """
    out_path = pathlib.Path(output_path)
    to_ext = out_path.suffix.lower()
    if to_ext in ('.md', '.markdown'): to_format = 'markdown'
    elif to_ext in ('.html', '.htm'): to_format = 'html'
    elif to_ext in ('.tex', '.latex'): to_format = 'latex'
    elif to_ext == '.json': to_format = 'json'
    else:
        raise ValueError("Could not infer output format from extension.")

    result = convert(source, to_format=to_format, template=template, is_file=True, output_dir=str(out_path.parent), image_dir_name=f"{out_path.stem}_images", image_handling=image_handling, code_parsing=code_parsing, extract_html=extract_html)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(result)
