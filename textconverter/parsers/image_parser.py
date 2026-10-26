from __future__ import annotations
import os
from ..ast import Document
from ..config import AppConfig
from ..logger import log_action


def parse_image(source: str, config: AppConfig | None = None) -> Document:
    """Parse an image file into a Document through the AI describer.

    The image is classified, then described or transcribed, and the answer is
    parsed into AST nodes. If that fails, the Document holds a plain reference
    to the image.

    Args:
        source: Image file path.
        config: Application configuration; loaded from config.json when omitted.

    Raises:
        ValueError: If the file does not exist.
        ImportError: If ``unified_ai_client`` is not installed.
    """
    from ..image_describer import transcribe_images
    if not os.path.exists(source):
        raise ValueError(f"Image file not found: {source}")
    log_action(f"Generating description for image {source}...")
    return transcribe_images([source], config)
