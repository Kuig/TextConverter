from __future__ import annotations
import os
import json
from textconverter.logger import log_action, log_info, log_success, log_warning
from .ast import Image

from .config import load_config, get_ai_config, configure_provider_from_config


def _call_ai(
    src: str,
    base_dir: str,
    config: dict,
    latex_auto: bool = False,
    extracted_text: str | None = None,
) -> tuple[str | None, str]:
    """Classify and describe an image using the configured AI provider via UnifiedAiClient.

    Makes two sequential calls: first a JSON-mode classification to determine
    the image category, then a free-form description call with a category-specific
    prompt. UnifiedAiClient handles base64 encoding of the image internally.

    The provider and its connection settings are read from the config and applied
    via ``configure_provider_from_config()`` before any call is made.

    Args:
        src: Image path (relative or absolute).
        base_dir: Base directory for resolving relative paths.
        config: Loaded configuration dictionary.
        latex_auto: If True, skip description for non-formula images.
        extracted_text: Optional pre-extracted text from the image.

    Returns:
        Tuple of (description_text, category). Description is None if skipped.
    """
    category = "default"
    img_path = src if os.path.isabs(src) else os.path.join(base_dir, src)

    if not os.path.exists(img_path):
        return f"[Error: Image file not found at {img_path}]", "error"

    ai_cfg = get_ai_config(config)
    provider = ai_cfg.get("provider", "ollama")
    provider_settings = config.get(provider, {})
    provider_timeout = provider_settings.get("timeout", 300)
    c_model = ai_cfg.get("classification_model", "gemma4:12b")
    d_model = ai_cfg.get("description_model", "gemma4:12b")
    classification_prompt = ai_cfg.get(
        "classification_prompt",
        'Classify the image. Reply with JSON {"category": "default"}',
    )
    c_budget = ai_cfg.get("classification_visual_token_budget", 0)
    d_budget = ai_cfg.get("description_visual_token_budget", 0)

    try:
        try:
            from unified_ai_client import call_ai, preload_model
        except ImportError:
            raise ImportError(
                "The 'unified_ai_client' package is required for AI-based image description. "
                "Please install it first (e.g. via requirements_prod.txt)."
            )

        # Apply provider connection settings (url, timeout, keep_alive, context_size, …)
        # before any call so that UnifiedAiClient uses the correct configuration.
        configure_provider_from_config(config)

        # Pre-load models to ensure the provider is initialised with the correct context.
        preload_model(provider=provider, model=c_model, extra_options={"use_generate": False})
        if d_model != c_model:
            preload_model(provider=provider, model=d_model, extra_options={"use_generate": False})

        # 1. Classification — JSON mode, UnifiedAiClient handles base64 encoding
        c_opts: dict = {"use_generate": False}
        if c_budget > 0:
            c_opts["visual_token_budget"] = c_budget

        class_response = call_ai(
            provider=provider,
            model=c_model,
            prompt=classification_prompt,
            file_path=img_path,
            format_json=True,
            timeout=provider_timeout,
            extra_options=c_opts,
        )
        try:
            category_data = json.loads(class_response.text)
            category = category_data.get("category", "default")
        except Exception:
            category = "default"

        # 2. Description
        prompts = ai_cfg.get("prompts", {})
        if category not in prompts:
            category = "default"

        final_prompt = prompts.get(category, "Describe the image in detail.")
        if extracted_text and ai_cfg.get("provide_extracted_text_to_describer", False):
            final_prompt += (
                f"\n\nThis image was originally vector-based and contained the following "
                f"extracted text:\n{extracted_text}"
            )

        log_action(f"Classified as: {category}")

        if latex_auto and category != "short_text_table_or_formula":
            log_action("(LaTeX Auto mode: skipping description for non-table/formula image)")
            return None, category

        d_opts: dict = {"use_generate": False}
        if d_budget > 0:
            d_opts["visual_token_budget"] = d_budget

        desc_response = call_ai(
            provider=provider,
            model=d_model,
            prompt=final_prompt,
            file_path=img_path,
            timeout=provider_timeout,
            extra_options=d_opts,
        )
        return desc_response.text.strip(), category

    except ImportError as exc:
        raise exc
    except Exception as exc:
        log_warning(f"Classification failed, using default: {exc}")
        return f"[Error generating description: {exc}]", category


def _count_images(node) -> int:
    """Recursively count Image nodes in the document AST.

    Args:
        node: Any AST node.

    Returns:
        Total number of Image nodes found.
    """
    count = 0
    if isinstance(node, Image):
        count += 1
    if hasattr(node, "children"):
        for c in node.children:
            count += _count_images(c)
    if hasattr(node, "content") and isinstance(node.content, list):
        for c in node.content:
            count += _count_images(c)
    if hasattr(node, "items"):
        for c in node.items:
            count += _count_images(c)
    if hasattr(node, "rows"):
        for c in node.rows:
            count += _count_images(c)
    if hasattr(node, "cells"):
        for c in node.cells:
            count += _count_images(c)
    if hasattr(node, "headers") and getattr(node, "headers", None):
        for c in node.headers:
            count += _count_images(c)
    return count


def _traverse(node, base_dir: str, config: dict, state: dict, latex_auto: bool = False) -> None:
    """Recursively walk an AST node and process Image children in-place.

    Args:
        node: Any AST node.
        base_dir: Base directory for resolving image paths.
        config: Loaded configuration dictionary.
        state: Mutable dict with 'total' and 'current' counters.
        latex_auto: Whether to skip non-formula images in LaTeX mode.
    """
    if hasattr(node, "children"):
        node.children = _process_list(node.children, base_dir, config, state, latex_auto)
    if hasattr(node, "content") and isinstance(node.content, list):
        node.content = _process_list(node.content, base_dir, config, state, latex_auto)
    if hasattr(node, "items"):
        for item in node.items:
            _traverse(item, base_dir, config, state, latex_auto)
    if hasattr(node, "rows"):
        for row in node.rows:
            _traverse(row, base_dir, config, state, latex_auto)
    if hasattr(node, "cells"):
        for cell in node.cells:
            _traverse(cell, base_dir, config, state, latex_auto)
    if hasattr(node, "headers") and node.headers:
        for header in node.headers:
            _traverse(header, base_dir, config, state, latex_auto)


def _process_list(node_list: list, base_dir: str, config: dict, state: dict, latex_auto: bool = False) -> list:
    """Process a list of AST nodes, replacing Image nodes with descriptions.

    Args:
        node_list: List of AST nodes.
        base_dir: Base directory for resolving image paths.
        config: Loaded configuration dictionary.
        state: Mutable dict with 'total' and 'current' counters.
        latex_auto: Whether to skip non-formula images in LaTeX mode.

    Returns:
        The modified node list.
    """
    for child in node_list:
        if isinstance(child, Image):
            state["current"] += 1
            log_action(f"[{state['current']}/{state['total']}] Requesting description for: {child.src}")
            desc, category = _call_ai(
                child.src, base_dir, config, latex_auto,
                extracted_text=getattr(child, "extracted_text", None),
            )
            child.category = category
            if desc:
                child.description = desc
            if latex_auto and category == "short_text_table_or_formula":
                child.render_metadata = False
        elif (
            hasattr(child, "children")
            or hasattr(child, "content")
            or hasattr(child, "items")
            or hasattr(child, "rows")
            or hasattr(child, "cells")
            or hasattr(child, "headers")
        ):
            _traverse(child, base_dir, config, state, latex_auto)
    return node_list


def process_images(doc, base_dir: str, latex_auto: bool = False) -> None:
    """Classify and describe all Image nodes in a document AST using Ollama.

    Loads configuration from the project-root config.json, traverses the full
    document AST, and populates each Image node's .description and .category
    fields in-place.

    Args:
        doc: Root AST document node.
        base_dir: Base directory for resolving relative image paths.
        latex_auto: If True, skip description for non-table/formula images.
    """
    config = load_config()
    total_images = _count_images(doc)
    state = {"total": total_images, "current": 0}

    if total_images > 0:
        ai_cfg = get_ai_config(config)
        provider = ai_cfg.get("provider", "ollama")
        c_model = ai_cfg.get("classification_model", "unknown")
        d_model = ai_cfg.get("description_model", "unknown")
        log_info(f"Starting description of {total_images} images via {provider} (Class: {c_model}, Desc: {d_model})...")

    _traverse(doc, base_dir, config, state, latex_auto)

    if total_images > 0:
        log_success("Image description completed.")
