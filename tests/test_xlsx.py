"""Excel (.xlsx) input: the fixture Test_sheets.xlsx and workbooks built with openpyxl.

Usage: python -m unittest discover -s tests -p "test_xlsx.py"
"""
from __future__ import annotations
import datetime
import os
import tempfile
from unittest.mock import patch

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Font

import json

from textconverter import ConvertOptions, convert, convert_text, save_to_file
from textconverter.ast import CodeBlock, Document, Footnote, Heading, Image, Link, Table, Text, walk
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
        md = convert(str(FIXTURE), "markdown", output_dir=str(OUTPUT_DIR))
        self.assertIn("| Item | Qty | Price | Total |", md)
        self.assertIn("```excel", md)
        self.assertIn('"type": "Table"', convert(str(FIXTURE), "json", output_dir=str(OUTPUT_DIR)))

    def test_to_html_embeds_the_image(self):
        self.assertIn("data:image/png;base64", convert(str(FIXTURE), "html"))

    def test_discard_removes_the_image(self):
        self.assertNotIn("![](", convert(str(FIXTURE), "markdown", ConvertOptions(image_handling="discard")))


MARKDOWN = """# Sales

| Item | Qty | Total |
|---|---|---|
| Apple | 3 | 4.5 |
| Pear | 5 | 11.25 |
| **Sum** | 8 | 15.75 |

```excel
C2:C3 = B2*1.5
B4 = SUM(B2:B3)
```

Some prose that a spreadsheet cannot hold.

## Notes / 2026

| Code | When | Done | Text |
|---|---|---|---|
| 007 | 2026-10-30 | TRUE | 1,5 |
"""

ONE_TABLE = "| a |\n|---|\n| 1 |\n"


class TestXlsxRenderer(BaseConverterTest):
    def _save(self, markdown: str, name: str = "out.xlsx"):
        out = self._out(name)
        src = self._out(name + ".md")
        src.write_text(markdown, encoding="utf-8")
        save_to_file(str(src), str(out))
        return out

    def test_tables_become_sheets_named_after_their_headings(self):
        wb = load_workbook(self._save(MARKDOWN))
        self.assertEqual(wb.sheetnames, ["Sales", "Notes   2026"])

    def test_text_becomes_numbers_booleans_dates_but_only_when_exact(self):
        wb = load_workbook(self._save(MARKDOWN))
        ws = wb["Notes   2026"]
        self.assertEqual(ws["A2"].value, "007")
        self.assertEqual(ws["B2"].value, datetime.datetime(2026, 10, 30))
        self.assertIs(ws["C2"].value, True)
        self.assertEqual(ws["D2"].value, "1,5")
        self.assertEqual(wb["Sales"]["B2"].value, 3)

    def test_cells_keep_math_code_and_references(self):
        ws = load_workbook(self._save("| k | v |\n|---|---|\n| math | $x^2$ |\n| code | `abc` |\n"
                                      "| mix | val $5$ eur |\n| ref | \\ref{t} |\n")).active
        self.assertEqual([ws.cell(r, 2).value for r in range(2, 6)], ["$x^2$", "abc", "val $5$ eur", "\\ref{t}"])

    def test_header_is_bold(self):
        ws = load_workbook(self._save(MARKDOWN))["Sales"]
        self.assertTrue(ws["A1"].font.b)
        self.assertTrue(ws["A4"].font.b)
        self.assertFalse(ws["A2"].font.b)

    def test_formulas_are_written_with_their_stored_result(self):
        path = self._save(MARKDOWN)
        formulas, values = load_workbook(path)["Sales"], load_workbook(path, data_only=True)["Sales"]
        self.assertEqual([formulas["C2"].value, formulas["C3"].value, formulas["B4"].value],
                         ["=B2*1.5", "=B3*1.5", "=SUM(B2:B3)"])
        self.assertEqual([values["C2"].value, values["C3"].value, values["B4"].value], [4.5, 11.25, 8])

    def test_prose_is_dropped_and_no_table_is_an_error(self):
        wb = load_workbook(self._save(MARKDOWN))
        self.assertEqual(wb["Sales"].max_row, 4)
        with self.assertRaises(ValueError):
            self._save("# Only text\n\nNo table here.\n", "none.xlsx")
        self.assertFalse(self._out("none.xlsx").exists())

    def test_two_tables_under_one_heading_get_distinct_sheets(self):
        wb = load_workbook(self._save(f"# Data\n\n{ONE_TABLE}\n{ONE_TABLE}"))
        self.assertEqual(wb.sheetnames, ["Data", "Data (2)"])

    def test_comment_link_and_rich_text(self):
        from textconverter.renderers.xlsx_renderer import render_xlsx
        out = self._out("rich.xlsx")
        render_xlsx(parse_xlsx(str(FIXTURE), write_images=False), str(out))
        wb = load_workbook(out, rich_text=True)
        self.assertIn("Fresh", wb["Sales"]["A2"].comment.text)
        self.assertEqual(wb["Sales"]["A3"].hyperlink.target, "https://example.com")
        rich = wb["Dates"]["C2"].value
        self.assertEqual([getattr(p, "text", p) for p in rich], ["very ", "important"])

    def test_metadata_goes_to_the_file_properties(self):
        md = '---\ntitle: "Book"\nauthor: "Ada"\ndate: "2026-03-04"\n---\n\n' + ONE_TABLE
        props = load_workbook(self._save(md)).properties
        self.assertEqual((props.title, props.creator, props.created.date().isoformat()), ("Book", "Ada", "2026-03-04"))

    def test_round_trip_is_identical(self):
        options = ConvertOptions(image_handling="discard")
        out = self._out("roundtrip.xlsx")
        save_to_file(str(FIXTURE), str(out), options)
        self.assertEqual(json.loads(convert(str(out), "json", options)),
                         json.loads(convert(str(FIXTURE), "json", options)))

    def test_images_are_embedded_by_default_and_survive_the_round_trip(self):
        out = self._out("images.xlsx")
        save_to_file(str(FIXTURE), str(out))
        self.assertFalse(self._out("images_images").exists())
        self.assertEqual(len(load_workbook(out)["Dates"]._images), 1)

    def test_markdown_image_reference_is_anchored_to_its_cell(self):
        src = INPUT_DIR / "tmp_img_table.md"
        src.write_text("| a |\n|---|\n| ![x](OcrText.png) |\n", encoding="utf-8")
        try:
            out = self._out("md_image.xlsx")
            save_to_file(str(src), str(out))
        finally:
            src.unlink()
        self.assertEqual(len(load_workbook(out)["Sheet1"]._images), 1)

    def test_xlsx_is_not_a_text_output(self):
        with self.assertRaises(ValueError):
            convert_text(ONE_TABLE, "markdown", "xlsx")

    def test_csv_to_xlsx_and_back(self):
        out, back = self._out("data.xlsx"), self._out("data.csv")
        save_to_file(str(INPUT_DIR / "Test_data.csv"), str(out))
        save_to_file(str(out), str(back))
        self.assertEqual(back.read_bytes().decode("utf-8-sig"),
                         'Name,Qty,Note\r\nApple,3,"two\nlines"\r\nPear,5,\r\n')
