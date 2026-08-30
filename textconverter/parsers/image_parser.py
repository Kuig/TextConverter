from __future__ import annotations
import os
from ..ast import Document
from ..logger import log_action, log_warning
from .markdown_parser import parse_markdown

def parse_image(source: str) -> Document:
    """Parses an image file by generating a markdown description via Ollama and then parsing that markdown."""
    from ..image_describer import _call_ai, init_ai
    if not os.path.exists(source):
        raise ValueError(f"Image file not found: {source}")

    from ..config import load_config
    config = load_config()
    init_ai(config)

    # We pass an empty base_dir since we provide the absolute/relative path directly in source
    base_dir = ""
    log_action(f"Generating description for image {source}...")
    markdown_desc, category = _call_ai(source, base_dir, config)

    if not markdown_desc:
        # Description failed or was skipped; keep a plain image reference so the
        # pipeline still has content to render.
        from ..ast import Paragraph, Image
        log_warning(f"No description generated for image {source}; keeping image reference.")
        doc = Document()
        doc.children.append(Paragraph(children=[Image(src=source, alt=os.path.basename(source))]))
        return doc

    return parse_markdown(markdown_desc)
