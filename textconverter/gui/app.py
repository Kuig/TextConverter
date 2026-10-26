from __future__ import annotations
import dataclasses
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import textconverter.logger as logger
from textconverter.api import save_to_file
from textconverter.formats import (
    IMAGE_HANDLING_CHOICES, INPUT_FORMATS, OUTPUT_FORMATS, PDF_MODES, TEMPLATE_CHOICES,
)
from textconverter.options import ConvertOptions
from textconverter.config import DEFAULT_CONTEXT_SIZE, AppConfig, load_config
from textconverter.gui.file_dialog import ask_path

logger.set_backend("streamlit")

# The GUI runs as its own `streamlit run` process and never enters main(),
# so silence the third-party SDK loggers here too.
try:
    from unified_ai_client import list_models, list_providers, silence_sdks
    silence_sdks()
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

FORMAT_LABELS = {"markdown": "Markdown Files", "html": "HTML Files", "latex": "LaTeX Files",
                 "json": "JSON Files", "pdf": "PDF Files", "image": "Images"}


def _filetypes(formats: dict, all_label: str | None) -> list[tuple[str, str]]:
    """File dialog filters for the given formats, from the format registry."""
    patterns = {name: ";".join(f"*{ext}" for ext in f.extensions) for name, f in formats.items()}
    filters = [(FORMAT_LABELS[name], pattern) for name, pattern in patterns.items()]
    if all_label:
        filters.insert(0, (all_label, ";".join(patterns.values())))
    return [*filters, ("All Files", "*.*")]


INPUT_FILETYPES = _filetypes(INPUT_FORMATS, "All Supported Files")
OUTPUT_FILETYPES = _filetypes(OUTPUT_FORMATS, None)
# Session keys of the AI selection, each mirroring the AiConfig field of the same name.
MODEL_KEYS = ("classification_model", "description_model", "ocr_model")
NO_OCR_LABEL = "(none: description model transcribes)"
CONTEXT_SIZES = (4096, 8192, 16384, 32768, 65536, 131072, 262144)


@st.cache_data(show_spinner=False)
def _available_providers() -> list[str]:
    """Providers that can take images now: local servers that answer, cloud providers with a key."""
    return [p.name for p in list_providers() if "image" in p.file_types]


@st.cache_data(show_spinner=False)
def _available_models(provider: str) -> tuple[list[str], str]:
    """Image-capable model ids of a provider, and the error if they could not be listed.

    A model whose input types are unknown is kept.

    Returns:
        (model ids, '') on success, ([], error message) on failure.
    """
    try:
        models = list_models(provider)
    except Exception as exc:
        return [], str(exc) or type(exc).__name__
    return [m.id for m in models
            if not m.embeddings and (m.file_types is None or "image" in m.file_types)], ""


def _configured_context_size(provider: str) -> int:
    """The provider's ``context_size`` in config.json, or the default when it sets none."""
    return load_config().provider_settings(provider).get("context_size", DEFAULT_CONTEXT_SIZE)


def _init_state() -> None:
    """Fill the session state with the paths and the AI selection from config.json."""
    ai = load_config().ai
    defaults = {"source": "", "output": "", "provider": ai.provider,
                "context_size": _configured_context_size(ai.provider)}
    defaults.update({key: getattr(ai, key) for key in MODEL_KEYS})
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _on_provider_change() -> None:
    """Clear the model choices and load the new provider's context size."""
    st.session_state.update({key: "" for key in MODEL_KEYS})
    st.session_state.context_size = _configured_context_size(st.session_state.provider)


def _path_field(label: str, key: str, placeholder: str, filetypes: list, save: bool) -> str:
    """A text input bound to st.session_state[key], with a button opening a file dialog."""
    col_text, col_btn = st.columns([4, 1])
    with col_btn:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("💾" if save else "📁", key=f"{key}_btn", use_container_width=True,
                     help="Browse for output path" if save else "Browse for source file"):
            selected = ask_path(st.session_state[key], filetypes, save=save)
            if selected:
                st.session_state[key] = selected
    with col_text:
        return st.text_input(label, key=key, placeholder=placeholder)


def _provider_picker() -> str:
    """Provider selectbox; a saved provider that is unavailable stays selectable, with a warning."""
    options = _available_providers()
    current = st.session_state.provider
    if current not in options:
        options = [current, *options]
        st.caption(f"⚠️ '{current}' is not available now: server not running or no API key.")
    return st.selectbox("Provider", options, key="provider", on_change=_on_provider_change)


def _model_picker(label: str, key: str, provider: str, optional: bool = False) -> None:
    """Model selectbox bound to st.session_state[key].

    Falls back to a text input when the provider cannot list its models. A
    saved model that is not offered stays selectable, with a warning.

    Args:
        label: Widget label.
        key: Session state key, also the AiConfig field name.
        provider: Provider whose models are offered.
        optional: Offer "" (no model) as the first choice.
    """
    models, error = _available_models(provider)
    if not models:
        st.text_input(label, key=key)
        reason = error.rstrip(".") or "the provider offers none"
        st.caption(f"⚠️ Models of '{provider}' could not be listed ({reason}). Type the model name.")
        return
    current = st.session_state[key]
    # Ollama lists "name:latest" for a model configured as plain "name".
    if current and current not in models and f"{current}:latest" in models:
        current = st.session_state[key] = f"{current}:latest"
    options = ([""] if optional else []) + models
    if not current and not optional:
        st.session_state[key] = models[0]
    elif current not in options:
        options = [current, *options]
        st.caption(f"⚠️ '{current}' is not offered by '{provider}' now.")
    st.selectbox(label, options, key=key,
                 format_func=lambda m: NO_OCR_LABEL if m == "" else m)


def _context_size_picker() -> None:
    """Context size slider over CONTEXT_SIZES; a saved size off that scale is added, with a warning."""
    current = st.session_state.context_size
    options = CONTEXT_SIZES
    if current not in options:
        options = tuple(sorted({*options, current}))
        st.caption(f"⚠️ Context size {current} from config.json is not one of the standard sizes.")
    st.select_slider(
        "Context size", options, key="context_size",
        format_func=lambda size: f"{size // 1024}k" if size % 1024 == 0 else str(size),
        help="Tokens per call, shared by the image and the answer; raise it if long pages come out "
             "truncated. More context uses more memory. Ignored by providers without this setting.",
    )


def _selected_config() -> AppConfig:
    """config.json with the provider, models and context size chosen in the sidebar."""
    config = load_config()
    if AI_AVAILABLE:
        chosen = {key: st.session_state[key] for key in ("provider", *MODEL_KEYS)}
        config.ai = dataclasses.replace(config.ai, **chosen)
        block = config.providers.setdefault(config.ai.provider, {})
        block["context_size"] = st.session_state.context_size
    return config


st.set_page_config(page_title="TextConverter", page_icon="📝", layout="wide")
st.title("📝 TextConverter: Document Conversion")
st.caption("Convert between PDF, HTML, Markdown, LaTeX and JSON, and to PDF, with optional AI features.")
_init_state()

with st.sidebar:
    st.header("⚙️ Options")
    template = st.selectbox("Template", TEMPLATE_CHOICES,
                            help="HTML output only; PDF output always uses the light theme.")
    image_handling = st.selectbox("Image handling", IMAGE_HANDLING_CHOICES)
    pdf_mode = st.selectbox(
        "PDF input", PDF_MODES,
        format_func={"text": "Text layer", "raster": "Raster pages + AI transcription"}.get,
        help="Raster renders every page and transcribes it with the AI models below (for scans).",
    )
    code_parsing = st.checkbox("Enable code detection", help="Markdown sources, and PDF sources in text mode.")
    extract_html = st.checkbox("Clean HTML & extract main content")
    site_cleanup = st.checkbox("Site-specific cleanup (e.g. Wikipedia)", value=load_config().html.site_cleanup,
                               disabled=not extract_html)
    discard_links = st.checkbox("Discard links (keep text)")
    st.divider()

    st.header("🤖 AI models")
    if not AI_AVAILABLE:
        st.caption("AI features need the 'unified_ai_client' package (see requirements_prod.txt).")
    else:
        st.caption("Used by 'describe', image inputs, raster PDF input, and LaTeX/JSON output.")
        provider = _provider_picker()
        _model_picker("Classification model", "classification_model", provider)
        _model_picker("Description model", "description_model", provider)
        _model_picker("OCR model", "ocr_model", provider, optional=True)
        _context_size_picker()
        col_refresh, col_save = st.columns(2)
        with col_refresh:
            if st.button("🔄 Refresh", use_container_width=True, help="Reload providers and models"):
                _available_providers.clear()
                _available_models.clear()
                st.rerun()
        with col_save:
            if st.button("💾 Save as default", use_container_width=True,
                         help="Write these choices to config.json in the working directory"):
                try:
                    st.success(f"Saved to {_selected_config().save()}")
                except OSError as exc:
                    st.error(f"Save failed: {exc}")

col1, col2 = st.columns(2)
with col1:
    source = _path_field("Source file path or URL", "source",
                         "DocsInput/document.pdf or https://example.com", INPUT_FILETYPES, save=False)
with col2:
    output = _path_field("Output file path", "output",
                         "DocsOutput/document.md", OUTPUT_FILETYPES, save=True)

if st.button("Convert", type="primary", use_container_width=True):
    if not source or not output:
        st.error("Source and output paths are required.")
    else:
        with st.spinner("Converting..."):
            try:
                options = ConvertOptions(
                    template=template,
                    image_handling=image_handling,
                    code_parsing=code_parsing,
                    extract_html=extract_html,
                    discard_links=discard_links,
                    site_cleanup=site_cleanup,
                    pdf_mode=pdf_mode,
                )
                save_to_file(source, output, options, config=_selected_config())
                st.success(f"Saved to: `{output}`")
            except Exception as exc:
                st.error(f"Error: {exc}")
