from __future__ import annotations
import os
from ..ast import Document, Image, walk
from ..config import AppConfig
from ..images import ImageStore
from ..logger import log_action


def parse_image(
    file_path: str,
    *,
    config: AppConfig,
    output_dir: str | None = None,
    image_dir_name: str | None = None,
    write_images: bool = True,
    overlay_path: str | None = None,
) -> Document:
    """Parse an image file into a Document through the AI describer.

    The image is classified, then described or transcribed, and the answer is
    parsed into AST nodes. A page holding more than text is split into regions.
    If that fails, the Document holds a plain reference to the image.

    Image paths in the Document are relative to ``output_dir``, like those of
    the other binary parsers.

    Args:
        file_path: Image file path.
        config: Application configuration.
        output_dir: Base directory for the kept crops (current directory if None).
        image_dir_name: Image subdirectory name inside ``output_dir``.
        write_images: Keep the crops of the regions that are not transcribed.
        overlay_path: Where to save the image with what was found in it.

    Raises:
        FileNotFoundError: If the file does not exist.
        ImportError: If ``unified_ai_client`` is not installed.
    """
    from ..image_describer import transcribe_images
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Image file not found: {file_path}")
    log_action(f"Generating description for image {file_path}...")
    save_crop = ImageStore(output_dir, image_dir_name).save_png if write_images else None
    doc = transcribe_images([file_path], config=config, save_crop=save_crop, overlay_path=overlay_path)
    if not os.path.isabs(file_path):
        for node in walk(doc):
            if isinstance(node, Image) and node.src == file_path:
                node.src = _relative(file_path, output_dir or os.getcwd())
    return doc


def _relative(path: str, base_dir: str) -> str:
    """``path`` relative to ``base_dir``, or absolute when it is on another drive."""
    try:
        return os.path.relpath(path, base_dir)
    except ValueError:
        return os.path.abspath(path)
