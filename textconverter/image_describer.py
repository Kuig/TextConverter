from __future__ import annotations
import json
import os
import tempfile
from textconverter.logger import log_action, log_info, log_success, log_warning
from collections.abc import Callable
from dataclasses import dataclass, replace
from .ast import Document, Image, Node, Paragraph, walk
from .config import AppConfig
from .images import Expansion, expand_images, resolve_local
from .parsers.transcription_parser import normalize_transcription, transcription_nodes
from .regions import (
    Block, contact_sheet, crop_image, draw_overlay, find_blocks, needs_labels, parse_labels, plan_crops,
    plan_regions,
)

# Categories that ``auto_latex`` transcribes; every other image keeps a plain reference.
LATEX_AUTO_CATEGORIES = ("text", "table", "formula")
# Categories of a whole page, which may hold more than text and so can split into regions.
PAGE_CATEGORIES = ("text", "document_scan")
# The labels the default ``region_prompt`` offers; a region's label is its category.
REGION_LABELS = ("text", "table", "formula", "photo_drawing_or_comic", "diagram", "chart", "map", "logo_or_icon")
# Margin around a transcribed crop, of the image's side: blocks are cut tight to the ink, and
# what lies next to them is blanked. A figure gets none: the model reads a neighbour into it.
_REGION_PADDING = 0.01

# Writes a crop's PNG bytes where the output keeps its images; returns the ``src`` for the Image.
SaveCrop = Callable[[bytes], str]

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


@dataclass
class Split:
    """A page split into regions.

    Attributes:
        regions: One Image per crop, in reading order; each has its category,
            and its result once the description and OCR phases have run.
        blocks: The labelled blocks the regions were planned from.
    """
    regions: list[Image]
    blocks: list[Block]


def _ask(
    model: str,
    prompt: str,
    img_path: str,
    config: AppConfig,
    *,
    temperature: float | None = None,
    format_json: bool = False,
    max_tokens: int | None = None,
    thinking: bool | str = "default",
) -> str | None:
    """Make one AI call on one image.

    Returns:
        The stripped answer, or None if the call failed (the failure is logged).
    """
    from unified_ai_client import call_ai

    try:
        response = call_ai(
            provider=config.ai.provider,
            model=model,
            prompt=prompt,
            file_path=img_path,
            temperature=temperature,
            format_json=format_json,
            max_tokens=max_tokens,
            thinking=thinking,
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
        format_json=True,
        thinking=False,
    )
    try:
        category = json.loads(answer).get("category")
    except (TypeError, ValueError, AttributeError):
        return "default"
    return category if category in ai.prompts or category in ai.ocr_prompts else "default"


def _description_thinking(config: AppConfig) -> bool | str:
    """The ``thinking`` argument of a description call: the model's default, or off."""
    return "default" if config.ai.description_thinking else False


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


def _plan_split(img: Image, img_path: str, blocks: list[Block], tmp_dir: str, config: AppConfig) -> Split | None:
    """Label the blocks of a page and cut it into crops; None leaves the page whole.

    A contact sheet goes to ``ai.region_model`` with thinking off: on a task
    this plain, it costs minutes and can use up the token limit before any
    answer. Anything that goes wrong here leaves the image as it would be with
    no regions at all.
    """
    ai = config.ai
    try:
        sheet_path = os.path.join(tmp_dir, f"sheet_{id(img)}.png")
        with open(sheet_path, "wb") as f:
            f.write(contact_sheet(img_path, blocks))
        answer = _ask(ai.region_model, ai.region_prompt.replace("{count}", str(len(blocks))), sheet_path, config,
                      temperature=0.0, format_json=True, max_tokens=ai.region_max_tokens, thinking=False)
        labels = parse_labels(answer, len(blocks), REGION_LABELS)
        if labels is None:
            log_warning(f"Unusable region labels for {img_path}, keeping the page whole.")
            return None
        planned = plan_regions(blocks, labels)
        regions = []
        for number, crop in enumerate(plan_crops(planned, ai.ocr_prompts)):
            path = os.path.join(tmp_dir, f"region_{id(img)}_{number}.png")
            padding = _REGION_PADDING if crop.box.label in ai.ocr_prompts else 0
            with open(path, "wb") as f:
                f.write(crop_image(img_path, crop, padding))
            regions.append(Image(src=path, alt=img.alt, category=crop.box.label, render_metadata=img.render_metadata))
    except (OSError, ValueError) as exc:
        log_warning(f"Could not split {img_path} into regions, keeping the page whole: {exc}")
        return None
    return Split(regions, planned) if regions else None


def _page_blocks(jobs: list[tuple[Image, str]], config: AppConfig) -> dict[int, list[Block]]:
    """The blocks of each page worth labelling, by ``id`` of its Image: no model is involved yet."""
    blocks_by_image = {}
    for img, img_path in jobs:
        if not config.ai.region_model or img.category not in PAGE_CATEGORIES:
            continue
        try:
            blocks = find_blocks(img_path)
        except (OSError, ValueError) as exc:
            log_warning(f"Could not read {img_path} to look for regions: {exc}")
            continue
        if len(blocks) > 1 and needs_labels(blocks):
            blocks_by_image[id(img)] = blocks
    return blocks_by_image


def _keep_crops(splits: dict[int, Split], config: AppConfig, save_crop: SaveCrop | None) -> None:
    """Store the crops that are content: figures, and what could not be transcribed.

    Called while the temporary folder exists; a crop that is not stored loses
    its ``src``, and with no ``save_crop`` none is.
    """
    for split in splits.values():
        for region in split.regions:
            transcribed = region.category in config.ai.ocr_prompts and region.description
            if save_crop is None or transcribed:
                region.src = ""
                continue
            with open(region.src, "rb") as f:
                region.src = save_crop(f.read())


def _region_nodes(split: Split) -> list[Node]:
    """The AST blocks of a split page, in reading order.

    A stored crop is an Image node, carrying its description; without a file a
    region is what it says. A region with neither is lost, and reported.
    """
    nodes: list[Node] = []
    for region in split.regions:
        if region.src:
            nodes.append(Paragraph(children=[replace(region)]))
        elif region.description:
            nodes.extend(transcription_nodes(region.description, region.category))
        else:
            log_warning(f"A region labelled {region.category} could not be processed and is missing.")
    return nodes


def describe_images(
    images: list[Image],
    base_dir: str,
    *,
    config: AppConfig,
    latex_auto: bool = False,
    save_crop: SaveCrop | None = None,
) -> dict[int, Split]:
    """Classify, describe and transcribe images in phases, one model per phase.

    Every image is classified first; then pages holding more than text are
    split into regions; then the description model describes the images
    outside ``ai.ocr_prompts``; finally the OCR model (or, without one, the
    description model) transcribes the rest. The calls are grouped by model, so
    models swap between phases and never image by image. Sets ``category`` and
    ``description`` on each Image in place; a missing file gets category
    ``"error"`` and a failed call leaves ``description`` unset. A file used by
    several images is processed once, and its result is given to all of them.
    The regions of a split page take its place in the later phases, so the
    page itself gets no ``description``.

    Args:
        images: Image nodes to process.
        base_dir: Directory that relative image paths resolve against.
        config: The application configuration.
        latex_auto: Only transcribe ``LATEX_AUTO_CATEGORIES``; describe nothing.
        save_crop: Stores the crops worth keeping; without it they are dropped.

    Returns:
        The split pages, by ``id`` of their Image node.
    """
    jobs: list[tuple[Image, str]] = []
    copies: dict[str, list[Image]] = {}  # file -> the other images showing it
    for img in images:
        img_path = resolve_local(img.src, base_dir)
        if img_path is None:
            img.category = "error"
            log_warning(f"Not a local image file, skipping description: {img.src[:80]}")
        elif not os.path.exists(img_path):
            img.category = "error"
            log_warning(f"Image file not found, skipping description: {img_path}")
        else:
            key = os.path.normcase(os.path.abspath(img_path))
            if key in copies:
                copies[key].append(img)
            else:
                copies[key] = []
                jobs.append((img, img_path))
    if not jobs:
        return {}
    splits: dict[int, Split] = {}
    with tempfile.TemporaryDirectory(prefix="textconverter_regions_") as tmp_dir:
        try:
            _run_phases(jobs, config, latex_auto, tmp_dir, splits)
            _keep_crops(splits, config, save_crop)
        finally:
            for img, img_path in jobs:
                for copy in copies[os.path.normcase(os.path.abspath(img_path))]:
                    copy.category, copy.description = img.category, img.description
                    if id(img) in splits:
                        splits[id(copy)] = splits[id(img)]
    return splits


def _run_phases(
    jobs: list[tuple[Image, str]],
    config: AppConfig,
    latex_auto: bool,
    tmp_dir: str,
    splits: dict[int, Split],
) -> None:
    """The phases of ``describe_images`` on ``(image, file)`` jobs of distinct files; ``splits`` is filled in."""
    ai = config.ai

    init_ai(config)
    total = len(jobs)
    current_model = ""

    def run_phase(verb: str, model: str, phase_jobs: list[tuple[Image, str]],
                  ask: Callable[[Image, str], None]) -> None:
        """Load ``model`` unless it is the one in use, then run ``ask`` on each job with a progress line.

        A model coming back after another is loaded again here: left to the
        call, it would not get ``context_size`` (see ``init_ai``).
        """
        nonlocal current_model
        if not phase_jobs:
            return
        if model != current_model:
            _preload(model, config)
            current_model = model
        for i, (img, img_path) in enumerate(phase_jobs, 1):
            log_action(f"[{i}/{len(phase_jobs)}] {verb}: {img.src}")
            ask(img, img_path)

    def classify(img: Image, img_path: str) -> None:
        img.category = _classify(img_path, config)
        log_action(f"Classified as: {img.category}")

    run_phase("Classifying", ai.classification_model, jobs, classify)

    page_blocks = _page_blocks(jobs, config)

    def split(img: Image, img_path: str) -> None:
        result = _plan_split(img, img_path, page_blocks[id(img)], tmp_dir, config)
        if result is not None:
            splits[id(img)] = result
            log_action(f"Split into {len(result.regions)} regions")

    run_phase("Looking for regions", ai.region_model, [job for job in jobs if id(job[0]) in page_blocks], split)

    active = [job for job in jobs if id(job[0]) not in splits]
    active.extend((region, region.src) for page in splits.values() for region in page.regions)

    to_describe = [job for job in active if not latex_auto and job[0].category not in ai.ocr_prompts]
    to_transcribe = [
        job for job in active
        if job[0].category in ai.ocr_prompts
        and (not latex_auto or job[0].category in LATEX_AUTO_CATEGORIES)
    ]
    if latex_auto and total > len(to_transcribe):
        log_action("(LaTeX Auto mode: skipping description for non-text/table/formula images)")

    def describe(img: Image, img_path: str) -> None:
        img.description = _ask(ai.description_model, _description_prompt(img, config), img_path, config,
                               max_tokens=ai.description_max_tokens, thinking=_description_thinking(config))

    def transcribe(img: Image, img_path: str) -> None:
        if ai.ocr_model:
            text = _ask(ai.ocr_model, ai.ocr_prompts[img.category], img_path, config,
                        temperature=ai.ocr_temperature, max_tokens=ai.ocr_max_tokens)
        else:
            text = _ask(ai.description_model, _description_prompt(img, config), img_path, config,
                        max_tokens=ai.ocr_max_tokens, thinking=_description_thinking(config))
        img.description = normalize_transcription(text) if text else None

    run_phase("Describing", ai.description_model, to_describe, describe)
    run_phase("Transcribing", ai.ocr_model or ai.description_model, to_transcribe, transcribe)


def _apply_latex_auto(node: Node) -> None:
    """Replace each transcribed image with its content as AST nodes.

    A formula becomes an Equation, a table a Table, and so on (see
    ``transcription_nodes``); an image alone in its paragraph replaces the
    whole paragraph. Images that were not transcribed stay as references.
    """
    def blocks(img: Image) -> Expansion | None:
        if img.category not in LATEX_AUTO_CATEGORIES or not img.description:
            return None
        return Expansion(transcription_nodes(img.description, img.category))

    expand_images(node, blocks)


def process_images(
    doc: Node,
    base_dir: str,
    *,
    config: AppConfig,
    latex_auto: bool = False,
    save_crop: SaveCrop | None = None,
) -> None:
    """Classify and describe all Image nodes of a document AST in place.

    A page split into regions is replaced by them, in reading order; where
    blocks cannot go (a link, a table cell, a heading) the image stays and they
    follow.

    Without ``unified_ai_client``, ``latex_auto`` (an implicit mode chosen by
    ``image_handling="auto"``) keeps the images as plain references with a
    warning, while an explicit ``describe`` raises ImportError.

    Args:
        doc: Root AST document node.
        base_dir: Base directory for resolving relative image paths.
        config: Application configuration.
        latex_auto: Transcribe only text/table/formula images and replace them
            with their content (see ``_apply_latex_auto``).
        save_crop: Stores the crops worth keeping; without it they are dropped.
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
    splits = describe_images(images, base_dir, config=config, latex_auto=latex_auto, save_crop=save_crop)

    def regions(img: Image) -> Expansion | None:
        if id(img) not in splits:
            return None
        return Expansion(_region_nodes(splits[id(img)]), inline=[replace(img, description=None)])

    if splits:
        expand_images(doc, regions)
    if latex_auto:
        _apply_latex_auto(doc)
    log_success("Image description completed.")


def _write_overlay(img: Image, img_path: str, split: Split | None, overlay_path: str) -> None:
    """Save the image with what was found in it, or one box with its category; a failure is only reported."""
    if img.category in (None, "error"):
        return
    blocks = split.blocks if split else [Block(0.0, 0.0, 1.0, 1.0, label=img.category)]
    try:
        draw_overlay(img_path, blocks, overlay_path)
    except (OSError, ValueError) as exc:
        log_warning(f"Could not write the region overlay {overlay_path}: {exc}")


def transcribe_images(
    paths: list[str],
    *,
    config: AppConfig,
    save_crop: SaveCrop | None = None,
    overlay_path: str | None = None,
) -> Document:
    """Turn image files into a Document, one block of content per image, in order.

    Each image is classified, then described or transcribed (see
    ``describe_images``), and the answer is parsed into AST nodes; a page split
    into regions gives their nodes. An image whose processing fails stays as a
    plain image reference.

    Args:
        paths: Image file paths.
        config: Application configuration.
        save_crop: Stores the crops worth keeping; without it they are dropped.
        overlay_path: Where to save the first image with what was found in it.

    Raises:
        ImportError: If ``unified_ai_client`` is not installed.
    """
    if not ai_client_available():
        raise ImportError(_MISSING_CLIENT)
    images = [Image(src=path, alt=os.path.basename(path)) for path in paths]
    splits = describe_images(images, "", config=config, save_crop=save_crop)
    if overlay_path and images:
        _write_overlay(images[0], paths[0], splits.get(id(images[0])), overlay_path)

    doc = Document()
    for img in images:
        if id(img) in splits:
            doc.children.extend(_region_nodes(splits[id(img)]))
            continue
        if not img.description:
            log_warning(f"No description generated for image {img.src}; keeping image reference.")
            doc.children.append(Paragraph(children=[img]))
            continue
        doc.children.extend(transcription_nodes(img.description, img.category))
    return doc
