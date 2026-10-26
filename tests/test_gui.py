"""The Streamlit GUI, run headless with streamlit.testing; provider and model lists are faked.

Usage: python -m unittest discover -s tests -p "test_gui.py"
"""
from __future__ import annotations
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from _support import BaseConverterTest, setUpModule, tearDownModule

APP = str(Path(__file__).resolve().parent.parent / "textconverter" / "gui" / "app.py")


class _Info:
    """Minimal stand-in for ProviderInfo / ModelInfo."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


PROVIDERS = [_Info(name="ollama", file_types=frozenset({"image"})),
             _Info(name="script", file_types=frozenset())]
MODELS = [_Info(id="gemma4:e2b", file_types=frozenset({"image"}), embeddings=False),
          _Info(id="glm-ocr:latest", file_types=frozenset({"image"}), embeddings=False),
          _Info(id="embed:1b", file_types=frozenset(), embeddings=True)]


class TestGui(BaseConverterTest):

    def _run(self, providers=PROVIDERS, models=MODELS) -> AppTest:
        st.cache_data.clear()  # the provider/model lists are cached across runs
        with patch("unified_ai_client.list_providers", return_value=providers), \
             patch("unified_ai_client.list_models", return_value=models):
            app = AppTest.from_file(APP, default_timeout=30)
            app.run()
        self.assertFalse(app.exception, app.exception)
        return app

    def _selectbox(self, app: AppTest, label: str):
        return next(s for s in app.sidebar.selectbox if s.label == label)

    def test_menus_offer_image_capable_choices(self):
        """Only image-capable providers and non-embedding models are offered."""
        app = self._run()
        self.assertEqual(self._selectbox(app, "Provider").options, ["ollama"])
        self.assertEqual(self._selectbox(app, "Description model").options,
                         ["gemma4:e2b", "glm-ocr:latest"])

    def test_plain_ollama_name_matches_latest_tag(self):
        """config.json's 'glm-ocr' selects the listed 'glm-ocr:latest' without a warning."""
        app = self._run()
        self.assertEqual(self._selectbox(app, "OCR model").value, "glm-ocr:latest")
        self.assertFalse([c for c in app.sidebar.caption if "not offered" in c.value])

    def test_unavailable_provider_stays_selected_with_warning(self):
        """A configured provider that is not running stays selected, flagged in a caption."""
        app = self._run(providers=[])
        self.assertEqual(self._selectbox(app, "Provider").value, "ollama")
        self.assertTrue([c for c in app.sidebar.caption if "not available now" in c.value])


class TestFileDialog(BaseConverterTest):
    """ask_path() runs the dialog in a child process, faked here."""

    def _ask(self, stdout: str):
        from textconverter.gui.file_dialog import ask_path
        fake = type("Done", (), {"stdout": stdout})()
        with patch("textconverter.gui.file_dialog.subprocess.run", return_value=fake) as run:
            return ask_path("DocsInput/a.pdf", [("PDF Files", "*.pdf")]), run

    def test_path_inside_cwd_becomes_relative(self):
        chosen, run = self._ask(str(Path.cwd() / "DocsInput" / "b.pdf"))
        self.assertEqual(chosen, "DocsInput/b.pdf")
        self.assertIn("-c", run.call_args.args[0])

    def test_cancel_returns_none(self):
        self.assertIsNone(self._ask("")[0])
