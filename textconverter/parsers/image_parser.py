from __future__ import annotations
import os
from ..ast import Document
from ..config import AppConfig
from ..logger import log_action


def parse_image(file_path: str, *, config: AppConfig) -> Document:
    """Parse an image file into a Document through the AI describer.

    The image is classified, then described or transcribed, and the answer is
    parsed into AST nodes. If that fails, the Document holds a plain reference
    to the image.

    Args:
        file_path: Image file path.
        config: Application configuration.

    Raises:
        FileNotFoundError: If the file does not exist.
        ImportError: If ``unified_ai_client`` is not installed.
    """
    from ..image_describer import transcribe_images
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Image file not found: {file_path}")
    log_action(f"Generating description for image {file_path}...")
    return transcribe_images([file_path], config=config)
