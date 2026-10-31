from __future__ import annotations

from dataclasses import dataclass

from .formats import IMAGE_HANDLING_MODES, PDF_MODES, TEMPLATES, check_choice


@dataclass
class ConvertOptions:
    """How a document is converted; shared by every conversion entry point.

    Values are validated on creation, so a misspelled option fails before any
    download or AI call.

    Attributes:
        template: HTML template (see ``formats.TEMPLATES``); used for HTML output.
        image_handling: One of ``formats.IMAGE_HANDLING_MODES``. ``"auto"``
            picks the output format's default (see the README's Image Handling).
        code_parsing: Fence code blocks found by the heuristic detector
            (Markdown, Word and PowerPoint sources, and PDF sources in text mode).
        extract_html: Strip boilerplate and keep the main content of HTML input.
        discard_links: Replace every hyperlink with its visible text.
        site_cleanup: Run site-specific cleanup (e.g. Wikipedia) during
            ``extract_html``; None follows ``html.site_cleanup`` in config.json.
        pdf_mode: ``"text"`` reads a PDF's text layer; ``"raster"`` renders
            every page and transcribes it with the AI describer.

    Raises:
        ValueError: If ``template``, ``image_handling`` or ``pdf_mode`` is unknown.
    """
    template: str = "plain"
    image_handling: str = "auto"
    code_parsing: bool = False
    extract_html: bool = False
    discard_links: bool = False
    site_cleanup: bool | None = None
    pdf_mode: str = "text"

    def __post_init__(self) -> None:
        check_choice("template", self.template, TEMPLATES)
        check_choice("image_handling", self.image_handling, IMAGE_HANDLING_MODES)
        check_choice("pdf_mode", self.pdf_mode, PDF_MODES)
