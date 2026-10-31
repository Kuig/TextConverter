"""CSV input and output: delimiters, encodings, one file per table.

Usage: python -m unittest discover -s tests -p "test_csv.py"
"""
from __future__ import annotations
import os
import tempfile
from unittest.mock import patch

from textconverter import ConvertOptions, convert, convert_text, save_to_file
from textconverter.ast import Document, Footnote, Heading, Image, Table, TableCell, TableRow, Text
from textconverter.formats import OUTPUT_FORMATS, infer_input_format, infer_input_format_from_media_type
from textconverter.parsers.csv_parser import parse_csv
from textconverter.renderers._common import plain_text
from textconverter.renderers.csv_renderer import render_csv, render_csv_files
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR  # noqa: F401


def _table(*rows: list[str]) -> Table:
    cells = [[TableCell([Text(v)] if v else []) for v in row] for row in rows]
    return Table(headers=cells[0], rows=[TableRow(r) for r in cells[1:]])


def _grid(table: Table) -> list[list[str]]:
    return [[plain_text(c.children) for c in row] for row in [table.headers, *(r.cells for r in table.rows)]]


class TestCsvParser(BaseConverterTest):
    def test_first_row_is_the_header(self):
        table = parse_csv("a,b\n1,2\n3,4\n").children[0]
        self.assertEqual(_grid(table), [["a", "b"], ["1", "2"], ["3", "4"]])

    def test_delimiter_is_detected(self):
        for sep in (";", "\t", "|"):
            with self.subTest(sep=sep):
                table = parse_csv(f"a{sep}b\n1{sep}2\n").children[0]
                self.assertEqual(_grid(table), [["a", "b"], ["1", "2"]])

    def test_quotes_and_newlines_in_cells(self):
        table = parse_csv('a,b\n"x, y","line1\nline2"\n').children[0]
        self.assertEqual(_grid(table)[1], ["x, y", "line1\nline2"])

    def test_ragged_rows_are_padded_and_trailing_blank_rows_dropped(self):
        table = parse_csv("a,b,c\n1\n\n,,\n").children[0]
        self.assertEqual(_grid(table), [["a", "b", "c"], ["1", "", ""]])

    def test_empty_text_has_no_table(self):
        self.assertEqual(parse_csv("  \n").children, [])

    def test_bom_is_ignored(self):
        self.assertEqual(_grid(parse_csv("﻿a,b\n1,2").children[0])[0], ["a", "b"])


class TestCsvRenderer(BaseConverterTest):
    def test_first_table_with_crlf(self):
        text = render_csv(Document([_table(["a", "b"], ["1", "x,y"])]))
        self.assertEqual(text, 'a,b\r\n1,"x,y"\r\n')

    def test_footnotes_and_images_are_dropped(self):
        cell = TableCell([Text("v"), Footnote([Text("note")]), Image("x.png")])
        table = Table(headers=[TableCell([Text("h")])], rows=[TableRow([cell])])
        self.assertEqual(render_csv(Document([table])), "h\r\nv\r\n")

    def test_no_table_raises(self):
        with self.assertRaises(ValueError):
            render_csv(Document([Heading(1, [Text("x")])]))

    def test_one_file_per_table_named_after_the_heading(self):
        doc = Document([Heading(1, [Text("Sales/2026")]), _table(["a"], ["1"]),
                        Heading(1, [Text("Costs")]), _table(["b"], ["2"])])
        self.assertEqual([s for s, _ in render_csv_files(doc)], ["_Sales 2026", "_Costs"])
        self.assertEqual(render_csv_files(Document([_table(["a"])]))[0][0], "")


class TestCsvPipeline(BaseConverterTest):
    def test_formats(self):
        self.assertEqual(infer_input_format("a.TSV"), "csv")
        self.assertEqual(infer_input_format_from_media_type("text/csv"), "csv")
        self.assertEqual(OUTPUT_FORMATS["csv"].auto_images, "discard")

    def test_csv_to_markdown(self):
        md = convert(str(INPUT_DIR / "Test_data.csv"), "markdown")
        self.assertIn("| Name | Qty | Note |", md)
        self.assertIn("Apple", md)

    def test_markdown_to_csv_text(self):
        md = "# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        self.assertEqual(convert_text(md, "markdown", "csv"), "a,b\r\n1,2\r\n")

    def test_cells_keep_math_code_and_references(self):
        md = ("| k | v |\n|---|---|\n| math | $x^2$ |\n| code | `abc` |\n| mix | val $5$ eur |\n"
              "| ref | see \\ref{t} and \\cite{key} |\n")
        self.assertEqual(convert_text(md, "markdown", "csv"),
                         "k,v\r\nmath,$x^2$\r\ncode,abc\r\nmix,val $5$ eur\r\nref,see \\ref{t} and \\cite{key}\r\n")

    def test_a_footnote_in_a_cell_stays_out(self):
        md = "| k |\n|---|\n| a\\footnote{note `x`} |\n"
        self.assertEqual(convert_text(md, "markdown", "csv"), "k\r\na\r\n")

    def test_no_table_explains_the_cause(self):
        with self.assertRaisesRegex(ValueError, "no table to write"):
            convert_text("no table here", "markdown", "csv")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.pdf")
            with patch("textconverter.api.parse_pdf", return_value=Document()):
                with open(path, "wb") as f:
                    f.write(b"%PDF-1.7")
                with self.assertRaisesRegex(ValueError, "pdf_mode 'raster'"):
                    convert(path, "csv")
                with self.assertRaisesRegex(ValueError, "did not transcribe"):
                    convert(path, "csv", ConvertOptions(pdf_mode="raster"))

    def test_cp1252_file_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.csv")
            with open(path, "wb") as f:
                f.write("name,city\nJosé,Zürich\n".encode("cp1252"))
            self.assertIn("Zürich", convert(path, "markdown"))

    def test_save_writes_one_file_per_table(self):
        md = "# Sales\n\n| a |\n|---|\n| 1 |\n\n# Costs\n\n| b |\n|---|\n| 2 |\n"
        with tempfile.TemporaryDirectory() as tmp:
            src, out = os.path.join(tmp, "in.md"), os.path.join(tmp, "out.csv")
            with open(src, "w", encoding="utf-8") as f:
                f.write(md)
            written = save_to_file(src, out, ConvertOptions())
            self.assertEqual(sorted(os.listdir(tmp)), ["in.md", "out_Costs.csv", "out_Sales.csv"])
            self.assertEqual(sorted(os.path.basename(p) for p in written), ["out_Costs.csv", "out_Sales.csv"])
            with open(os.path.join(tmp, "out_Sales.csv"), "rb") as f:
                self.assertEqual(f.read(), b"\xef\xbb\xbfa\r\n1\r\n")

    def test_save_single_table_keeps_the_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.csv")
            self.assertEqual(save_to_file(str(INPUT_DIR / "Test_data.csv"), out), [out])
            self.assertEqual(os.listdir(tmp), ["out.csv"])
