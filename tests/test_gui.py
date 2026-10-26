"""The Streamlit GUI, run headless with streamlit.testing; provider and model lists are faked.

Usage: python -m unittest discover -s tests -p "test_gui.py"
"""
from __future__ import annotations
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from textconverter.config import AppConfig

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

    def test_context_size_slider_offers_standard_sizes(self):
        """The slider starts at the provider's context_size and steps through 4k..256k."""
        config = AppConfig(providers={"ollama": {"context_size": 8192}})
        with patch("textconverter.config.load_config", return_value=config):
            slider = self._run().sidebar.select_slider[0]
        self.assertEqual(slider.value, 8192)
        self.assertEqual(slider.options, ["4k", "8k", "16k", "32k", "64k", "128k", "256k"])

    def test_off_scale_context_size_stays_selected_with_warning(self):
        """A configured size that is not a standard step is kept and flagged in a caption."""
        config = AppConfig(providers={"ollama": {"context_size": 10000}})
        with patch("textconverter.config.load_config", return_value=config):
            app = self._run()
        self.assertEqual(app.sidebar.select_slider[0].value, 10000)
        self.assertTrue([c for c in app.sidebar.caption if "not one of the standard sizes" in c.value])

    def test_chosen_context_size_reaches_conversion(self):
        """Convert passes the slider value in the provider block of the config override."""
        st.cache_data.clear()
        with patch("unified_ai_client.list_providers", return_value=PROVIDERS), \
             patch("unified_ai_client.list_models", return_value=MODELS), \
             patch("textconverter.config.load_config", side_effect=lambda: AppConfig()), \
             patch("textconverter.api.save_to_file") as save:
            app = AppTest.from_file(APP, default_timeout=30)
            app.run()
            app.sidebar.select_slider[0].set_value(32768)
            app.text_input(key="source").input("in.md")
            app.text_input(key="output").input("out.md")
            next(b for b in app.button if b.label == "Convert").click()
            app.run()
        self.assertFalse(app.exception, app.exception)
        self.assertEqual(save.call_args.kwargs["config"].providers["ollama"]["context_size"], 32768)


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


class TestStreamlitLogger(BaseConverterTest):

    def test_messages_are_escaped(self):
        """A log message with markup (a URL, an exception text) is shown, not interpreted."""
        import textconverter.logger as logger
        self.addCleanup(logger.set_backend, "silent")
        with patch("streamlit.markdown") as markdown:
            logger.set_backend("streamlit")
            logger.log_warning('Failed <img src="x"> & co')
        html = markdown.call_args.args[0]
        self.assertIn("&lt;img src=&quot;x&quot;&gt; &amp; co", html)
