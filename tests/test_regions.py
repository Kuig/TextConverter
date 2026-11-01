"""Page segmentation and region planning, with no AI involved.

Usage: python -m unittest discover -s tests -p "test_regions.py"
"""
from __future__ import annotations
import io
import json
import tempfile
import unittest
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops, ImageDraw

from _support import INPUT_DIR, setUpModule, tearDownModule  # noqa: F401
from textconverter.regions import (
    Block, Crop, contact_sheet, crop_image, draw_overlay, find_blocks, needs_labels, parse_labels, plan_crops,
    plan_regions,
)

KNOWN = ("text", "table", "formula", "photo_drawing_or_comic", "diagram", "chart")


def _text_lines(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill="black", pitch: int = 18) -> None:
    """Draw lines of thin strokes grouped in words, with the proportions of printed text."""
    x0, y0, x1, y1 = box
    for line, y in enumerate(range(y0, y1 - 10, pitch)):
        x = x0
        while x < x1:
            for _ in range(3 + (x * 7 + line * 13) % 6):
                if x < x1:
                    draw.line((x, y, x, y + 9), fill=fill, width=2)
                x += 6
            x += 7


def _photo(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    """Draw a solid area of varied tones, as a photo gives."""
    x0, y0, x1, y1 = box
    for x in range(x0, x1, 12):
        for y in range(y0, y1, 12):
            draw.rectangle((x, y, min(x + 11, x1 - 1), min(y + 11, y1 - 1)), fill=((x * 3 + y * 5) % 120 + 20,) * 3)


class RegionTest(unittest.TestCase):

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)

    def page(self, paint, size=(800, 1100), background="white") -> str:
        """Write a page drawn by ``paint`` and return its path."""
        image = Image.new("RGB", size, background)
        paint(ImageDraw.Draw(image))
        path = self.dir / "page.png"
        image.save(path)
        return str(path)


class TestFindBlocks(RegionTest):

    def test_a_photo_is_one_block(self):
        def paint(draw):
            _photo(draw, (0, 0, 800, 1100))
        (block,) = find_blocks(self.page(paint))
        self.assertTrue(block.dense)
        self.assertEqual((block.x0, block.y0, block.x1, block.y1), (0, 0, 1, 1))

    def test_columns_read_left_then_right(self):
        def paint(draw):
            _text_lines(draw, (60, 80, 370, 980))
            _text_lines(draw, (430, 80, 740, 980))
        blocks = find_blocks(self.page(paint))
        self.assertEqual(len(blocks), 2)
        self.assertLess(blocks[0].x1, blocks[1].x0)

    def test_full_width_title_comes_before_the_columns(self):
        def paint(draw):
            _text_lines(draw, (60, 500, 370, 980))
            _text_lines(draw, (430, 500, 740, 980))
            draw.rectangle((100, 80, 700, 130), fill="black")
        blocks = find_blocks(self.page(paint))
        self.assertLess(blocks[0].y1, 0.2)
        self.assertLess(blocks[1].x1, blocks[2].x0)

    def test_photo_inside_flowing_text_is_a_block_of_its_own(self):
        """Text wrapping around a photo gives a block around both: the photo follows it."""
        def paint(draw):
            _text_lines(draw, (60, 100, 740, 330))
            _text_lines(draw, (340, 330, 740, 620))
            _text_lines(draw, (60, 620, 740, 900))
            _photo(draw, (60, 345, 310, 600))
        blocks = find_blocks(self.page(paint))
        photos = [b for b in blocks if b.dense]
        self.assertEqual(len(photos), 1)
        self.assertAlmostEqual(photos[0].x1, 310 / 800, delta=0.02)
        hosts = [b for b in blocks if b.area > photos[0].area and photos[0].share_inside(b) > 0.8]
        self.assertEqual(len(hosts), 1)
        self.assertEqual(blocks.index(photos[0]), blocks.index(hosts[0]) + 1)

    def test_framed_panel_is_looked_into(self):
        """A frame holds its content together as one component: its text and its photo still come apart."""
        def paint(draw):
            draw.rectangle((40, 200, 760, 800), outline="black", width=3)
            draw.line((400, 200, 400, 240), fill="black", width=3)
            _text_lines(draw, (80, 240, 370, 760))
            _photo(draw, (440, 300, 720, 700))
        blocks = find_blocks(self.page(paint))
        self.assertTrue(any(b.dense and b.x0 > 0.5 for b in blocks))
        self.assertTrue(any(not b.dense and b.x1 < 0.5 and b.y0 > 0.2 for b in blocks))

    def test_dark_background(self):
        def paint(draw):
            _text_lines(draw, (60, 100, 740, 500), fill="white")
        (block,) = find_blocks(self.page(paint, background="#102030"))
        self.assertFalse(block.dense)

    def test_small_images_give_fractions_too(self):
        """A small image is enlarged to the working size: blocks stay fractions of the image."""
        def paint(draw):
            draw.rectangle((8, 10, 70, 30), fill="black")
            draw.rectangle((8, 70, 70, 95), fill="black")
        blocks = find_blocks(self.page(paint, size=(80, 110)))
        self.assertEqual(len(blocks), 2)
        self.assertAlmostEqual(blocks[1].y1, 96 / 110, delta=0.01)

    def test_the_lines_of_a_title_are_one_block(self):
        def paint(draw):
            for y in (100, 150):
                draw.rectangle((100, y, 700, y + 30), fill="black")
        self.assertEqual(len(find_blocks(self.page(paint))), 1)

    def test_too_many_blocks_become_columns_first(self):
        """Over the limit paragraphs of one column join; a narrow centered line does not."""
        def paint(draw):
            for row in range(12):
                top = 40 + row * 85
                _text_lines(draw, (40, top, 370, top + 50))
                _text_lines(draw, (430, top, 760, top + 50))
            draw.rectangle((150, 1070, 650, 1085), fill="black")
        blocks = find_blocks(self.page(paint))
        self.assertLessEqual(len(blocks), 16)
        self.assertTrue(any(b.x0 > 0.15 and b.x1 < 0.85 for b in blocks))

    def test_no_block_is_repeated(self):
        blocks = find_blocks(str(INPUT_DIR / "Infographics_1.png"))
        self.assertEqual(len(blocks), len(set(blocks)))
        self.assertLessEqual(len(blocks), 24)

    def test_article_with_text_around_two_photos(self):
        """Fixture with a photo in the text flow and one at the side: both come out dense."""
        blocks = find_blocks(str(INPUT_DIR / "Article_image.png"))
        dense = [b for b in blocks if b.dense]
        self.assertTrue(any(b.x1 < 0.45 and 0.4 < b.y0 < 0.45 for b in dense))
        self.assertTrue(any(b.x0 > 0.75 for b in dense))

    def test_two_column_journal_page_reads_by_column(self):
        with pymupdf.open(INPUT_DIR / "Journal PDF.pdf") as pdf:
            path = str(self.dir / "journal.png")
            pdf[2].get_pixmap(dpi=200).save(path)
        blocks = find_blocks(path)
        lower = [b for b in blocks if b.y0 > 0.55]
        sides = ["left" if b.x1 < 0.5 else "right" for b in lower]
        self.assertEqual(sides, sorted(sides))


class TestNeedsLabels(RegionTest):

    def test_plain_text_needs_no_labels(self):
        def paint(draw):
            _text_lines(draw, (60, 80, 370, 980))
            _text_lines(draw, (430, 80, 740, 980))
        self.assertFalse(needs_labels(find_blocks(self.page(paint))))

    def test_a_photo_needs_labels(self):
        def paint(draw):
            _text_lines(draw, (60, 80, 740, 400))
            _photo(draw, (60, 500, 740, 1000))
        self.assertTrue(needs_labels(find_blocks(self.page(paint))))

    def test_a_table_with_rules_needs_labels(self):
        """Rows and rules hold a table together, and its columns leave a gap running down it."""
        def paint(draw):
            _text_lines(draw, (60, 80, 740, 400))
            for y in (500, 700):
                draw.line((100, y, 700, y), fill="black", width=2)
            for x in (120, 500):
                _text_lines(draw, (x, 520, x + 120, 680))
        self.assertTrue(needs_labels(find_blocks(self.page(paint))))

    def test_journal_page_with_only_text_is_recognized(self):
        with pymupdf.open(INPUT_DIR / "Journal PDF.pdf") as pdf:
            path = str(self.dir / "journal.png")
            pdf[0].get_pixmap(dpi=200).save(path)
        self.assertFalse(needs_labels(find_blocks(path)))


class TestContactSheet(RegionTest):

    def test_one_tile_per_block_in_a_square_grid(self):
        path = self.page(lambda draw: _text_lines(draw, (60, 80, 740, 400)))
        blocks = [Block(0, 0, 1, 0.1), Block(0, 0.2, 1, 0.3), Block(0, 0.4, 1, 0.5), Block(0, 0.6, 1, 0.7),
                  Block(0, 0.8, 1, 0.9)]
        sheet = Image.open(io.BytesIO(contact_sheet(path, blocks)))
        self.assertEqual(sheet.size, (1398, 1400))

    def test_a_block_inside_another_is_blanked_from_its_tile(self):
        """The photo in a paragraph has its own tile and must not show in the paragraph's."""
        path = self.page(lambda draw: _photo(draw, (300, 400, 500, 600)))
        host, photo = Block(0, 0, 1, 1), Block(300 / 800, 400 / 1100, 500 / 800, 600 / 1100, dense=True)
        sheet = Image.open(io.BytesIO(contact_sheet(path, [host, photo]))).convert("L")
        tile = sheet.crop((0, 40, 700, 1390))
        self.assertGreater(tile.point(lambda v: 255 if v > 200 else 0).histogram()[255], 0)
        self.assertEqual(tile.point(lambda v: 255 if v < 100 else 0).getbbox(), None)


class TestParseLabels(unittest.TestCase):

    def test_reads_labels_in_order(self):
        answer = json.dumps({"2": "table", "1": "text"})
        self.assertEqual(parse_labels(answer, 2, KNOWN), ["text", "table"])

    def test_accepts_a_code_fence(self):
        self.assertEqual(parse_labels('```json\n{"1": "text"}\n```', 1, KNOWN), ["text"])

    def test_partial_or_wrong_answers_are_refused(self):
        for answer in ('{"1": "text"}', '{"1": "text", "2": "banana"}', '{"1": "text", "2": 3}', "not json",
                       "[1, 2]", "", None):
            self.assertIsNone(parse_labels(answer, 2, KNOWN), answer)


class TestPlanRegions(unittest.TestCase):

    def test_one_kind_of_content_stays_whole(self):
        blocks = [Block(0, 0, 1, 0.4), Block(0, 0.5, 1, 1)]
        self.assertEqual(plan_regions(blocks, ["text", "text"]), [])
        self.assertEqual(plan_regions(blocks, ["chart", "chart"]), [])

    def test_mixed_content_splits_in_order(self):
        blocks = [Block(0, 0, 1, 0.4), Block(0, 0.5, 1, 1)]
        regions = plan_regions(blocks, ["text", "table"])
        self.assertEqual([r.label for r in regions], ["text", "table"])

    def test_pieces_of_one_figure_join(self):
        blocks = [Block(0, 0, 1, 0.2), Block(0, 0.3, 0.45, 1), Block(0.46, 0.3, 1, 1)]
        regions = plan_regions(blocks, ["text", "diagram", "diagram"])
        self.assertEqual([r.label for r in regions], ["text", "diagram"])
        self.assertEqual((regions[1].x0, regions[1].x1), (0, 1))

    def test_figures_do_not_join_across_something_else(self):
        """Two photos at the corners of an article stay apart: their union would hold its text."""
        blocks = [Block(0, 0, 0.3, 0.2), Block(0.31, 0.21, 1, 0.9), Block(0, 0.21, 0.3, 0.9)]
        labels = ["photo_drawing_or_comic", "text", "photo_drawing_or_comic"]
        self.assertEqual(len(plan_regions(blocks, labels)), 2)
        apart = [Block(0, 0, 0.5, 0.5), Block(0, 0.1, 1, 0.9), Block(0.51, 0.5, 1, 1)]
        self.assertEqual(len(plan_regions(apart, labels)), 3)

    def test_text_never_joins_as_a_figure(self):
        blocks = [Block(0, 0, 1, 0.2), Block(0, 0.21, 1, 0.4), Block(0, 0.5, 1, 1)]
        self.assertEqual(len(plan_regions(blocks, ["text", "text", "chart"])), 3)

    def test_what_lies_in_a_figure_belongs_to_it(self):
        blocks = [Block(0, 0, 1, 0.2), Block(0, 0.3, 1, 1), Block(0.1, 0.4, 0.3, 0.5)]
        regions = plan_regions(blocks, ["text", "diagram", "text"])
        self.assertEqual([r.label for r in regions], ["text", "diagram"])

    def test_a_photo_in_text_is_kept(self):
        """Only figures absorb: text around a photo does not."""
        blocks = [Block(0, 0, 1, 0.8), Block(0.1, 0.2, 0.4, 0.5)]
        regions = plan_regions(blocks, ["text", "photo_drawing_or_comic"])
        self.assertEqual(len(regions), 2)

    def test_a_tall_formula_block_is_text(self):
        """A paragraph holding a formula goes to the text reader, or the prose would be lost."""
        blocks = [Block(0, 0, 1, 0.2), Block(0, 0.3, 1, 0.5)]
        self.assertEqual(plan_regions(blocks, ["chart", "formula"])[1].label, "text")
        low = [Block(0, 0, 1, 0.2), Block(0, 0.3, 1, 0.35)]
        self.assertEqual(plan_regions(low, ["chart", "formula"])[1].label, "formula")

    def test_no_split_is_left_when_labels_collapse(self):
        """A formula corrected to text can leave one kind of content."""
        blocks = [Block(0, 0, 1, 0.2), Block(0, 0.3, 1, 0.5)]
        self.assertEqual(plan_regions(blocks, ["text", "formula"]), [])


class TestPlanCrops(unittest.TestCase):

    READ = ("text", "table", "formula")

    def regions(self, *items):
        return plan_regions([b for b, _ in items], [label for _, label in items])

    def test_consecutive_text_is_read_at_once(self):
        regions = self.regions((Block(0, 0, 1, 0.1), "text"), (Block(0, 0.2, 1, 0.3), "text"),
                               (Block(0, 0.4, 1, 0.5), "chart"), (Block(0, 0.6, 1, 0.7), "text"))
        crops = plan_crops(regions, self.READ)
        self.assertEqual([c.box.label for c in crops], ["text", "chart", "text"])
        self.assertEqual((crops[0].box.y0, crops[0].box.y1), (0, 0.3))

    def test_a_figure_inside_a_run_is_masked(self):
        regions = self.regions((Block(0, 0, 1, 0.8), "text"), (Block(0.1, 0.2, 0.4, 0.5), "chart"))
        crops = plan_crops(regions, self.READ)
        self.assertEqual(crops[0].masks, (regions[1],))
        self.assertEqual(crops[1].masks, ())

    def test_a_run_does_not_mask_what_it_reads(self):
        """A wide block overlapping the run is left visible when it covers part of the run."""
        regions = self.regions((Block(0, 0, 0.5, 0.2), "text"), (Block(0, 0.1, 1, 0.5), "chart"))
        self.assertEqual(plan_crops(regions, self.READ)[0].masks, ())

    def test_tables_and_formulas_are_crops_of_their_own(self):
        regions = self.regions((Block(0, 0, 1, 0.1), "table"), (Block(0, 0.2, 1, 0.25), "formula"),
                               (Block(0, 0.3, 1, 0.5), "text"))
        self.assertEqual([c.box.label for c in plan_crops(regions, self.READ)], ["table", "formula", "text"])


class TestCropImage(RegionTest):

    def test_crop_size_and_padding(self):
        path = self.page(lambda draw: None, size=(1000, 500))
        crop = Crop(Block(0.2, 0.2, 0.4, 0.6))
        self.assertEqual(Image.open(io.BytesIO(crop_image(path, crop, 0))).size, (200, 200))
        self.assertEqual(Image.open(io.BytesIO(crop_image(path, crop, 0.01))).size, (220, 210))

    def test_padding_stops_at_the_image_border(self):
        path = self.page(lambda draw: None, size=(1000, 500))
        crop = Crop(Block(0, 0, 1, 1))
        self.assertEqual(Image.open(io.BytesIO(crop_image(path, crop, 0.05))).size, (1000, 500))

    def test_masks_take_the_background_color(self):
        path = self.page(lambda draw: draw.rectangle((100, 100, 200, 200), fill="red"), background="#102030")
        crop = Crop(Block(0, 0, 1, 1), masks=(Block(0.1, 0.05, 0.3, 0.25),))
        result = Image.open(io.BytesIO(crop_image(path, crop, 0))).convert("RGB")
        blank = Image.new("RGB", result.size, "#102030")
        self.assertIsNone(ImageChops.difference(result, blank).getbbox())

    def test_grayscale_and_transparent_images_can_be_cropped(self):
        for mode in ("L", "RGBA", "P"):
            path = self.dir / f"{mode}.png"
            Image.new(mode, (100, 100)).save(path)
            self.assertTrue(crop_image(str(path), Crop(Block(0, 0, 0.5, 0.5)), 0))


class TestOverlay(RegionTest):

    def test_overlay_is_written_with_the_size_of_the_image(self):
        path = self.page(lambda draw: None, size=(300, 200))
        out = self.dir / "overlay.png"
        draw_overlay(path, [Block(0.1, 0.1, 0.9, 0.9, label="text")], str(out))
        with Image.open(out) as image:
            self.assertEqual(image.size, (300, 200))
            self.assertIsNotNone(ImageChops.difference(image.convert("RGB"), Image.new("RGB", (300, 200), "white")).getbbox())


if __name__ == "__main__":
    unittest.main()
