"""Excel (.xlsx) input: the fixture Test_sheets.xlsx and workbooks built with openpyxl.

Usage: python -m unittest discover -s tests -p "test_xlsx.py"
"""
from __future__ import annotations
import datetime
import os
import tempfile
from unittest.mock import patch

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Font

from textconverter import ConvertOptions, convert
from textconverter.ast import CodeBlock, Footnote, Heading, Image, Link, Table, Text, walk
from textconverter.formats import OUTPUT_FORMATS, infer_input_format, infer_input_format_from_media_type
from textconverter.parsers._excel_formulas import compress, expand
from textconverter.parsers.xlsx_parser import format_value, parse_xlsx
from textconverter.renderers._common import plain_text
from textconverter.renderers.csv_renderer import table_rows
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR, OUTPUT_DIR  # noqa: F401

FIXTURE = INPUT_DIR / "Test_sheets.xlsx"


def _grid(table: Table) -> list[list[str]]:
    return table_rows(table)


def _parse(workbook: Workbook, **kwargs):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "book.xlsx")
        workbook.save(path)
        return parse_xlsx(path, output_dir=tmp, image_dir_name="images", **kwargs)


class TestFormulaLines(BaseConverterTest):
    def test_a_column_of_one_formula_is_one_line(self):
        cells = {(r, 4): f"=B{r}*C{r}" for r in range(2, 6)}
        self.assertEqual(compress(cells), ["D2:D5 = B2*C2"])

    def test_a_row_of_one_formula_is_one_line(self):
        cells = {(10, c): f"=SUM({chr(64 + c)}2:{chr(64 + c)}9)" for c in range(2, 5)}
        self.assertEqual(compress(cells), ["B10:D10 = SUM(B2:B9)"])

    def test_different_formulas_stay_apart_and_absolute_references_hold(self):
        cells = {(2, 2): "=A2*$F$1", (3, 2): "=A3*$F$1", (4, 2): "=A4*2"}
        self.assertEqual(compress(cells), ["B2:B3 = A2*$F$1", "B4 = A4*2"])

    def test_expand_inverts_compress(self):
        cells = {(r, 4): f"=B{r}*C{r}" for r in range(2, 6)}
        cells[(7, 2)] = "=SUM(B2:B5)"
        self.assertEqual({(r, c): f for r, c, f in expand(compress(cells))}, cells)

    def test_expand_skips_what_is_not_a_formula_line(self):
        self.assertEqual(list(expand(["not a line", "A1:ZZ = x", "B2 = 1+1"])), [(2, 2, "=1+1")])

    def test_formula_with_equals_sign_inside(self):
        lines = compress({(2, 2): '=IF(A2 = "x", 1, 0)'})
        self.assertEqual([f for _, _, f in expand(lines)], ['=IF(A2 = "x", 1, 0)'])


class TestFormatValue(BaseConverterTest):
    def test_values(self):
        self.assertEqual(format_value(3.0), "3")
        self.assertEqual(format_value(2.25), "2.25")
        self.assertEqual(format_value(0.1 + 0.2), "0.3")
        self.assertEqual(format_value(True), "TRUE")
        self.assertEqual(format_value(datetime.datetime(2026, 10, 30)), "2026-10-30")
        self.assertEqual(format_value(datetime.datetime(2026, 10, 30, 14, 30)), "2026-10-30 14:30:00")
        self.assertEqual(format_value(datetime.time(9, 5)), "09:05:00")
        self.assertEqual(format_value(None), "")


class TestXlsxParser(BaseConverterTest):
    def setUp(self):
        super().setUp()
        self.images = OUTPUT_DIR / "sheets_parser_images"
        self.doc = parse_xlsx(str(FIXTURE), output_dir=str(OUTPUT_DIR), image_dir_name="sheets_parser_images")

    def test_formats(self):
        self.assertEqual(infer_input_format("a.XLSX"), "xlsx")
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        self.assertEqual(infer_input_format_from_media_type(media), "xlsx")
        self.assertEqual(OUTPUT_FORMATS["xlsx"].auto_images, "embed")

    def test_visible_sheets_are_level_one_headings_with_their_table(self):
        headings = [plain_text(n.children) for n in self.doc.children if isinstance(n, Heading)]
        self.assertEqual(headings, ["Sales", "Dates"])
        self.assertEqual(sum(isinstance(n, Table) for n in self.doc.children), 2)

    def test_a_single_sheet_has_no_heading(self):
        wb = Workbook()
        wb.active.append(["a", "b"])
        wb.active.append([1, 2])
        doc = _parse(wb)
        self.assertEqual([type(n) for n in doc.children], [Table])
        self.assertEqual(_grid(doc.children[0]), [["a", "b"], ["1", "2"]])

    def test_values_are_normalized_and_formulas_give_their_result(self):
        tables = [n for n in self.doc.children if isinstance(n, Table)]
        self.assertEqual(_grid(tables[0])[1:], [
            ["Apple", "3", "1.5", "4.5", "", ""], ["Pear", "5", "2.25", "11.25", "", ""],
            ["Plum", "2", "4", "8", "", ""], ["Sum", "10", "7.75", "20.5", "", ""]])
        self.assertEqual(_grid(tables[1])[1], ["2026-10-30", "TRUE", "very important"])
        self.assertEqual(_grid(tables[1])[2], ["2026-10-31 14:30:00", "FALSE", "007"])

    def test_formulas_are_one_code_block_under_the_table(self):
        block = next(n for n in self.doc.children if isinstance(n, CodeBlock))
        self.assertEqual(block.language, "excel")
        self.assertEqual(block.code.splitlines(), ["D2:D4 = B2*C2", "B5:D5 = SUM(B2:B4)"])

    def test_comment_link_and_rich_text(self):
        nodes = list(walk(self.doc))
        self.assertEqual([plain_text(n.content) for n in nodes if isinstance(n, Footnote)], ["Fresh\nfrom the market"])
        link = next(n for n in nodes if isinstance(n, Link))
        self.assertEqual((link.url, plain_text(link.content)), ("https://example.com", "Pear"))
        very = next(n for n in nodes if isinstance(n, Text) and n.content == "very ")
        self.assertTrue(very.bold)
        self.assertFalse(next(n for n in nodes if isinstance(n, Text) and n.content == "important").bold)

    def test_header_formatting_is_not_read(self):
        sales = next(n for n in self.doc.children if isinstance(n, Table))
        self.assertFalse(any(t.bold for c in sales.headers for t in c.children if isinstance(t, Text)))

    def test_image_is_anchored_to_its_cell(self):
        dates = [n for n in self.doc.children if isinstance(n, Table)][1]
        image = dates.rows[2].cells[2].children[0]
        self.assertIsInstance(image, Image)
        self.assertTrue(os.path.isfile(OUTPUT_DIR / image.src))

    def test_unsupported_features_are_one_warning(self):
        with patch("textconverter.parsers.xlsx_parser.log_warning") as warn:
            parse_xlsx(str(FIXTURE), write_images=False)
        warn.assert_called_once()
        self.assertIn("merged cells", warn.call_args.args[0])

    def test_images_are_ignored_without_write_images(self):
        doc = parse_xlsx(str(FIXTURE), write_images=False)
        self.assertFalse(any(isinstance(n, Image) for n in walk(doc)))

    def test_hidden_sheet_and_empty_sheet_are_skipped(self):
        wb = Workbook()
        wb.active.title = "Shown"
        wb.active.append(["a"])
        wb.create_sheet("Empty")
        wb.create_sheet("Hidden").append(["x"])
        wb["Hidden"].sheet_state = "hidden"
        doc = _parse(wb)
        self.assertEqual([type(n) for n in doc.children], [Table])

    def test_features_without_a_counterpart_are_counted(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["a", "b"])
        ws.append([1, 2])
        ws.merge_cells("A3:B3")
        ws.auto_filter.ref = "A1:B2"
        ws.conditional_formatting.add("A2", CellIsRule(operator="greaterThan", formula=["0"], font=Font(b=True)))
        with patch("textconverter.parsers.xlsx_parser.log_warning") as warn:
            _parse(wb)
        message = warn.call_args_list[0].args[0]
        for name in ("merged cells", "filters", "conditional formatting"):
            self.assertIn(name, message)

    def test_formula_without_a_stored_result_is_empty_and_reported(self):
        wb = Workbook()
        wb.active.append(["a", "b"])
        wb.active.append([2, "=A2*2"])
        with patch("textconverter.parsers.xlsx_parser.log_warning") as warn:
            doc = _parse(wb)
        self.assertEqual(_grid(doc.children[0])[1], ["2", ""])
        self.assertIn("1 formula cell", warn.call_args.args[0])
        self.assertEqual(doc.children[1].code, "B2 = A2*2")

    def test_cell_comment_on_an_empty_cell_extends_the_table(self):
        wb = Workbook()
        wb.active.append(["a"])
        wb.active["B2"].comment = Comment("hi", "me")
        table = _parse(wb).children[0]
        self.assertEqual(len(table.headers), 2)
        self.assertEqual(plain_text(table.rows[0].cells[1].children[0].content), "hi")


class TestXlsxPipeline(BaseConverterTest):
    def test_to_markdown_and_json(self):
        md = convert(str(FIXTURE), "markdown")
        self.assertIn("| Item | Qty | Price | Total |", md)
        self.assertIn("```excel", md)
        self.assertIn('"type": "Table"', convert(str(FIXTURE), "json"))

    def test_to_html_embeds_the_image(self):
        self.assertIn("data:image/png;base64", convert(str(FIXTURE), "html"))

    def test_discard_removes_the_image(self):
        self.assertNotIn("![](", convert(str(FIXTURE), "markdown", ConvertOptions(image_handling="discard")))
