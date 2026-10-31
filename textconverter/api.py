from __future__ import annotations
import contextlib
import os
import pathlib
import re
import tempfile
import urllib.parse
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from . import _net
from .ast import Document, Table, walk
from .code_detector import fence_code_paragraphs
from .images import ImagePaths, discard_links, embed_images, lower_image_descriptions, remove_images
from .logger import log_action, log_warning

from .parsers.markdown_parser import parse_markdown
from .parsers.html_parser import parse_html
from .parsers.latex_parser import parse_latex
from .parsers.pdf_parser import parse_pdf
from .parsers.docx_parser import parse_docx
from .parsers.pptx_parser import parse_pptx
from .parsers.csv_parser import parse_csv
from .parsers.xlsx_parser import parse_xlsx
from .parsers.image_parser import parse_image
from .parsers.json_parser import parse_json

from .renderers.markdown_renderer import render_markdown
from .renderers.html_renderer import render_html
from .renderers.latex_renderer import render_latex
from .renderers.json_renderer import render_json
from .renderers.csv_renderer import render_csv, render_csv_files

from .site_profiles import resolve_profiles
from .config import AppConfig, load_config
from .formats import (
    INPUT_FORMATS, OUTPUT_FORMATS, TEXT_OUTPUT_FORMATS, check_choice,
    infer_input_format, infer_input_format_from_media_type, infer_output_format,
)
from .options import ConvertOptions

# HTML template that PDF output is printed from.
PDF_TEMPLATE = "light"

# Turns the transformed document into the conversion's result (a string for the text formats).
Render = Callable[[Document], Any]


def _is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def _read_text(path: str, from_format: str) -> str:
    """The text of a source file: UTF-8, except CSV, which also reads a BOM and falls back to cp1252."""
    if from_format == "csv":
        with open(path, "rb") as f:
            data = f.read()
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("cp1252", errors="replace")
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
    if from_format in ("docx", "pptx"):
        parser = parse_docx if from_format == "docx" else parse_pptx
        doc = parser(path, output_dir=output_dir, image_dir_name=image_dir_name,
                     write_images=options.image_handling != "discard", keep_indentation=options.code_parsing)
        if options.code_parsing:
            fence_code_paragraphs(doc)
        return doc
    if from_format == "xlsx":
        return parse_xlsx(path, output_dir=output_dir, image_dir_name=image_dir_name,
                          write_images=options.image_handling != "discard")
    if from_format == "image":
        return parse_image(path, config=config)
    if from_format == "csv":
        return parse_csv(text)
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
    "csv": lambda doc, options: render_csv(doc),
}


def _text_render(to_format: str, options: ConvertOptions) -> Render:
    """The render step of ``convert``: the document as text in ``to_format``."""
    return lambda doc: _RENDERERS[to_format](doc, options)


def _image_handling(options: ConvertOptions, to_format: str) -> str:
    """The image handling a conversion uses: ``auto`` resolved by the target format."""
    if options.image_handling == "auto":
        return OUTPUT_FORMATS[to_format].auto_images
    return options.image_handling


@contextlib.contextmanager
def _image_folder(handling: str, output_dir: str | None, image_dir_name: str | None):
    """Yield ``(parent, name)`` of the folder the conversion writes its images to.

    Embedded images only pass through a temporary folder, so no image folder
    is left next to the output.
    """
    if handling != "embed":
        yield output_dir, image_dir_name
        return
    with tempfile.TemporaryDirectory(prefix="textconverter_images_") as tmp:
        yield tmp, "images"


def _doc_dir(from_format: str, output_dir: str | None, source_path: str | None) -> str:
    """Directory the parsed document's relative image paths resolve against.

    The PDF, Word, PowerPoint and Excel parsers write their images under ``output_dir`` (or the
    current directory); an image source path is relative to the current directory;
    a text source references images next to the source file; text given
    directly resolves against the current directory.
    """
    if from_format in ("pdf", "docx", "pptx", "xlsx"):
        return output_dir or os.getcwd()
    if source_path and from_format != "image":
        return os.path.dirname(os.path.abspath(source_path))
    return os.getcwd()


def _transform_and_render(
    doc: Document,
    from_format: str,
    to_format: str,
    options: ConvertOptions,
    config: AppConfig,
    *,
    output_dir: str | None,
    image_parent: str | None,
    image_dir_name: str | None,
    source_url: str | None,
    source_path: str | None,
    render: Render,
) -> Any:
    """Apply the image and link passes to a parsed document, then render it with ``render``.

    Local image paths are absolute while the passes run, so the download
    folder, the embedder and the AI describer agree on every file; the paths
    are made relative to the output directory again before rendering.
    Images are written to ``image_dir_name`` under ``image_parent`` (see
    ``_image_folder``), else under the output directory.
    """
    handling = _image_handling(options, to_format)

    if from_format != "json":
        if handling == "discard":
            remove_images(doc)
        else:
            doc_dir = _doc_dir(from_format, image_parent, source_path)
            out_dir = output_dir or _doc_dir(from_format, None, source_path)
            paths = ImagePaths(doc_dir)
            # Download first: on a web page, relative sources are remote.
            paths.download(doc, os.path.join(image_parent or out_dir, image_dir_name or ""), source_url)
            paths.absolutize(doc)
            # Image sources and raster PDF pages have been through the AI already.
            transcribed = from_format == "image" or (from_format == "pdf" and options.pdf_mode == "raster")
            if handling in ("describe", "auto_latex") and not transcribed:
                from .image_describer import process_images
                process_images(doc, doc_dir, config=config, latex_auto=handling == "auto_latex")
            elif handling == "embed":
                embed_images(doc)
            paths.relativize(doc, out_dir)

    if options.discard_links:
        discard_links(doc)

    if to_format != "json":
        lower_image_descriptions(doc)
    if to_format in ("csv", "xlsx"):
        _require_table(doc, from_format, options)
    return render(doc)


def _require_table(doc: Document, from_format: str, options: ConvertOptions) -> None:
    """Raise ValueError, with the likely cause, when a spreadsheet target has no table to write."""
    if any(isinstance(node, Table) for node in walk(doc)):
        return
    hint = ""
    if from_format == "pdf" and options.pdf_mode == "text":
        hint = " In a PDF's text layer only tables drawn with ruled lines are found: try pdf_mode 'raster'."
    elif from_format == "image" or from_format == "pdf":
        hint = " The AI did not transcribe a table: check the messages above."
    raise ValueError(f"The document has no table to write as a spreadsheet.{hint}")


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
            (PDF, Word, image).
        ImportError: If the image handling needs ``unified_ai_client`` and it
            is not installed.
    """
    _check_formats(from_format, to_format)
    if INPUT_FORMATS[from_format].binary:
        raise ValueError(f"{from_format} input needs a file: call convert() with its path.")
    options = options or ConvertOptions()
    config = config or load_config()
    doc = _parse(from_format, options, config, text=text)
    with _image_folder(_image_handling(options, to_format), output_dir, image_dir_name) as (parent, name):
        return _transform_and_render(doc, from_format, to_format, options, config,
                                     output_dir=output_dir, image_parent=parent, image_dir_name=name,
                                     source_url=None, source_path=None,
                                     render=_text_render(to_format, options))


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
        from_format: Source format. When None it is inferred from the file
            extension; for a URL, from the response's ``Content-Type``, then
            the URL's extension, else HTML.
        output_dir: Directory for downloaded and extracted images.
        image_dir_name: Subdirectory of ``output_dir`` for those images.
        config: Configuration to use instead of config.json.

    Returns:
        The converted document.

    Raises:
        FileNotFoundError: If ``source`` is neither a URL nor an existing file.
        ValueError: If a format is unknown or cannot be inferred.
        DownloadError: If the URL cannot be downloaded (a ``RuntimeError``).
        ImportError: If the conversion needs ``unified_ai_client`` and it is
            not installed.
    """
    _check_formats(from_format, to_format)
    options = options or ConvertOptions()
    return _convert(source, to_format, options, config or load_config(), from_format=from_format,
                    output_dir=output_dir, image_dir_name=image_dir_name,
                    render=_text_render(to_format, options))


def _convert(
    source: str,
    to_format: str,
    options: ConvertOptions,
    config: AppConfig,
    *,
    from_format: str | None,
    output_dir: str | None,
    image_dir_name: str | None,
    render: Render,
) -> Any:
    """Parse a file or URL, transform it and pass the document to ``render`` (what ``convert`` does).

    ``render`` runs while the conversion's temporary image folder still
    exists, so a renderer can read the images from disk.
    """
    if _is_url(source):
        return _convert_url(source, from_format, to_format, options, config,
                            output_dir=output_dir, image_dir_name=image_dir_name, render=render)

    if not os.path.isfile(source):
        raise FileNotFoundError(f"Source file not found: {source}")
    if from_format is None:
        from_format = infer_input_format(source)
        if from_format is None:
            raise ValueError(f"Could not infer the input format from the extension of {source}; pass from_format.")
    with _image_folder(_image_handling(options, to_format), output_dir, image_dir_name) as (parent, name):
        if INPUT_FORMATS[from_format].binary:
            doc = _parse(from_format, options, config, path=source, output_dir=parent, image_dir_name=name)
        else:
            doc = _parse(from_format, options, config, text=_read_text(source, from_format))
        return _transform_and_render(doc, from_format, to_format, options, config,
                                     output_dir=output_dir, image_parent=parent, image_dir_name=name,
                                     source_url=None, source_path=source, render=render)


_META_CHARSET = re.compile(rb'<meta[^>]+charset\s*=\s*["\']?([\w.:-]+)', re.IGNORECASE)


def _decode(download: _net.Download) -> str:
    """Decode a downloaded text document.

    The charset comes from ``Content-Type``, else from a ``<meta charset>``
    near the top, else UTF-8; undecodable bytes become U+FFFD instead of
    being dropped.
    """
    charset = download.charset
    if not charset:
        match = _META_CHARSET.search(download.data[:4096])
        charset = match.group(1).decode("ascii") if match else "utf-8"
    if charset.lower().replace("_", "-") in ("utf-8", "utf8"):
        charset = "utf-8-sig"
    try:
        return download.data.decode(charset, errors="replace")
    except LookupError:
        log_warning(f"Unknown charset '{charset}', decoding as UTF-8.")
        return download.data.decode("utf-8", errors="replace")


def _convert_url(
    url: str,
    from_format: str | None,
    to_format: str,
    options: ConvertOptions,
    config: AppConfig,
    *,
    output_dir: str | None,
    image_dir_name: str | None,
    render: Render,
) -> Any:
    """Download ``url`` and convert it; binary formats go through a temporary file."""
    log_action(f"Downloading remote source: {url}")
    download = _net.fetch(url, timeout=30)
    url_path = urllib.parse.urlparse(url).path
    if from_format is None:
        from_format = (infer_input_format_from_media_type(download.content_type)
                       or infer_input_format(url_path) or "html")

    fmt = INPUT_FORMATS[from_format]
    folder = _image_folder(_image_handling(options, to_format), output_dir, image_dir_name)
    if not fmt.binary:
        doc = _parse(from_format, options, config, text=_decode(download), source_url=url)
        with folder as (parent, name):
            return _transform_and_render(doc, from_format, to_format, options, config,
                                         output_dir=output_dir, image_parent=parent, image_dir_name=name,
                                         source_url=url, source_path=None, render=render)

    ext = os.path.splitext(url_path)[1].lower()
    fd, temp_path = tempfile.mkstemp(suffix=ext if ext in fmt.extensions else fmt.extensions[0])
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(download.data)
        with folder as (parent, name):
            doc = _parse(from_format, options, config, path=temp_path,
                         output_dir=parent, image_dir_name=name, source_url=url)
            return _transform_and_render(doc, from_format, to_format, options, config,
                                         output_dir=output_dir, image_parent=parent, image_dir_name=name,
                                         source_url=url, source_path=temp_path, render=render)
    finally:
        try:
            os.remove(temp_path)
        except OSError as exc:
            log_warning(f"Could not remove temporary file {temp_path}: {exc}")


def _office_writer(to_format: str) -> Callable[..., None]:
    """The ``render_*(doc, path, base_dir=...)`` function of an Office or Excel output format."""
    if to_format == "docx":
        from .renderers.docx_renderer import render_docx
        return render_docx
    if to_format == "xlsx":
        from .renderers.xlsx_renderer import render_xlsx
        return render_xlsx
    from .renderers.pptx_renderer import render_pptx
    return render_pptx


def _save_office(
    source: str,
    output_path: str,
    to_format: str,
    options: ConvertOptions,
    from_format: str | None,
    config: AppConfig | None,
) -> None:
    """Write the converted ``source`` as a Word, PowerPoint or Excel file; the file appears only once complete."""
    write = _office_writer(to_format)
    if from_format is not None:
        check_choice("from_format", from_format, INPUT_FORMATS)
    handling = "embed" if options.image_handling in ("auto", "link") else options.image_handling
    office_options = replace(options, image_handling=handling)
    directory = os.path.dirname(os.path.abspath(output_path))
    fd, temp_path = tempfile.mkstemp(suffix=f".{to_format}.tmp", dir=directory)
    os.close(fd)
    try:
        _convert(source, to_format, office_options, config or load_config(), from_format=from_format,
                 output_dir=directory, image_dir_name=f"{pathlib.Path(output_path).stem}_images",
                 render=lambda doc: write(doc, temp_path, base_dir=directory))
        os.replace(temp_path, output_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _save_csv(
    source: str,
    output_path: str,
    options: ConvertOptions,
    from_format: str | None,
    config: AppConfig | None,
) -> list[str]:
    """Write the tables of ``source`` as CSV: ``output_path``, or ``<stem>_<sheet>.csv`` for each of several.

    Returns:
        The paths written.
    """
    out_path = pathlib.Path(output_path)
    files = _convert(source, "csv", options, config or load_config(), from_format=from_format,
                     output_dir=str(out_path.parent), image_dir_name=f"{out_path.stem}_images",
                     render=render_csv_files)
    written = []
    for suffix, text in files:
        target = out_path.with_name(f"{out_path.stem}{suffix}{out_path.suffix}")
        with open(target, 'w', encoding='utf-8-sig', newline='') as f:
            f.write(text)
        written.append(str(target))
    return written


def save_to_file(
    source: str,
    output_path: str,
    options: ConvertOptions | None = None,
    *,
    from_format: str | None = None,
    config: AppConfig | None = None,
) -> list[str]:
    """Convert a file or a remote URL and write the result to ``output_path``.

    The output format comes from the extension of ``output_path``; images are
    written to a ``<output stem>_images`` folder next to it, unless they are
    embedded (``embed``, or ``auto`` for HTML and Word), which leaves no folder. A ``.pdf`` output
    is the HTML rendering with the light template, printed by
    ``renderers.pdf_renderer.render_pdf``: ``options.template`` is ignored and
    images are embedded (``auto`` and ``link`` both act as ``embed``), so the
    PDF is self-contained and no image folder is left next to it. A ``.docx``
    output is the document written by ``renderers.docx_renderer.render_docx``,
    with the same image rules and no template; so are ``.pptx`` and ``.xlsx``
    (the latter keeps only the tables, one sheet each). A ``.csv`` output holds the
    document's tables only: one file, or ``<stem>_<sheet name>.csv`` per table
    when there are several (the name is the nearest heading above the table).

    Args:
        source: A file path, or an ``http://``/``https://`` URL.
        output_path: Where to write the result.
        options: Conversion options; defaults when None.
        from_format: Source format; inferred from the extension when None.
        config: Configuration to use instead of config.json.

    Returns:
        The paths written: ``[output_path]``, or one path per table for a
        ``.csv`` output with several tables.

    Raises:
        ValueError: If the output format cannot be inferred, the output path
            is the source file itself, or a ``.csv`` or ``.xlsx`` output has no
            table to write.
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
    if to_format == "csv":
        return _save_csv(source, output_path, options, from_format, config)
    if to_format in ("docx", "pptx", "xlsx"):
        _save_office(source, output_path, to_format, options, from_format, config)
        return [output_path]
    if to_format == "pdf":
        from .renderers.pdf_renderer import render_pdf
        handling = "embed" if options.image_handling in ("auto", "link") else options.image_handling
        pdf_options = replace(options, template=PDF_TEMPLATE, image_handling=handling)
        with tempfile.TemporaryDirectory(prefix="textconverter_pdf_") as tmp:
            html = convert(source, "html", pdf_options, from_format=from_format,
                           output_dir=tmp, image_dir_name="images", config=config)
            render_pdf(html, output_path, base_dir=tmp)
        return [output_path]

    result = convert(source, to_format, options, from_format=from_format,
                     output_dir=str(out_path.parent), image_dir_name=f"{out_path.stem}_images",
                     config=config)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(result)
    return [output_path]
