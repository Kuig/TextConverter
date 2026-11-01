"""Split a page image into regions: blocks found with Pillow, labelled by a vision model.

Vision models name what they see far better than they locate it, so the
geometry stays here and the model only labels: ``find_blocks`` segments the
page, ``contact_sheet`` shows the blocks as numbered tiles for one AI call,
``parse_labels`` reads the answer, ``plan_regions`` decides whether to split
and ``plan_crops`` says what to read from where. Nothing here calls a model.
"""
from __future__ import annotations

import io
import json
import math
from collections import deque
from collections.abc import Collection, Iterable
from dataclasses import dataclass, replace

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .parsers.transcription_parser import strip_fence

# Pages are segmented at this size: the pixel constants below are relative to it.
_SIDE = 800
# A value is background within this bin width, so JPEG noise does not split it.
_BACKGROUND_BIN = 8
# With less background than this the area is a picture, not a layout.
_MIN_BACKGROUND = 0.35
_INK_DIFFERENCE = 28
_DILATION = 9
_CLOSING = 5
_EROSION = 13
_MIN_DENSE_SIDE = 40
_DENSE_MARGIN = 8
_MAX_DEPTH = 3
# A block this large (of the page), and smaller than its parent, is a panel to look into.
_PANEL_AREA = 0.08
_PANEL_OF_PARENT = 0.95
_MIN_BLOCK_AREA = 0.0004
_MIN_BLOCK_SIDE = 4
# Lines of one title: both this thin (of the page height), closer than this share of them.
_THIN_LINE = 0.06
_LINE_GAP = 0.8
# Paragraphs of one column: edges this aligned (of the width), this close (of the height).
_COLUMN_LEFT = 0.03
_COLUMN_RIGHT = 0.05
_COLUMN_GAP = 0.05
# Tiles worth having, and the most a contact sheet stays readable with.
_FEW_BLOCKS = 16
_MAX_BLOCKS = 24
# Blocks closer than this (in pixels) still count as separated by a gap.
_ORDER_TOLERANCE = 2
# A plain column of text has no gap this wide (of its width) running down it.
_TEXT_GUTTER = 0.05
# A table column broken off from its table: narrower and shorter than these, of the page.
_TABLE_COLUMN_WIDTH = 0.35
_TABLE_COLUMN_HEIGHT = 0.2
# A block is inside another when this share of it is covered.
_CONTAINED = 0.8
# A display formula is a few lines: anything taller is a paragraph holding one.
_MAX_FORMULA_HEIGHT = 0.08
_FIGURE_GAP = 0.03
_SWALLOWED = 0.2
_SHEET_SIDE = 1400
_TAG_HEIGHT = 30
_TAG_WIDTH = 56
_TILE_MARGIN = 4


@dataclass(frozen=True)
class Block:
    """A rectangle of the page, top-left origin.

    Attributes:
        x0: Left edge, as a fraction of the width.
        y0: Top edge, as a fraction of the height.
        x1: Right edge, as a fraction of the width.
        y1: Bottom edge, as a fraction of the height.
        dense: A solid area (photo, QR code, filled shape), not lines of ink.
        plain_text: Reads as a column of text: not dense, no gutter running down it.
        label: What the block holds, once it has been labelled.
    """
    x0: float
    y0: float
    x1: float
    y1: float
    dense: bool = False
    plain_text: bool = False
    label: str | None = None

    @property
    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def share_inside(self, other: Block) -> float:
        """The share of this block that ``other`` covers."""
        width = min(self.x1, other.x1) - max(self.x0, other.x0)
        height = min(self.y1, other.y1) - max(self.y0, other.y0)
        return max(width, 0) * max(height, 0) / self.area if self.area else 0.0

    def gap(self, other: Block) -> float:
        """How far apart two blocks are, along both axes; 0 when they touch."""
        dx = max(self.x0 - other.x1, other.x0 - self.x1, 0)
        dy = max(self.y0 - other.y1, other.y0 - self.y1, 0)
        return dx + dy

    def union(self, other: Block) -> Block:
        """The rectangle around both; it is dense only when both are."""
        return replace(self, x0=min(self.x0, other.x0), y0=min(self.y0, other.y0), x1=max(self.x1, other.x1),
                       y1=max(self.y1, other.y1), dense=self.dense and other.dense,
                       plain_text=self.plain_text and other.plain_text)


@dataclass(frozen=True)
class Crop:
    """One piece of a split page: what to cut out, and what to blank in it.

    Attributes:
        box: The area; its ``label`` says how to read it.
        masks: Blocks to cover: what else falls inside ``box``.
    """
    box: Block
    masks: tuple[Block, ...] = ()


def _background(gray: Image.Image) -> tuple[int, float]:
    """The background level of a grayscale image, and the share of pixels at it."""
    histogram = gray.histogram()
    start = max(range(0, 256, _BACKGROUND_BIN), key=lambda v: sum(histogram[v:v + _BACKGROUND_BIN]))
    return start + _BACKGROUND_BIN // 2, sum(histogram[start:start + _BACKGROUND_BIN]) / (gray.width * gray.height)


def _components(mask: Image.Image) -> list[tuple[int, int, int, int]]:
    """The bounding boxes of the connected areas of a binary image."""
    width, height = mask.size
    pixels = bytearray(mask.tobytes())
    boxes = []
    for start, value in enumerate(pixels):
        if not value:
            continue
        pixels[start] = 0
        queue = deque([start])
        x0, y0, x1, y1 = width, height, 0, 0
        while queue:
            i = queue.popleft()
            y, x = divmod(i, width)
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            for n, inside in ((i - 1, x > 0), (i + 1, x < width - 1), (i - width, y > 0), (i + width, y < height - 1)):
                if inside and pixels[n]:
                    pixels[n] = 0
                    queue.append(n)
        boxes.append((x0, y0, x1 + 1, y1 + 1))
    return boxes


def _dense_areas(ink: Image.Image) -> list[tuple[int, int, int, int]]:
    """Solid areas of a binary image: only they survive a closing and a strong erosion."""
    solid = ink.filter(ImageFilter.MaxFilter(_CLOSING)).filter(ImageFilter.MinFilter(_EROSION))
    found = []
    for x0, y0, x1, y1 in _components(solid):
        if x1 - x0 < _MIN_DENSE_SIDE or y1 - y0 < _MIN_DENSE_SIDE:
            continue
        left, top = max(0, x0 - _DENSE_MARGIN), max(0, y0 - _DENSE_MARGIN)
        tight = ink.crop((left, top, min(ink.width, x1 + _DENSE_MARGIN), min(ink.height, y1 + _DENSE_MARGIN))).getbbox()
        found.append((left + tight[0], top + tight[1], left + tight[2], top + tight[3]))
    return found


def _segment(gray: Image.Image, box: tuple[int, int, int, int], depth: int, out: list[Block]) -> None:
    """Add the blocks of ``box`` to ``out``, in pixels; a panel with its own background is segmented in turn."""
    crop = gray.crop(box)
    level, share = _background(crop)
    if share < _MIN_BACKGROUND:
        out.append(Block(*box, dense=True))
        return
    ink = crop.point(lambda v: 255 if abs(v - level) > _INK_DIFFERENCE else 0)
    left, top = box[0], box[1]
    dense = _dense_areas(ink)
    draw = ImageDraw.Draw(ink)
    for x0, y0, x1, y1 in dense:
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=0)
        out.append(Block(left + x0, top + y0, left + x1, top + y1, dense=True))
    box_area = (box[2] - box[0]) * (box[3] - box[1])
    page_area = gray.width * gray.height
    for x0, y0, x1, y1 in _components(ink.filter(ImageFilter.MaxFilter(_DILATION))):
        tight = ink.crop((x0, y0, x1, y1)).getbbox()
        if tight is None:
            continue
        rect = (left + x0 + tight[0], top + y0 + tight[1], left + x0 + tight[2], top + y0 + tight[3])
        width, height = rect[2] - rect[0], rect[3] - rect[1]
        area = width * height
        if depth < _MAX_DEPTH and _PANEL_AREA * page_area < area < _PANEL_OF_PARENT * box_area:
            _segment(gray, rect, depth + 1, out)
        elif area >= _MIN_BLOCK_AREA * page_area and min(width, height) >= _MIN_BLOCK_SIDE:
            out.append(Block(*rect))


def _join_title_lines(blocks: list[Block], height: int) -> list[Block]:
    """Join thin text blocks stacked close together: the lines of one title."""
    thin = _THIN_LINE * height

    def lines_of_a_title(a: Block, b: Block) -> bool:
        a_height, b_height = a.y1 - a.y0, b.y1 - b.y0
        overlap = min(a.x1, b.x1) - max(a.x0, b.x0)
        return (not a.dense and not b.dense and a_height < thin and b_height < thin
                and overlap > 0.5 * min(a.x1 - a.x0, b.x1 - b.x0)
                and 0 <= b.y0 - a.y1 < _LINE_GAP * min(a_height, b_height))

    blocks = list(blocks)
    while True:
        pair = next(((i, j) for i, a in enumerate(blocks) for j, b in enumerate(blocks)
                     if i != j and lines_of_a_title(a, b)), None)
        if pair is None:
            return blocks
        i, j = pair
        joined = blocks[i].union(blocks[j])
        blocks = [b for n, b in enumerate(blocks) if n not in pair] + [joined]


def _join_columns(blocks: list[Block], limit: int, width: int, height: int) -> list[Block]:
    """Join paragraphs of one column, smallest pair first, until at most ``limit`` remain.

    Only aligned text blocks join: a centered formula or a caption is not one
    of them, so a limit does not mix what the model must tell apart.
    """
    def same_column(a: Block, b: Block) -> bool:
        return (not a.dense and not b.dense and abs(a.x0 - b.x0) < _COLUMN_LEFT * width
                and abs(a.x1 - b.x1) < _COLUMN_RIGHT * width
                and min(abs(b.y0 - a.y1), abs(a.y0 - b.y1)) < _COLUMN_GAP * height)

    blocks = list(blocks)
    while len(blocks) > limit:
        pairs = [(i, j) for i in range(len(blocks)) for j in range(i + 1, len(blocks))
                 if same_column(blocks[i], blocks[j])]
        if not pairs:
            break
        i, j = min(pairs, key=lambda p: blocks[p[0]].area + blocks[p[1]].area)
        joined = blocks[i].union(blocks[j])
        blocks = [b for n, b in enumerate(blocks) if n not in (i, j)] + [joined]
    return blocks


def _join_nearest(blocks: list[Block], limit: int) -> list[Block]:
    """Last resort: merge the smallest text block into its nearest one, until at most ``limit`` remain."""
    blocks = list(blocks)
    while len(blocks) > limit:
        texts = [b for b in blocks if not b.dense]
        if len(texts) < 2:
            break
        small = min(texts, key=lambda b: b.area)
        near = min((b for b in texts if b is not small), key=small.gap)
        joined = small.union(near)
        blocks = [b for b in blocks
                  if b is not small and b is not near and (b.dense or b.share_inside(joined) < 0.9)] + [joined]
    return blocks


def _runs(blocks: list[Block], low: str, high: str) -> list[list[Block]]:
    """Split blocks into runs along one axis, wherever a gap crosses all of them."""
    runs: list[list[Block]] = []
    end = None
    for block in sorted(blocks, key=lambda b: getattr(b, low)):
        if end is None or getattr(block, low) >= end - _ORDER_TOLERANCE:
            runs.append([])
            end = getattr(block, high)
        runs[-1].append(block)
        end = max(end, getattr(block, high))
    return runs


def _columns_slice(rows: list[list[Block]]) -> tuple[int, int] | None:
    """The longest stretch of at least two rows that a vertical gap divides, but not all of them."""
    spans = sorted(((i, j) for i in range(len(rows)) for j in range(i + 2, len(rows) + 1)
                    if j - i < len(rows)), key=lambda s: s[0] - s[1])
    for i, j in spans:
        if len(_runs([block for row in rows[i:j] for block in row], "x0", "x1")) > 1:
            return i, j
    return None


def _cut_order(blocks: list[Block]) -> list[Block]:
    """Order blocks by cuts: columns go first, or a heading across them would mix them up.

    Cutting by rows first would alternate between two columns at every gap
    they happen to share, so where a full-width block prevents a vertical cut,
    the longest stretch of rows that allows one is read as columns.
    """
    if len(blocks) < 2:
        return blocks
    columns = _runs(blocks, "x0", "x1")
    if len(columns) > 1:
        return [block for column in columns for block in _cut_order(column)]
    rows = _runs(blocks, "y0", "y1")
    if len(rows) < 2:
        return sorted(blocks, key=lambda b: (b.y0, b.x0))
    stretch = _columns_slice(rows)
    if stretch is None:
        return [block for row in rows for block in _cut_order(row)]
    i, j = stretch
    parts = (rows[:i], rows[i:j], rows[j:])
    return [block for part in parts for block in _cut_order([b for row in part for b in row])]


def _reading_order(blocks: list[Block]) -> list[Block]:
    """Top to bottom, left column first; a block inside another follows it."""
    def host(block: Block) -> Block | None:
        hosts = [b for b in blocks if b is not block and b.area > block.area and block.share_inside(b) > _CONTAINED]
        return max(hosts, key=lambda b: b.area) if hosts else None

    hosts = {id(b): host(b) for b in blocks}
    ordered = []
    for top in _cut_order([b for b in blocks if hosts[id(b)] is None]):
        ordered.append(top)
        ordered.extend(b for b in blocks if hosts[id(b)] is top)
    ordered.extend(b for b in blocks if not any(b is o for o in ordered))
    return ordered


def _reads_as_text(gray: Image.Image, block: Block) -> bool:
    """True for a block with no gap running down it: a table or a figure has one, a text column does not."""
    crop = gray.crop((int(block.x0), int(block.y0), int(block.x1), int(block.y1)))
    level, _ = _background(crop)
    ink = crop.point(lambda v: 255 if abs(v - level) > _INK_DIFFERENCE else 0)
    columns = ink.resize((ink.width, 1), Image.BOX).tobytes()
    longest = run = 0
    for value in columns:
        run = 0 if value else run + 1
        longest = max(longest, run)
    return longest < _TEXT_GUTTER * ink.width


def find_blocks(path: str) -> list[Block]:
    """Find the blocks of a page image, in reading order.

    Args:
        path: Image file path.

    Returns:
        The blocks, in fractions of the image. A photo is a single block.

    Raises:
        OSError: If the file cannot be read as an image.
    """
    with Image.open(path) as source:
        gray = source.convert("L")
    scale = _SIDE / max(gray.size)
    size = (max(1, int(gray.width * scale)), max(1, int(gray.height * scale)))
    gray = gray.resize(size, Image.BICUBIC if scale > 1 else Image.BOX)
    blocks: list[Block] = []
    _segment(gray, (0, 0, gray.width, gray.height), 0, blocks)
    blocks = _join_title_lines(list(dict.fromkeys(blocks)), gray.height)
    blocks = _join_columns(blocks, _FEW_BLOCKS, gray.width, gray.height)
    blocks = _reading_order(_join_nearest(blocks, _MAX_BLOCKS))
    return [replace(b, x0=b.x0 / gray.width, y0=b.y0 / gray.height, x1=b.x1 / gray.width, y1=b.y1 / gray.height,
                    plain_text=not b.dense and _reads_as_text(gray, b))
            for b in blocks]


def _looks_tabular(a: Block, b: Block) -> bool:
    """True for two short narrow blocks side by side: the columns of a table with no rules through them."""
    def short_and_narrow(block: Block) -> bool:
        return block.x1 - block.x0 < _TABLE_COLUMN_WIDTH and block.y1 - block.y0 < _TABLE_COLUMN_HEIGHT

    return short_and_narrow(a) and short_and_narrow(b) and min(a.y1, b.y1) > max(a.y0, b.y0)


def needs_labels(blocks: list[Block]) -> bool:
    """False when the page is plain text: nothing to split, so the labelling call can be skipped."""
    if not all(b.plain_text for b in blocks):
        return True
    return any(_looks_tabular(a, b) for i, a in enumerate(blocks) for b in blocks[i + 1:])


def _pixels(block: Block, size: tuple[int, int]) -> tuple[int, int, int, int]:
    return int(block.x0 * size[0]), int(block.y0 * size[1]), int(block.x1 * size[0]), int(block.y1 * size[1])


def _blanked(image: Image.Image, box: tuple[int, int, int, int], masks: Iterable[Block]) -> Image.Image:
    """Cut ``box`` out of ``image`` with ``masks`` covered in the crop's dominant color."""
    tile = image.crop(box)
    fill = max(tile.getcolors(tile.width * tile.height), key=lambda c: c[0])[1]
    draw = ImageDraw.Draw(tile)
    for mask in masks:
        x0, y0, x1, y1 = _pixels(mask, image.size)
        draw.rectangle((x0 - box[0], y0 - box[1], x1 - box[0], y1 - box[1]), fill=fill)
    return tile


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def contact_sheet(path: str, blocks: list[Block]) -> bytes:
    """Show the blocks of a page as numbered tiles on one sheet, as a PNG.

    Each block is enlarged and seen alone, which a model labels far better than
    boxes drawn on the page. What lies inside a block is blanked out of it: a
    photo amid a paragraph has its own tile.

    Args:
        path: Image file path.
        blocks: The blocks, numbered from 1 in this order.

    Returns:
        The PNG bytes.
    """
    with Image.open(path) as source:
        image = source.convert("RGB")
    columns = max(1, math.ceil(math.sqrt(len(blocks))))
    rows = max(1, math.ceil(len(blocks) / columns))
    cell_width, cell_height = _SHEET_SIDE // columns, _SHEET_SIDE // rows
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "#808080")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=24)
    for number, block in enumerate(blocks, 1):
        inner = [b for b in blocks if b.area < block.area and b.share_inside(block) > _CONTAINED]
        tile = _blanked(image, _pixels(block, image.size), inner)
        row, column = divmod(number - 1, columns)
        x, y = column * cell_width + _TILE_MARGIN, row * cell_height + _TILE_MARGIN
        scale = min((cell_width - 2 * _TILE_MARGIN) / tile.width,
                    (cell_height - _TAG_HEIGHT - 3 * _TILE_MARGIN) / tile.height)
        tile = tile.resize((max(1, int(tile.width * scale)), max(1, int(tile.height * scale))))
        draw.rectangle((x, y, x + _TAG_WIDTH, y + _TAG_HEIGHT), fill="black")
        draw.text((x + _TILE_MARGIN, y), str(number), fill="white", font=font)
        sheet.paste(tile, (x, y + _TAG_HEIGHT + 2))
    return _png(sheet)


def parse_labels(answer: str | None, count: int, known: Collection[str]) -> list[str] | None:
    """Read the labels of ``count`` tiles from an answer such as ``{"1": "text", "2": "table"}``.

    Args:
        answer: The model's answer.
        count: The number of tiles.
        known: The accepted labels.

    Returns:
        One label per tile, in order, or None unless every tile has a known one:
        a partial answer gives no reliable split.
    """
    try:
        data = json.loads(strip_fence(answer or ""))
        labels = [data[str(number)] for number in range(1, count + 1)]
    except (ValueError, TypeError, KeyError):
        return None
    return labels if all(isinstance(label, str) and label in known for label in labels) else None


def _accepted_label(block: Block, label: str) -> str:
    """The label a block keeps: a paragraph holding a formula is text, whatever the model says."""
    return "text" if label == "formula" and block.y1 - block.y0 > _MAX_FORMULA_HEIGHT else label


def _join_figures(blocks: list[Block]) -> list[Block]:
    """Join near pieces of one figure, unless the union would cover something with another label."""
    blocks = list(blocks)

    def joinable(i: int, j: int) -> Block | None:
        a, b = blocks[i], blocks[j]
        if a.label != b.label or a.label == "text" or a.gap(b) > _FIGURE_GAP:
            return None
        joined = a.union(b)
        others = (o for n, o in enumerate(blocks) if n not in (i, j) and o.label != a.label)
        return None if any(o.share_inside(joined) > _SWALLOWED for o in others) else joined

    while True:
        found = next(((i, j, joined) for i in range(len(blocks)) for j in range(i + 1, len(blocks))
                      if (joined := joinable(i, j)) is not None), None)
        if found is None:
            return blocks
        i, j, joined = found
        blocks = [joined if n == i else b for n, b in enumerate(blocks) if n != j]


def _without_figure_parts(blocks: list[Block]) -> list[Block]:
    """Drop what lies inside a figure: it belongs to the figure."""
    figures = [b for b in blocks if b.label != "text"]
    return [b for b in blocks
            if not any(f is not b and f.area > b.area and b.share_inside(f) > _CONTAINED for f in figures)]


def plan_regions(blocks: list[Block], labels: list[str]) -> list[Block]:
    """Decide whether a labelled page splits, and into what.

    Args:
        blocks: The blocks, in reading order.
        labels: One label per block.

    Returns:
        The labelled regions in reading order, or an empty list when the page
        stays whole: all its content is of one kind.
    """
    labelled = [replace(b, label=_accepted_label(b, label)) for b, label in zip(blocks, labels)]
    if len({b.label for b in labelled}) < 2:
        return []
    regions = _without_figure_parts(_join_figures(labelled))
    return regions if len({b.label for b in regions}) > 1 else []


def plan_crops(regions: list[Block], read: Collection[str]) -> list[Crop]:
    """Turn regions into crops: consecutive regions labelled ``"text"`` are read together.

    A run of text is one crop, so the OCR model reads a stretch of page at
    once: its reading of the text is at least as good, for far fewer calls.

    Args:
        regions: The regions, in reading order.
        read: The labels transcribed from the image, whose crops blank the rest.

    Returns:
        The crops, in reading order.
    """
    groups: list[list[Block]] = []
    for region in regions:
        if region.label == "text" and groups and groups[-1][-1].label == "text":
            groups[-1].append(region)
        else:
            groups.append([region])
    crops = []
    for group in groups:
        box = group[0]
        for region in group[1:]:
            box = box.union(region)
        masks: tuple[Block, ...] = ()
        if box.label in read:
            masks = tuple(o for o in regions
                          if not any(o is member for member in group) and o.share_inside(box) > 0
                          and not any(member.share_inside(o) > _SWALLOWED for member in group))
        crops.append(Crop(box, masks))
    return crops


def crop_image(path: str, crop: Crop, padding: float) -> bytes:
    """Cut a crop out of an image, as a PNG.

    Args:
        path: Image file path.
        crop: What to cut out.
        padding: Margin added on each side, as a fraction of the image's side.

    Returns:
        The PNG bytes.
    """
    with Image.open(path) as source:
        image = source.convert("RGB")
    x_margin, y_margin = padding * image.width, padding * image.height
    box = crop.box
    area = (max(0, int(box.x0 * image.width - x_margin)), max(0, int(box.y0 * image.height - y_margin)),
            min(image.width, math.ceil(box.x1 * image.width + x_margin)),
            min(image.height, math.ceil(box.y1 * image.height + y_margin)))
    return _png(_blanked(image, area, crop.masks))


def draw_overlay(path: str, blocks: list[Block], out_path: str) -> None:
    """Save a copy of an image with its labelled blocks drawn on it, to check a detection by eye.

    Args:
        path: Image file path.
        blocks: The blocks; each has a ``label``.
        out_path: Where to write the PNG.
    """
    with Image.open(path) as source:
        image = source.convert("RGB")
    side = max(image.size)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=max(14, side // 65))
    for number, block in enumerate(blocks, 1):
        box = _pixels(block, image.size)
        draw.rectangle(box, outline="#d62728", width=max(2, side // 400))
        tag = f"{number} {block.label}"
        draw.rectangle(draw.textbbox(box[:2], tag, font=font), fill="#d62728")
        draw.text(box[:2], tag, fill="white", font=font)
    image.save(out_path, "PNG")
