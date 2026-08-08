from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Hardcoded defaults — used only when no config.json is found.
# ---------------------------------------------------------------------------

_DEFAULT_CLASSIFICATION_PROMPT = (
    "Analyze the image and classify it into exactly one of the following categories: "
    "'photo_drawing_or_comic', 'diagram', 'short_text_table_or_formula', 'chart', "
    "'infographic_or_depliant', 'document_scan', 'logo_or_icon', 'map'. "
    "Reply ONLY with a valid JSON object containing a single key 'category' and the "
    "chosen category as the value. Do not include markdown blocks."
)

_DEFAULT_PROMPTS: dict[str, str] = {
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
}

_DEFAULT_PROVIDERS: dict[str, dict[str, Any]] = {
    "ollama": {
        "url": "http://localhost:11434",
        "timeout": 300,
        "keep_alive": "15m",
        "context_size": 8192,
    },
}


@dataclass
class AiConfig:
    """TextConverter application-level AI settings (provider-agnostic)."""

    provider: str = "ollama"
    classification_model: str = "gemma4:12b"
    description_model: str = "gemma4:12b"
    classification_visual_token_budget: int = 70
    description_visual_token_budget: int = 1120
    provide_extracted_text_to_describer: bool = False
    classification_prompt: str = _DEFAULT_CLASSIFICATION_PROMPT
    prompts: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_PROMPTS))


@dataclass
class AppConfig:
    """Root application configuration loaded from config.json.

    ``providers`` intentionally stays a raw dict: its schema is provider-specific
    (Ollama, Google, OpenAI, ...) and is owned by ``unified_ai_client``, not by
    TextConverter, so it is dynamic/opaque data by design (see CONVENTIONS.md §5.1).
    """

    ai: AiConfig = field(default_factory=AiConfig)
    providers: dict[str, dict[str, Any]] = field(default_factory=lambda: dict(_DEFAULT_PROVIDERS))


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_raw_dict() -> dict:
    """Load the raw JSON configuration, prioritizing CWD, falling back to package root.

    Returns:
        The parsed config.json content as a dict, or an empty dict if no file
        was found or parsing failed (callers fall back to dataclass defaults).
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
    return {}


def _ai_config_from_dict(data: Any) -> AiConfig:
    """Build an AiConfig from the raw ``"ai"`` section of config.json.

    Unknown keys are silently ignored (fail-soft, mirrors the previous dict
    behavior). A missing or malformed section falls back to defaults.

    Args:
        data: The raw ``"ai"`` value from the parsed config.json.

    Returns:
        A populated AiConfig instance.
    """
    if not isinstance(data, dict):
        return AiConfig()
    fields = AiConfig.__dataclass_fields__
    filtered = {k: v for k, v in data.items() if k in fields}
    return AiConfig(**filtered)


def load_config() -> AppConfig:
    """Load configuration prioritizing CWD, falling back to package root.

    Returns:
        An AppConfig instance. Falls back to dataclass defaults for any
        missing file, section, or field.
    """
    raw = _load_raw_dict()
    if not raw:
        return AppConfig()

    ai_config = _ai_config_from_dict(raw.get("ai"))
    providers = {
        k: v for k, v in raw.items()
        if k != "ai" and isinstance(v, dict)
    }
    return AppConfig(ai=ai_config, providers=providers or dict(_DEFAULT_PROVIDERS))


def get_ai_config(cfg: AppConfig) -> AiConfig:
    """Extract the app-level AI config section from a loaded AppConfig.

    Args:
        cfg: An AppConfig instance as returned by ``load_config()``.

    Returns:
        The ``ai`` sub-dataclass, containing provider name, model names,
        prompts, and token budgets.
    """
    return cfg.ai


def configure_provider_from_config(cfg: AppConfig) -> None:
    """Call ``unified_ai_client.configure_provider()`` for the active provider.

    Reads the provider name from ``cfg.ai.provider`` (default ``"ollama"``),
    then passes the matching provider section (e.g. ``cfg.providers["ollama"]``)
    as keyword arguments to ``configure_provider()``.

    This is a no-op if ``unified_ai_client`` is not installed.

    Args:
        cfg: An AppConfig instance as returned by ``load_config()``.
    """
    try:
        from unified_ai_client import configure_provider
    except ImportError:
        return

    provider_name = cfg.ai.provider
    provider_settings = cfg.providers.get(provider_name, {})

    if provider_settings:
        configure_provider(provider_name, **provider_settings)
