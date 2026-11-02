"""The Streamlit GUI, run headless with streamlit.testing; provider and model lists are faked.

Usage: python -m unittest discover -s tests -p "test_gui.py"
"""
from __future__ import annotations
import sys
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
          _Info(id="gemma4:12b", file_types=frozenset({"image"}), embeddings=False),
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
                         ["gemma4:e2b", "gemma4:12b", "glm-ocr:latest"])

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


    def _with_paths(self, source: str, output: str) -> AppTest:
        """The app after typing the two paths."""
        st.cache_data.clear()
        with patch("unified_ai_client.list_providers", return_value=PROVIDERS), \
             patch("unified_ai_client.list_models", return_value=MODELS):
            app = AppTest.from_file(APP, default_timeout=30)
            app.run()
            app.text_input(key="source").input(source)
            app.text_input(key="output").input(output)
            app.run()
        self.assertFalse(app.exception, app.exception)
        return app

    def _note(self, app: AppTest) -> str:
        return next((c.value for c in app.sidebar.caption if "paths" in c.value or "discard" in c.value), "")

    def test_image_menus_offer_every_value_with_a_label(self):
        app = self._run()
        self.assertIn("Text only: transcriptions and descriptions", self._selectbox(app, "Image handling").options)
        self.assertEqual(self._selectbox(app, "Image output").options,
                         ["Automatic", "Embedded in the output", "Linked files"])

    def test_without_the_client_only_what_needs_no_model_is_offered(self):
        with patch.dict(sys.modules, {"unified_ai_client": None}):
            app = AppTest.from_file(APP, default_timeout=30)
            app.run()
        self.assertFalse(app.exception, app.exception)
        self.assertEqual(self._selectbox(app, "Image handling").options, ["Automatic", "Remove images", "Keep images"])

    def test_image_output_is_off_when_the_format_has_one_way(self):
        for output, disabled in (("out.docx", True), ("out.tex", True), ("out.csv", True), ("out.html", False),
                                 ("out.md", False), ("out", False)):
            with self.subTest(output=output):
                app = self._with_paths("in.md", output)
                self.assertEqual(self._selectbox(app, "Image output").disabled, disabled)

    def test_the_note_says_what_automatic_means_here(self):
        self.assertIn("transcribe text, keep figures; images: linked files", self._note(self._with_paths("in.md", "o.tex")))
        self.assertIn("keep images; images: embedded", self._note(self._with_paths("in.md", "o.json")))
        self.assertIn("transcribe text", self._note(self._with_paths("in.png", "o.md")))
        self.assertIn("this format holds none", self._note(self._with_paths("in.md", "o.csv")))

    def test_no_note_until_the_paths_tell_the_formats(self):
        self.assertEqual(self._note(self._run()), "")

    def test_a_refused_choice_is_flagged_before_converting(self):
        st.cache_data.clear()
        with patch("unified_ai_client.list_providers", return_value=PROVIDERS), \
             patch("unified_ai_client.list_models", return_value=MODELS):
            app = AppTest.from_file(APP, default_timeout=30)
            app.run()
            app.text_input(key="source").input("in.png")
            app.text_input(key="output").input("out.md")
            self._selectbox(app, "Image handling").set_value("discard")
            app.run()
        self.assertIn("Cannot discard", self._note(app))

    def test_the_chosen_image_options_reach_the_conversion(self):
        st.cache_data.clear()
        with patch("unified_ai_client.list_providers", return_value=PROVIDERS), \
             patch("unified_ai_client.list_models", return_value=MODELS), \
             patch("textconverter.api.save_to_file") as save:
            app = AppTest.from_file(APP, default_timeout=30)
            app.run()
            app.text_input(key="source").input("in.md")
            app.text_input(key="output").input("out.html")
            app.run()
            self._selectbox(app, "Image handling").set_value("append")
            self._selectbox(app, "Image output").set_value("link")
            next(b for b in app.button if b.label == "Convert").click()
            app.run()
        self.assertFalse(app.exception, app.exception)
        options = save.call_args.args[2]
        self.assertEqual((options.image_handling, options.image_output), ("append", "link"))

    def test_a_format_with_one_way_gets_auto_whatever_the_menu_shows(self):
        st.cache_data.clear()
        with patch("unified_ai_client.list_providers", return_value=PROVIDERS), \
             patch("unified_ai_client.list_models", return_value=MODELS), \
             patch("textconverter.api.save_to_file") as save:
            app = AppTest.from_file(APP, default_timeout=30)
            app.run()
            app.text_input(key="source").input("in.md")
            app.text_input(key="output").input("out.html")
            app.run()
            self._selectbox(app, "Image output").set_value("link")
            app.text_input(key="output").input("out.docx")
            app.run()
            next(b for b in app.button if b.label == "Convert").click()
            app.run()
        self.assertEqual(save.call_args.args[2].image_output, "auto")

    def test_site_cleanup_default_follows_config(self):
        """html.site_cleanup = false in config.json unticks the checkbox (it was always ticked)."""
        st.cache_data.clear()
        cfg = AppConfig()
        cfg.html.site_cleanup = False
        with patch("unified_ai_client.list_providers", return_value=PROVIDERS),              patch("unified_ai_client.list_models", return_value=MODELS),              patch("textconverter.config.load_config", side_effect=lambda: cfg):
            app = AppTest.from_file(APP, default_timeout=30)
            app.run()
        box = next(c for c in app.sidebar.checkbox if c.label.startswith("Site-specific cleanup"))
        self.assertFalse(box.value)


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
