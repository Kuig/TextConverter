from __future__ import annotations
import copy
import json
from dataclasses import MISSING, asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from textconverter.logger import log_warning

# ---------------------------------------------------------------------------
# Hardcoded defaults, used only when no config.json is found.
# ---------------------------------------------------------------------------

_DEFAULT_CLASSIFICATION_PROMPT = (
    "Analyze the image and classify it into exactly one of the following categories: "
    "'photo_drawing_or_comic', 'diagram', 'text' (mostly a short passage of text), "
    "'table' (mostly a table), 'formula' (mostly a mathematical formula or equation), "
    "'chart', 'infographic_or_depliant', 'document_scan' (a whole scanned or photographed "
    "page), 'logo_or_icon', 'map'. "
    "Reply ONLY with a valid JSON object containing a single key 'category' and the "
    "chosen category as the value. Do not include markdown blocks."
)

_DEFAULT_PROMPTS: dict[str, str] = {
    "photo_drawing_or_comic": "Accurate description of scene and subjects.",
    "diagram": "Detailed description of the diagram.",
    "text": (
        "Transcription only, strictly preserving the original layout and formatting "
        "(use markdown)."
    ),
    "table": "Transcription only: reproduce the table as a markdown table, keeping every row and column.",
    "formula": "Transcription only: write the formula in LaTeX between $$ delimiters, nothing else.",
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

# Task prompts of GLM-OCR, keyed by the categories routed to the OCR phase.
_DEFAULT_OCR_PROMPTS: dict[str, str] = {
    "text": "Text Recognition:",
    "table": "Table Recognition:",
    "formula": "Formula Recognition:",
    "document_scan": "Text Recognition:",
}

# Images and answer share the window: an A3 page at 200 DPI alone takes about 4k tokens.
DEFAULT_CONTEXT_SIZE = 8192

_DEFAULT_PROVIDERS: dict[str, dict[str, Any]] = {
    "ollama": {
        "url": "http://localhost:11434",
        "timeout": 300,
        "keep_alive": "15m",
        "context_size": DEFAULT_CONTEXT_SIZE,
    },
}


@dataclass
class AiConfig:
    """TextConverter application-level AI settings (provider-agnostic).

    Images whose category is a key of ``ocr_prompts`` are transcribed rather
    than described: by ``ocr_model`` with the matching OCR prompt when it is
    set, otherwise by ``description_model`` with the category's entry in
    ``prompts``. A temperature of ``None`` leaves the model default in place.
    """

    provider: str = "ollama"
    classification_model: str = "gemma4:e2b"
    description_model: str = "gemma4:e2b"
    classification_visual_token_budget: int = 70
    description_visual_token_budget: int = 1120
    provide_extracted_text_to_describer: bool = False
    classification_prompt: str = _DEFAULT_CLASSIFICATION_PROMPT
    prompts: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_PROMPTS))
    ocr_model: str = ""
    ocr_prompts: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_OCR_PROMPTS))
    classification_temperature: float | None = 0.0
    ocr_temperature: float | None = 0.0


@dataclass
class WikipediaCleanupConfig:
    """Settings for the Wikipedia HTML cleanup profile.

    Attributes:
        drop_sections: End-matter section titles to remove (heading plus its
            block). An entry that matches an English canonical name
            (``see also``, ``external links``, ``further reading``) also removes
            that section's known translations; any other entry is matched
            literally, so non-English wikis can list their own titles here.
        drop_citation_marks: Remove inline ``[n]`` citation superscripts.
        keep_reference_list: Keep the full citation list at the end of the
            article; set False to strip it too.
        extra_strip_selectors: Additional MediaWiki class names or element ids
            to remove, on top of the built-in list.
    """

    drop_sections: list[str] = field(
        default_factory=lambda: ["see also", "external links", "further reading"]
    )
    drop_citation_marks: bool = True
    keep_reference_list: bool = True
    extra_strip_selectors: list[str] = field(default_factory=list)


@dataclass
class HtmlConfig:
    """HTML input handling settings.

    Attributes:
        site_cleanup: Default for whether site-specific cleanup profiles run
            during ``--extract-html``. A per-run flag can still override it.
        wikipedia: Settings for the Wikipedia cleanup profile.
    """

    site_cleanup: bool = True
    wikipedia: WikipediaCleanupConfig = field(default_factory=WikipediaCleanupConfig)


@dataclass
class AppConfig:
    """Root application configuration loaded from config.json.

    ``providers`` intentionally stays a raw dict: its schema is provider-specific
    (Ollama, Google, OpenAI, ...) and is owned by ``unified_ai_client``, not by
    TextConverter, so it is dynamic/opaque data by design.
    """

    ai: AiConfig = field(default_factory=AiConfig)
    html: HtmlConfig = field(default_factory=HtmlConfig)
    providers: dict[str, dict[str, Any]] = field(default_factory=lambda: copy.deepcopy(_DEFAULT_PROVIDERS))

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

        ai_config = _dataclass_from_dict(AiConfig, raw.get("ai"), "ai")
        html_config = _dataclass_from_dict(HtmlConfig, raw.get("html"), "html")
        providers = {
            k: v for k, v in raw.items()
            if k not in ("ai", "html") and isinstance(v, dict)
        }
        return cls(ai=ai_config, html=html_config, providers=providers or copy.deepcopy(_DEFAULT_PROVIDERS))

    def provider_settings(self, name: str | None = None) -> dict[str, Any]:
        """Return the settings block of a provider (the active one by default).

        Args:
            name: Provider name; ``ai.provider`` when None.

        Returns:
            The provider's raw settings, or an empty dict when it has none.
            The dict is the live block: changes to it change this config.
        """
        return self.providers.get(name or self.ai.provider, {})

    def save(self, path: str | Path | None = None) -> Path:
        """Write this configuration as JSON, in the layout ``load()`` reads.

        Unlike ``load()``, which falls back to the package root, saving always
        targets the working directory: a saved configuration belongs to the
        workspace, never inside an installed package.

        Args:
            path: Destination file. Defaults to ``./config.json``.

        Returns:
            The path written.
        """
        target = Path(path) if path is not None else Path.cwd() / "config.json"
        data = {"ai": asdict(self.ai), "html": asdict(self.html), **self.providers}
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return target


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


def _dataclass_from_dict(cls: type, data: Any, section: str) -> Any:
    """Build the config dataclass ``cls`` from its raw section of config.json.

    Tolerant but noisy: unknown keys are dropped with a ``log_warning``, a
    missing section falls back to defaults, and a section that is not a JSON
    object is reported and replaced by defaults. A field whose default is a
    nested config dataclass is built from its sub-section the same way.

    Args:
        cls: The config dataclass to build.
        data: The raw section value from the parsed config.json.
        section: The section's dotted name, for messages (e.g. ``"html.wikipedia"``).

    Returns:
        A populated ``cls`` instance.
    """
    if data is None:
        return cls()
    if not isinstance(data, dict):
        log_warning(f"Ignoring config '{section}' section: expected an object, got {type(data).__name__}")
        return cls()
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        if f.default_factory is not MISSING and is_dataclass(f.default_factory):
            kwargs[f.name] = _dataclass_from_dict(f.default_factory, data[f.name], f"{section}.{f.name}")
        else:
            kwargs[f.name] = data[f.name]
    unknown = sorted(set(data) - set(kwargs))
    if unknown:
        log_warning(f"Ignoring unknown keys in config '{section}' section: {', '.join(unknown)}")
    return cls(**kwargs)


def load_config() -> AppConfig:
    """Load configuration prioritizing CWD, falling back to package root.

    Thin wrapper around :meth:`AppConfig.load`.

    Returns:
        An AppConfig instance. Falls back to dataclass defaults for any
        missing file, section, or field.
    """
    return AppConfig.load()
