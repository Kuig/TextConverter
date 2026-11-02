from __future__ import annotations

from dataclasses import dataclass

from .formats import IMAGE_HANDLING_CHOICES, IMAGE_OUTPUT_CHOICES, OUTPUT_FORMATS, PDF_MODES, TEMPLATES, check_choice
from .logger import log_warning


@dataclass
class ConvertOptions:
    """How a document is converted; shared by every conversion entry point.

    Values are validated on creation, so a misspelled option fails before any
    download or AI call.

    Attributes:
        template: HTML template (see ``formats.TEMPLATES``); used for HTML output.
        image_handling: What happens to the images in the document, one of
            ``formats.IMAGE_HANDLING_CHOICES``. ``"auto"`` depends on the
            source and the output format (see the README's Image Handling).
        image_output: How the images left in the document are written, one of
            ``formats.IMAGE_OUTPUT_CHOICES``. ``"auto"`` is the output format's
            default; a format that offers one way only always uses it.
        code_parsing: Fence code blocks found by the heuristic detector
            (Markdown, Word and PowerPoint sources, and PDF sources in text mode).
        extract_html: Strip boilerplate and keep the main content of HTML input.
        discard_links: Replace every hyperlink with its visible text.
        site_cleanup: Run site-specific cleanup (e.g. Wikipedia) during
            ``extract_html``; None follows ``html.site_cleanup`` in config.json.
        pdf_mode: ``"text"`` reads a PDF's text layer; ``"raster"`` renders
            every page to an image, for the image passes to read.

    Raises:
        ValueError: If ``template``, ``image_handling``, ``image_output`` or
            ``pdf_mode`` is unknown.
    """
    template: str = "plain"
    image_handling: str = "auto"
    image_output: str = "auto"
    code_parsing: bool = False
    extract_html: bool = False
    discard_links: bool = False
    site_cleanup: bool | None = None
    pdf_mode: str = "text"

    def __post_init__(self) -> None:
        check_choice("template", self.template, TEMPLATES)
        check_choice("image_handling", self.image_handling, IMAGE_HANDLING_CHOICES)
        check_choice("image_output", self.image_output, IMAGE_OUTPUT_CHOICES)
        check_choice("pdf_mode", self.pdf_mode, PDF_MODES)


@dataclass(frozen=True)
class ImagePlan:
    """What one conversion does with its images: the options with every ``auto`` resolved.

    Attributes:
        handling: One of ``formats.IMAGE_HANDLING_CHOICES``, never ``"auto"``.
        output: ``"embed"`` or ``"link"``; None for a format that holds no images.
        ai_required: An analysis cannot go without the AI models. False when
            it comes from ``"auto"`` on a document, which reads fine without it.
        page_source: The source is made of images: they are the document.
    """
    handling: str
    output: str | None
    ai_required: bool = True
    page_source: bool = False

    @property
    def analyzes(self) -> bool:
        """True when the AI models look at the images."""
        return self.handling not in ("discard", "keep")


def _is_page_source(options: ConvertOptions, from_format: str) -> bool:
    """True for a source that is made of images: the images are the document."""
    return from_format == "image" or (from_format == "pdf" and options.pdf_mode == "raster")


def _auto_handling(page_source: bool, to_format: str) -> str:
    """What ``image_handling="auto"`` means: a source made of pages is read, whatever the target."""
    if page_source or to_format == "latex":
        return "transcribe"
    return "discard" if to_format == "csv" else "keep"


def _image_output(options: ConvertOptions, to_format: str) -> str | None:
    """The way images are written to ``to_format``; a way it does not offer gives its default, with a warning."""
    supported = OUTPUT_FORMATS[to_format].image_outputs
    default = supported[0] if supported else None
    if options.image_output == "auto":
        return default
    if options.image_output not in supported:
        log_warning(f"Image output '{options.image_output}' is not available for {to_format}: "
                    f"{f'using {default}' if default else 'it holds no images'}.")
        return default
    return options.image_output


def resolve_images(options: ConvertOptions, from_format: str, to_format: str) -> ImagePlan:
    """Resolve the image options for a conversion, once, when both formats are known.

    Args:
        options: The conversion options.
        from_format: Source format.
        to_format: Output format.

    Returns:
        The plan every step of the conversion reads.

    Raises:
        ValueError: If ``discard`` is asked of a source made of images, which
            would leave nothing.
    """
    page_source = _is_page_source(options, from_format)
    if page_source and options.image_handling == "discard":
        raise ValueError("Cannot discard the images of a source made of images; "
                         "use image_handling 'replace' to keep their text only.")
    implicit = options.image_handling == "auto"
    handling = _auto_handling(page_source, to_format) if implicit else options.image_handling
    return ImagePlan(handling, _image_output(options, to_format), page_source or not implicit, page_source)
