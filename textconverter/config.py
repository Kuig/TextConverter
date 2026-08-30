from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from textconverter.logger import log_warning

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
    TextConverter, so it is dynamic/opaque data by design.
    """

    ai: AiConfig = field(default_factory=AiConfig)
    providers: dict[str, dict[str, Any]] = field(default_factory=lambda: dict(_DEFAULT_PROVIDERS))

    @classmethod
    def load(cls, path: str | Path | None = None) -> "AppConfig":
        """Load configuration from JSON, falling back to defaults for missing keys.

        Args:
            path: Explicit config.json path. When omitted, the current working
                directory is tried first, then the package root.

        Returns:
            An AppConfig populated from the file, or an all-default instance
            when no readable config.json exists.
        """
        raw = _load_raw_dict(path)
        if not raw:
            return cls()

        ai_config = _ai_config_from_dict(raw.get("ai"))
        providers = {
            k: v for k, v in raw.items()
            if k != "ai" and isinstance(v, dict)
        }
        return cls(ai=ai_config, providers=providers or dict(_DEFAULT_PROVIDERS))


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_raw_dict(path: str | Path | None = None) -> dict:
    """Load the raw JSON configuration, prioritizing CWD, falling back to package root.

    Args:
        path: Explicit config.json path. When omitted, the current working
            directory is tried first, then the package root.

    Returns:
        The parsed config.json content as a dict, or an empty dict if no file
        was found (callers fall back to dataclass defaults). A file that exists
        but cannot be read or parsed is reported via ``log_warning`` and skipped.
    """
    if path is not None:
        candidates = [Path(path)]
    else:
        candidates = [
            Path.cwd() / "config.json",                     # 1. current working directory
            Path(__file__).parent.parent / "config.json",   # 2. package root
        ]

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            with open(candidate, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            log_warning(f"Ignoring unreadable config file {candidate}: {exc}")

    # 3. Fallback to hardcoded defaults
    return {}


def _ai_config_from_dict(data: Any) -> AiConfig:
    """Build an AiConfig from the raw ``"ai"`` section of config.json.

    Tolerant but noisy: unknown keys are dropped with a ``log_warning`` instead
    of being silently ignored. A missing or malformed section falls back to
    defaults.

    Args:
        data: The raw ``"ai"`` value from the parsed config.json.

    Returns:
        A populated AiConfig instance.
    """
    if not isinstance(data, dict):
        return AiConfig()
    fields = AiConfig.__dataclass_fields__
    filtered = {k: v for k, v in data.items() if k in fields}
    unknown = sorted(set(data) - set(filtered))
    if unknown:
        log_warning(f"Ignoring unknown keys in config 'ai' section: {', '.join(unknown)}")
    return AiConfig(**filtered)


def load_config() -> AppConfig:
    """Load configuration prioritizing CWD, falling back to package root.

    Thin wrapper around :meth:`AppConfig.load`.

    Returns:
        An AppConfig instance. Falls back to dataclass defaults for any
        missing file, section, or field.
    """
    return AppConfig.load()


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
