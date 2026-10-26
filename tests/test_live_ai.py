"""Live checks against the AI provider configured in config.json (Ollama by default).

Skipped unless the environment variable TEXTCONVERTER_LIVE_AI is set to 1 and
the provider answers. Kept light on purpose: a handful of sequential calls on
small fixture images, no load or stress testing.

Usage (PowerShell):
    $env:TEXTCONVERTER_LIVE_AI=1; python -m unittest discover -s tests -p "test_live_ai.py"
"""
from __future__ import annotations
import os
import unittest
import urllib.request
from unittest.mock import patch

from textconverter.ast import Document, Image, Paragraph, Table
from textconverter.config import load_config
from _support import INPUT_DIR, setUpModule, tearDownModule

LIVE_ENV = "TEXTCONVERTER_LIVE_AI"
FIXTURES = {name: str(INPUT_DIR / name) for name in
            ("Foto.jpg", "OcrText.png", "OcrTable.png", "OcrFormula.png")}


def _provider_answers(config) -> bool:
    """True when the configured Ollama server responds (other providers are assumed up)."""
    if config.ai.provider != "ollama":
        return True
    url = config.providers.get("ollama", {}).get("url", "http://localhost:11434")
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=3):
            return True
    except OSError:
        return False


class LiveAiTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if os.environ.get(LIVE_ENV) != "1":
            raise unittest.SkipTest(f"set {LIVE_ENV}=1 to run live AI tests")
        cls.config = load_config()
        if not _provider_answers(cls.config):
            raise unittest.SkipTest(f"AI provider '{cls.config.ai.provider}' is not reachable")
        from textconverter.image_describer import init_ai
        init_ai(cls.config)

    def _ocr(self, fixture: str, category: str) -> str:
        from textconverter.image_describer import _ask
        ai = self.config.ai
        if not ai.ocr_model:
            self.skipTest("no ocr_model configured")
        answer = _ask(ai.ocr_model, ai.ocr_prompts[category], FIXTURES[fixture], self.config,
                      temperature=ai.ocr_temperature)
        self.assertTrue(answer, f"{ai.ocr_model} returned nothing for {fixture}")
        return answer


class TestLiveClassification(LiveAiTest):

    def test_every_fixture_gets_a_known_category(self):
        from textconverter.image_describer import _classify
        ai = self.config.ai
        known = set(ai.prompts) | set(ai.ocr_prompts)
        results = {name: _classify(path, self.config) for name, path in FIXTURES.items()}
        for name, category in results.items():
            self.assertIn(category, known, f"{name}: {results}")
            self.assertNotEqual(category, "default", f"{name} was not classified: {results}")


class TestLiveOcr(LiveAiTest):

    def test_table_becomes_table_node(self):
        from textconverter.parsers.transcription_parser import parse_transcription
        answer = self._ocr("OcrTable.png", "table")
        nodes = parse_transcription(answer).children
        self.assertTrue(any(isinstance(n, Table) for n in nodes), answer)

    def test_formula_becomes_equation(self):
        from textconverter.parsers.transcription_parser import equation_code
        answer = self._ocr("OcrFormula.png", "formula")
        code = equation_code(answer, bare_is_formula=True)
        self.assertTrue(code and "sqrt" in code, answer)

    def test_text_is_transcribed(self):
        answer = self._ocr("OcrText.png", "text")
        self.assertIn("Lorem ipsum dolor sit amet", answer)


class TestLivePhases(LiveAiTest):

    def test_each_model_is_preloaded_once(self):
        """A document with every fixture loads each configured model at most once."""
        from unified_ai_client import preload_model
        from textconverter.image_describer import process_images
        images = [Image(src=p) for p in FIXTURES.values()]
        doc = Document(children=[Paragraph(children=[img]) for img in images])
        with patch("unified_ai_client.preload_model", wraps=preload_model) as spy:
            process_images(doc, "", config=self.config)
        preloaded = [c.args[1] for c in spy.call_args_list]
        self.assertEqual(len(preloaded), len(set(preloaded)), preloaded)
        summary = {img.src: (img.category, img.description) for img in images}
        self.assertTrue(all(img.description for img in images), summary)
