"""Live downloads from public URLs; skipped when offline.

Usage: python -m unittest discover -s tests -p "test_remote.py"
"""
from __future__ import annotations
import os
import shutil
import unittest

import textconverter
from _support import BaseConverterTest, setUpModule, tearDownModule, OUTPUT_DIR, is_connected, read


class TestRemoteIntegration(BaseConverterTest):

    @classmethod
    def setUpClass(cls):
        if not is_connected():
            raise unittest.SkipTest("No internet connection available")
        super().setUpClass()

    def test_remote_bread_link(self):
        """Remote URL → MD with image_handling=link: output and image folder created."""
        out_path = self._out("Pane.md")
        img_dir = OUTPUT_DIR / "Pane_images"
        if img_dir.exists():
            shutil.rmtree(img_dir)

        textconverter.save_to_file(
            "https://daginoilbonaparte.it/blog-di-cucina/ricetta-pane-impasta/",
            str(out_path),
            image_handling="link",
            code_parsing=True,
            extract_html=False
        )
        self.assertTrue(out_path.exists(), "Output markdown file not created")
        self.assertTrue(img_dir.exists(), "Image directory was not created")
        self.assertGreater(len(os.listdir(img_dir)), 0, "Image directory is empty")

    def test_remote_bread_discard(self):
        """Remote URL → MD with image_handling=discard: output created, no image folder."""
        out_path = self._out("Pane_discard.md")
        img_dir = OUTPUT_DIR / "Pane_discard_images"
        if img_dir.exists():
            shutil.rmtree(img_dir)

        textconverter.save_to_file(
            "https://daginoilbonaparte.it/blog-di-cucina/ricetta-pane-impasta/",
            str(out_path),
            image_handling="discard",
            code_parsing=True,
            extract_html=True
        )
        self.assertTrue(out_path.exists(), "Output markdown file not created")
        self.assertFalse(img_dir.exists(), "Image directory should NOT be created with discard")

    def test_remote_wikipedia_swish(self):
        """Wikipedia Swish function → HTML: output created, contains expected content."""
        out_path = self._out("Swish.html")

        textconverter.save_to_file(
            "https://en.wikipedia.org/wiki/Swish_function",
            str(out_path),
            image_handling="discard",
            code_parsing=True,
            extract_html=True,
            template="light"
        )
        self.assertTrue(out_path.exists(), "Output HTML file not created")
        content = read(out_path)
        self.assertIn("Swish", content, "Expected 'Swish' keyword not found in output")
        # Wikipedia cleanup profile ran: chrome should be gone.
        self.assertNotIn("[edit]", content, "Section edit links not stripped")
        self.assertNotIn("Retrieved from", content, "Category/footer chrome not stripped")
