from __future__ import annotations
import os
import shutil
import tempfile
from ..ast import Document, Image, walk
from ..config import AppConfig
from ..formats import PDF_MODES, check_choice
from ..logger import log_action, log_warning
from .markdown_parser import parse_markdown

# GLM-OCR's reference pipeline renders pages at 200 DPI; more mostly costs time.
RASTER_DPI = 200


def _import_pymupdf4llm():
    """Import pymupdf4llm without its layout-package hint.

    The hint is printed to stdout on import, and in MCP mode stdout carries the
    protocol stream.
    """
    try:
        import pymupdf
        if hasattr(pymupdf, "no_recommend_layout"):
            pymupdf.no_recommend_layout()
        import pymupdf4llm
    except ImportError:
        raise ImportError("pymupdf4llm is required to parse PDF files. Install it with `pip install pymupdf4llm`.")
    return pymupdf4llm


def parse_pdf(
    file_path: str,
    *,
    config: AppConfig,
    pdf_mode: str = "text",
    code_parsing: bool = False,
    output_dir: str | None = None,
    image_dir_name: str | None = None,
    write_images: bool = True,
) -> Document:
    """Parse a PDF into an AST Document.

    Args:
        file_path: PDF file path.
        config: Application configuration (used by ``raster`` mode).
        pdf_mode: ``"text"`` reads the text layer with pymupdf4llm; ``"raster"``
            renders every page to an image and transcribes it with the AI
            describer, for scans or PDFs whose text layer is unusable.
        code_parsing: Enable heuristic code-block detection (``text`` mode only).
        output_dir: Base directory for extracted images (current directory if None).
        image_dir_name: Image subdirectory name inside ``output_dir``.
        write_images: Extract embedded images (``text`` mode only).

    Raises:
        ValueError: If ``pdf_mode`` is not one of ``formats.PDF_MODES``.
        ImportError: If ``raster`` mode is requested without ``unified_ai_client``.
    """
    check_choice("pdf_mode", pdf_mode, PDF_MODES)
    if pdf_mode == "raster":
        return _parse_raster(file_path, output_dir, image_dir_name, config)

    pymupdf4llm = _import_pymupdf4llm()

    # Extract markdown, saving images into the target directory
    kwargs = {'write_images': write_images}
    created_dir = None
    if write_images and output_dir:
        target_dir = output_dir
        if image_dir_name:
            target_dir = os.path.join(output_dir, image_dir_name)
            os.makedirs(target_dir, exist_ok=True)
            created_dir = target_dir
        kwargs['image_path'] = target_dir
    md_text = pymupdf4llm.to_markdown(file_path, **kwargs)

    # Clean up created_dir if it was created but remains empty (no images in PDF)
    if created_dir and os.path.exists(created_dir):
        try:
            if not os.listdir(created_dir):
                os.rmdir(created_dir)
        except OSError as exc:
            log_warning(f"Could not remove empty image directory {created_dir}: {exc}")

    if not write_images:
        import re
        md_text = re.sub(r'\*\*==>\s*picture.*?<==\*\*\n?', '', md_text)

    # Re-parse through our own Markdown parser to keep the AST consistent
    doc = parse_markdown(md_text, code_parsing=code_parsing)

    # Strip the directory prefix from image paths so references stay relative to the document
    for node in walk(doc):
        if isinstance(node, Image):
            basename = os.path.basename(node.src)
            node.src = f"{image_dir_name}/{basename}" if image_dir_name else basename
    return doc


def _parse_raster(
    file_path: str,
    output_dir: str | None,
    image_dir_name: str | None,
    config: AppConfig,
) -> Document:
    """Render each page to an image and let the AI describer transcribe the pages.

    Pages go through the whole image pipeline (classification, then OCR or
    description), batched so each model loads once. The page images live in a
    temporary folder; a page that could not be transcribed is kept as an image
    in the output image folder, so the content is not lost.
    """
    import pymupdf
    from ..image_describer import ai_client_available, transcribe_images

    if not ai_client_available():
        raise ImportError(
            "PDF raster mode needs the 'unified_ai_client' package to transcribe the pages. "
            "Please install it first (e.g. via requirements_prod.txt)."
        )

    with tempfile.TemporaryDirectory(prefix="textconverter_pages_") as tmp:
        with pymupdf.open(file_path) as pdf:
            log_action(f"Rendering {pdf.page_count} pages at {RASTER_DPI} DPI...")
            page_paths = []
            for number, page in enumerate(pdf, 1):
                path = os.path.join(tmp, f"page_{number:04d}.png")
                page.get_pixmap(dpi=RASTER_DPI).save(path)
                page_paths.append(path)

        doc = transcribe_images(page_paths, config=config)

        keep_dir = os.path.join(output_dir or os.getcwd(), image_dir_name or "")
        for node in walk(doc):
            if isinstance(node, Image) and node.src in page_paths:
                os.makedirs(keep_dir, exist_ok=True)
                basename = os.path.basename(node.src)
                shutil.copy(node.src, os.path.join(keep_dir, basename))
                node.src = f"{image_dir_name}/{basename}" if image_dir_name else basename
    return doc
