from __future__ import annotations
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Hardcoded defaults — used only when no config.json is found.
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict = {
    "ai": {
        "provider": "ollama",
        "classification_model": "gemma4:12b",
        "description_model": "gemma4:12b",
        "classification_visual_token_budget": 70,
        "description_visual_token_budget": 1120,
        "provide_extracted_text_to_describer": False,
        "classification_prompt": (
            "Analyze the image and classify it into exactly one of the following categories: "
            "'photo_drawing_or_comic', 'diagram', 'short_text_table_or_formula', 'chart', "
            "'infographic_or_depliant', 'document_scan', 'logo_or_icon', 'map'. "
            "Reply ONLY with a valid JSON object containing a single key 'category' and the "
            "chosen category as the value. Do not include markdown blocks."
        ),
        "prompts": {
            "photo_drawing_or_comic": "Accurate description of scene and subjects.",
            "diagram": "Detailed description of the diagram.",
            "short_text_table_or_formula": (
                "Transcription only, strictly preserving the original layout and formatting "
                "(e.g. use markdown tables and latex math for formulas)."
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
    },
    "ollama": {
        "url": "http://localhost:11434",
        "timeout": 300,
        "keep_alive": "15m",
        "context_size": 8192,
    },
}


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load configuration prioritizing CWD, falling back to package root.

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


def get_ai_config(cfg: dict) -> dict:
    """Extract the app-level AI config section from a loaded config dict.

    Returns the ``"ai"`` section, which contains TextConverter-specific
    settings: provider name, model names, prompts, token budgets, etc.

    Args:
        cfg: A config dict as returned by ``load_config()``.

    Returns:
        The ``"ai"`` sub-dict, or an empty dict if the section is missing.
    """
    return cfg.get("ai", {})


def configure_provider_from_config(cfg: dict) -> None:
    """Call ``unified_ai_client.configure_provider()`` for the active provider.

    Reads the provider name from ``cfg["ai"]["provider"]`` (default ``"ollama"``),
    then passes the matching provider section (e.g. ``cfg["ollama"]``) as keyword
    arguments to ``configure_provider()``.

    This is a no-op if ``unified_ai_client`` is not installed.

    Args:
        cfg: A config dict as returned by ``load_config()``.
    """
    try:
        from unified_ai_client import configure_provider
    except ImportError:
        return

    ai_cfg = get_ai_config(cfg)
    provider_name = ai_cfg.get("provider", "ollama")
    provider_settings = cfg.get(provider_name, {})

    if provider_settings:
        configure_provider(provider_name, **provider_settings)
