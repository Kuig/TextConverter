"""HTML parsing: structure, tables with spans, main-content extraction.

Usage: python -m unittest discover -s tests -p "test_html.py"
"""
from __future__ import annotations

import textconverter
from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR, read


class TestHtmlParser(BaseConverterTest):

    def test_sample_html_to_markdown(self):
        """SampleHtml.htm → MD: text content, lists, table, links survive parsing."""
        in_path = INPUT_DIR / "SampleHtml.htm"
        out_path = self._out("SampleHtml.md")

        textconverter.save_to_file(str(in_path), str(out_path))
        self.assertTrue(out_path.exists())

        content = read(out_path)
        # Headings
        self.assertIn("Titolo di Livello 1", content, "Missing h1 content")
        self.assertIn("Sottotitolo di Livello 2", content, "Missing h2 content")
        # Table content
        self.assertIn("Mario Rossi", content, "Missing table row content")
        self.assertIn("Laura Bianchi", content, "Missing table row content")
        # List items
        self.assertIn("grassetto", content, "Missing list item content")
        self.assertIn("corsivo", content, "Missing list item content")
        # Link preserved
        self.assertIn("https://www.google.it", content, "Missing hyperlink")

    def test_html_table_colspan_rowspan(self):
        """HTML colspan/rowspan flatten to a rectangular grid in every target."""
        import json as _json
        html = (
            "<table><tbody>"
            "<tr><td rowspan='2'>ID</td><td colspan='2'>Group</td><td rowspan='2'>Tail</td></tr>"
            "<tr><td>G1</td><td>G2</td></tr>"
            "<tr><td>1</td><td><div>Left</div><div>Right</div></td><td>x</td><td>y</td></tr>"
            "</tbody></table>"
        )

        def _data_rows(md_text):
            return [l for l in md_text.splitlines()
                    if l.strip().startswith("|") and set(l.strip()) - set("|-: ")]

        md = textconverter.convert(html, to_format="markdown", from_format="html")
        rows = _data_rows(md)
        self.assertEqual(len({l.count("|") for l in rows}), 1, f"ragged markdown table: {rows}")
        self.assertIn("Left Right", md, "adjacent <div> cell text glued together")
        self.assertNotIn("LeftRight", md)

        # extract_html path strips unknown attrs; colspan/rowspan must survive it too.
        md_x = textconverter.convert(html, to_format="markdown", from_format="html", extract_html=True)
        self.assertEqual(len({l.count("|") for l in _data_rows(md_x)}), 1, "ragged table after extract_html")

        tex = textconverter.convert(html, to_format="latex", from_format="html")
        body = [l for l in tex.splitlines() if l.rstrip().endswith("\\\\") and "&" in l]
        self.assertTrue(body)
        self.assertEqual(len({l.count("&") for l in body}), 1, f"ragged latex table: {body}")

        ast = textconverter.convert(html, to_format="json", from_format="html")
        self.assertNotIn("_colspan", ast)
        self.assertNotIn("_rowspan", ast)
        table = _json.loads(ast)["children"][0]
        self.assertEqual({len(r["cells"]) for r in table["rows"]}, {4})

    def test_main_content_extraction(self):
        """MainContentTest.html → MD with extract_html=True: only main block, no nav/footer."""
        in_path = INPUT_DIR / "MainContentTest.html"
        out_path = self._out("MainContentTest.md")

        textconverter.save_to_file(str(in_path), str(out_path), extract_html=True)
        self.assertTrue(out_path.exists())

        content = read(out_path)
        self.assertIn("Main Title", content, "Missing main content title")
        self.assertIn("This is the main content.", content, "Missing main content paragraph")
        self.assertNotIn("Footer info", content, "Footer should be stripped")
        self.assertNotIn("Home", content, "Nav should be stripped")
