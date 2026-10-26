from __future__ import annotations
import json
import os
from textconverter.logger import log_action, log_info, log_success, log_warning
from collections.abc import Callable
from .ast import Document, Image, Node, Paragraph, walk
from .config import AppConfig
from .images import expand_images, resolve_local
from .parsers.transcription_parser import normalize_transcription, transcription_nodes

# Categories that ``auto_latex`` transcribes; every other image keeps a plain reference.
LATEX_AUTO_CATEGORIES = ("text", "table", "formula")

_FALLBACK_PROMPT = "Describe the image in detail."
_MISSING_CLIENT = (
    "The 'unified_ai_client' package is required for AI-based image description. "
    "Please install it first (e.g. via requirements_prod.txt)."
)


def ai_client_available() -> bool:
    """True if the optional ``unified_ai_client`` package can be imported."""
    try:
        import unified_ai_client  # noqa: F401
    except ImportError:
        return False
    return True


def init_ai(config: AppConfig) -> None:
    """Register the provider connection settings, once per run.

    ``context_size`` is left out: it is passed to ``preload_model()`` instead,
    because Ollama allocates the context window at load time and a later
    mismatch forces a reload. A setup failure is logged, not raised: the calls
    that follow report the error per image.

    Args:
        config: The application configuration.
    """
    from unified_ai_client import configure_provider, silence_sdks

    silence_sdks()
    settings = dict(config.provider_settings())
    settings.pop("context_size", None)
    if not settings:
        return
    try:
        configure_provider(config.ai.provider, **settings)
    except Exception as exc:
        log_warning(f"AI provider setup failed: {exc}")


def _preload(model: str, config: AppConfig) -> None:
    """Load a model before its phase; a failure is logged and left to the calls."""
    from unified_ai_client import preload_model

    context_size = config.provider_settings().get("context_size")
    try:
        preload_model(config.ai.provider, model, context_size=context_size)
    except Exception as exc:
        log_warning(f"Could not preload {model}: {exc}")


def _ask(
    model: str,
    prompt: str,
    img_path: str,
    config: AppConfig,
    *,
    temperature: float | None = None,
    visual_token_budget: int = 0,
    format_json: bool = False,
) -> str | None:
    """Make one AI call on one image.

    Returns:
        The stripped answer, or None if the call failed (the failure is logged).
    """
    from unified_ai_client import call_ai

    options = {"visual_token_budget": visual_token_budget} if visual_token_budget > 0 else None
    try:
        response = call_ai(
            provider=config.ai.provider,
            model=model,
            prompt=prompt,
            file_path=img_path,
            temperature=temperature,
            format_json=format_json,
            extra_options=options,
        )
    except Exception as exc:
        log_warning(f"AI call failed for {img_path}, skipping: {exc}")
        return None
    if not getattr(response, "text", None):
        log_warning(f"Empty AI answer for {img_path}, skipping.")
        return None
    return response.text.strip()


def _classify(img_path: str, config: AppConfig) -> str:
    """Return the image category, or ``"default"`` when the answer is not a known one."""
    ai = config.ai
    answer = _ask(
        ai.classification_model,
        ai.classification_prompt,
        img_path,
        config,
        temperature=ai.classification_temperature,
        visual_token_budget=ai.classification_visual_token_budget,
        format_json=True,
    )
    try:
        category = json.loads(answer).get("category")
    except (TypeError, ValueError, AttributeError):
        return "default"
    return category if category in ai.prompts or category in ai.ocr_prompts else "default"


def _description_prompt(img: Image, config: AppConfig) -> str:
    """Category prompt for the description model, plus any text extracted from a vector image."""
    ai = config.ai
    prompt = ai.prompts.get(img.category, ai.prompts.get("default", _FALLBACK_PROMPT))
    if img.extracted_text and ai.provide_extracted_text_to_describer:
        prompt += (
            f"\n\nThis image was originally vector-based and contained the following "
            f"extracted text:\n{img.extracted_text}"
        )
    return prompt


def describe_images(images: list[Image], base_dir: str, *, config: AppConfig, latex_auto: bool = False) -> None:
    """Classify, describe and transcribe images in three phases, one model per phase.

    Every image is classified first; then the description model describes the
    images outside ``ai.ocr_prompts``; finally the OCR model (or, without one,
    the description model) transcribes the rest. Grouping the calls by model
    means each model is loaded at most once per run. Sets ``category`` and
    ``description`` on each Image in place; a missing file gets category
    ``"error"`` and a failed call leaves ``description`` unset.

    Args:
        images: Image nodes to process.
        base_dir: Directory that relative image paths resolve against.
        config: The application configuration.
        latex_auto: Only transcribe ``LATEX_AUTO_CATEGORIES``; describe nothing.
    """
    ai = config.ai
    jobs: list[tuple[Image, str]] = []
    for img in images:
        img_path = resolve_local(img.src, base_dir)
        if img_path is None:
            img.category = "error"
            log_warning(f"Not a local image file, skipping description: {img.src[:80]}")
        elif os.path.exists(img_path):
            jobs.append((img, img_path))
        else:
            img.category = "error"
            log_warning(f"Image file not found, skipping description: {img_path}")
    if not jobs:
        return

    init_ai(config)
    total = len(jobs)
    loaded: set[str] = set()

    def run_phase(verb: str, model: str, phase_jobs: list[tuple[Image, str]],
                  ask: Callable[[Image, str], None]) -> None:
        """Load ``model`` once, then run ``ask`` on each job with a progress line."""
        if not phase_jobs:
            return
        if model not in loaded:
            _preload(model, config)
            loaded.add(model)
        for i, (img, img_path) in enumerate(phase_jobs, 1):
            log_action(f"[{i}/{len(phase_jobs)}] {verb}: {img.src}")
            ask(img, img_path)

    def classify(img: Image, img_path: str) -> None:
        img.category = _classify(img_path, config)
        log_action(f"Classified as: {img.category}")

    run_phase("Classifying", ai.classification_model, jobs, classify)

    to_describe = [job for job in jobs if not latex_auto and job[0].category not in ai.ocr_prompts]
    to_transcribe = [
        job for job in jobs
        if job[0].category in ai.ocr_prompts
        and (not latex_auto or job[0].category in LATEX_AUTO_CATEGORIES)
    ]
    if latex_auto and total > len(to_transcribe):
        log_action("(LaTeX Auto mode: skipping description for non-text/table/formula images)")

    def describe(img: Image, img_path: str) -> None:
        img.description = _ask(
            ai.description_model, _description_prompt(img, config), img_path, config,
            visual_token_budget=ai.description_visual_token_budget,
        )

    def transcribe(img: Image, img_path: str) -> None:
        if ai.ocr_model:
            text = _ask(ai.ocr_model, ai.ocr_prompts[img.category], img_path, config,
                        temperature=ai.ocr_temperature)
        else:
            text = _ask(ai.description_model, _description_prompt(img, config), img_path, config,
                        visual_token_budget=ai.description_visual_token_budget)
        img.description = normalize_transcription(text) if text else None

    run_phase("Describing", ai.description_model, to_describe, describe)
    run_phase("Transcribing", ai.ocr_model or ai.description_model, to_transcribe, transcribe)


def _apply_latex_auto(node: Node) -> None:
    """Replace each transcribed image with its content as AST nodes.

    A formula becomes an Equation, a table a Table, and so on (see
    ``transcription_nodes``); an image alone in its paragraph replaces the
    whole paragraph. Images that were not transcribed stay as references.
    """
    def blocks(img: Image) -> list[Node] | None:
        if img.category not in LATEX_AUTO_CATEGORIES or not img.description:
            return None
        return transcription_nodes(img.description, img.category)

    expand_images(node, blocks)


def process_images(doc: Node, base_dir: str, *, config: AppConfig, latex_auto: bool = False) -> None:
    """Classify and describe all Image nodes of a document AST in place.

    Without ``unified_ai_client``, ``latex_auto`` (an implicit mode chosen by
    ``image_handling="auto"``) keeps the images as plain references with a
    warning, while an explicit ``describe`` raises ImportError.

    Args:
        doc: Root AST document node.
        base_dir: Base directory for resolving relative image paths.
        config: Application configuration.
        latex_auto: Transcribe only text/table/formula images and replace them
            with their content (see ``_apply_latex_auto``).
    """
    images = [node for node in walk(doc) if isinstance(node, Image)]
    if not images:
        return
    if not ai_client_available():
        if not latex_auto:
            raise ImportError(_MISSING_CLIENT)
        log_warning("unified_ai_client is not installed: images are kept as plain references.")
        return

    ai = config.ai
    log_info(
        f"Starting description of {len(images)} images via {ai.provider} "
        f"(Class: {ai.classification_model}, Desc: {ai.description_model}, "
        f"OCR: {ai.ocr_model or ai.description_model})..."
    )
    describe_images(images, base_dir, config=config, latex_auto=latex_auto)
    if latex_auto:
        _apply_latex_auto(doc)
    log_success("Image description completed.")


def transcribe_images(paths: list[str], *, config: AppConfig) -> Document:
    """Turn image files into a Document, one block of content per image, in order.

    Each image is classified, then described or transcribed (see
    ``describe_images``), and the answer is parsed into AST nodes. An image
    whose processing fails stays as a plain image reference.

    Args:
        paths: Image file paths.
        config: Application configuration.

    Raises:
        ImportError: If ``unified_ai_client`` is not installed.
    """
    if not ai_client_available():
        raise ImportError(_MISSING_CLIENT)
    images = [Image(src=path, alt=os.path.basename(path)) for path in paths]
    describe_images(images, "", config=config)

    doc = Document()
    for img in images:
        if not img.description:
            log_warning(f"No description generated for image {img.src}; keeping image reference.")
            doc.children.append(Paragraph(children=[img]))
            continue
        doc.children.extend(transcription_nodes(img.description, img.category))
    return doc
