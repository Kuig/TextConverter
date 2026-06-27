from __future__ import annotations
import os
import json
from pathlib import Path
from textconverter.logger import log_action, log_info, log_success, log_warning
from .ast import Image

from .config import load_config


def _call_ollama(
    src: str,
    base_dir: str,
    config: dict,
    latex_auto: bool = False,
    extracted_text: str | None = None,
) -> tuple[str | None, str]:
    """Classify and describe an image using Ollama via UnifiedAiClient.

    Makes two sequential calls: first a JSON-mode classification to determine
    the image category, then a free-form description call with a category-specific
    prompt. UnifiedAiClient handles base64 encoding of the image internally.

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

    ollama_cfg = config.get("ollama", {})
    c_model = ollama_cfg.get("classification_model", ollama_cfg.get("model", "gemma4:e2b"))
    d_model = ollama_cfg.get("description_model", ollama_cfg.get("model", "gemma4:e2b"))
    classification_prompt = ollama_cfg.get(
        "classification_prompt",
        'Classify the image. Reply with JSON {"category": "default"}',
    )

    try:
        c_budget = ollama_cfg.get("classification_visual_token_budget", 0)
        d_budget = ollama_cfg.get("description_visual_token_budget", 0)
        context_size = ollama_cfg.get("context_size", 8192)  # Default high for images

        try:
            from unified_ai_client import call_ai, preload_model
        except ImportError:
            raise ImportError(
                "The 'unified_ai_client' package is required for AI-based image description. "
                "Please install it first (e.g. via requirements_prod.txt)."
            )

        # Lazy pre-load to ensure correct context_size allocation for images.
        # We don't pass visual_token_budget here because we want to pass it explicitly
        # per-call, since classification and description might use different budgets
        # but share the same 'ollama' provider config state.
        preload_model(provider="ollama", model=c_model, context_size=context_size, extra_options={"use_generate": False})
        if d_model != c_model:
            preload_model(provider="ollama", model=d_model, context_size=context_size, extra_options={"use_generate": False})

        # 1. Classification — JSON mode, UnifiedAiClient handles base64 encoding
        c_opts = {"use_generate": False}
        if c_budget > 0:
            c_opts["visual_token_budget"] = c_budget

        class_response = call_ai(
            provider="ollama",
            model=c_model,
            prompt=classification_prompt,
            file_path=img_path,
            format_json=True,
            timeout=30,
            extra_options=c_opts,
        )
        try:
            category_data = json.loads(class_response.text)
            category = category_data.get("category", "default")
        except Exception:
            category = "default"

        # 2. Description
        prompts = ollama_cfg.get("prompts", {})
        if category not in prompts:
            category = "default"

        final_prompt = prompts.get(category, "Describe the image in detail.")
        if extracted_text and ollama_cfg.get("provide_extracted_text_to_describer", False):
            final_prompt += (
                f"\n\nThis image was originally vector-based and contained the following "
                f"extracted text:\n{extracted_text}"
            )

        log_action(f"Classified as: {category}")

        if latex_auto and category != "short_text_table_or_formula":
            log_action("(LaTeX Auto mode: skipping description for non-table/formula image)")
            return None, category

        d_opts = {"use_generate": False}
        if d_budget > 0:
            d_opts["visual_token_budget"] = d_budget

        desc_response = call_ai(
            provider="ollama",
            model=d_model,
            prompt=final_prompt,
            file_path=img_path,
            timeout=120,
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
            desc, category = _call_ollama(
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
        ollama_cfg = config.get("ollama", {})
        c_model = ollama_cfg.get("classification_model", ollama_cfg.get("model", "unknown"))
        d_model = ollama_cfg.get("description_model", ollama_cfg.get("model", "unknown"))
        log_info(f"Starting description of {total_images} images via Ollama (Class: {c_model}, Desc: {d_model})...")

    _traverse(doc, base_dir, config, state, latex_auto)

    if total_images > 0:
        log_success("Image description completed.")
