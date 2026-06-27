from __future__ import annotations
import json
from pathlib import Path

DEFAULT_CONFIG = {
    "ollama": {
        "url": "http://localhost:11434",
        "classification_model": "gemma4:e2b",
        "description_model": "gemma4:e2b",
        "classification_prompt": (
            "Analyze the image and classify it into exactly one of the following categories: "
            "'photo_drawing_or_comic', 'diagram', 'short_text_table_or_formula', 'chart', "
            "'infographic_or_depliant', 'document_scan', 'logo_or_icon', 'map'. "
            "Reply ONLY with a valid JSON object containing a single key 'category' and the "
            "chosen category as the value."
        ),
        "prompts": {
            "photo_drawing_or_comic": "Accurate description of scene and subjects.",
            "diagram": "Detailed description of the diagram.",
            "short_text_table_or_formula": (
                "Transcription only, strictly preserving the original layout and formatting "
                "(e.g. use markdown tables)."
            ),
            "chart": (
                "Extract key trends. Create a data table ONLY if exact numerical values are "
                "clearly readable; do NOT guess or hallucinate numbers."
            ),
            "infographic_or_depliant": (
                "Extract all the text and describe the layout and visual flow of the information."
            ),
            "document_scan": (
                "Transcribe all the text exactly as it appears in the scan, preserving the "
                "structure and formatting as much as possible."
            ),
            "logo_or_icon": "Briefly describe the logo, symbol, or icon without overcomplicating it.",
            "map": (
                "Describe the map, its geographic or thematic focus, and any key legends or "
                "paths shown."
            ),
            "default": "Describe the image in detail.",
        },
    }
}

def load_config() -> dict:
    """Load Ollama configuration prioritizing CWD, falling back to package root.

    Returns:
        Configuration dict. Falls back to DEFAULT_CONFIG if no file is found.
    """
    # 1. Prioritize Current Working Directory
    cwd_config = Path.cwd() / "config.json"
    if cwd_config.exists():
        try:
            with open(cwd_config, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # 2. Fallback to Package Root
    package_root = Path(__file__).parent.parent
    package_config = package_root / "config.json"
    if package_config.exists():
        try:
            with open(package_config, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # 3. Fallback to hardcoded defaults
    return DEFAULT_CONFIG
