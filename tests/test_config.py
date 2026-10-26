"""Loading and saving config.json.

Usage: python -m unittest discover -s tests -p "test_config.py"
"""
from __future__ import annotations
import json
from pathlib import Path

from textconverter.config import AppConfig
from _support import BaseConverterTest, OUTPUT_DIR, setUpModule, tearDownModule

PROJECT_CONFIG = Path(__file__).resolve().parent.parent / "config.json"


class TestConfigSave(BaseConverterTest):

    def test_save_round_trips_every_section(self):
        """save() then load() gives back the same ai, html and provider settings."""
        config = AppConfig.load(PROJECT_CONFIG)
        config.ai.ocr_model = "some-ocr"
        target = config.save(OUTPUT_DIR / "config_roundtrip.json")
        reloaded = AppConfig.load(target)
        self.assertEqual(reloaded, config)

    def test_committed_config_is_in_saved_layout(self):
        """config.json is byte-for-byte what save() writes, so saving from the GUI diffs cleanly."""
        target = AppConfig.load(PROJECT_CONFIG).save(OUTPUT_DIR / "config_layout.json")
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                         json.loads(PROJECT_CONFIG.read_text(encoding="utf-8")))
        self.assertEqual(target.read_bytes().replace(b"\r\n", b"\n"),
                         PROJECT_CONFIG.read_bytes().replace(b"\r\n", b"\n"))


class TestConfigLoad(BaseConverterTest):

    def _load(self, data) -> AppConfig:
        path = OUTPUT_DIR / "config_load_test.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return AppConfig.load(path)

    def test_default_providers_are_not_shared(self):
        """Changing one config's provider block (the GUI does) leaves the defaults intact."""
        AppConfig().providers["ollama"]["context_size"] = 1
        self.assertNotEqual(AppConfig().providers["ollama"]["context_size"], 1)
        loaded = self._load({"ai": {}})
        loaded.providers["ollama"]["url"] = "changed"
        self.assertNotEqual(AppConfig().providers["ollama"]["url"], "changed")

    def test_nested_sections_and_unknown_keys(self):
        """Every section, nested ones included, keeps known keys and reports the rest."""
        from unittest.mock import patch
        with patch("textconverter.config.log_warning") as warn:
            cfg = self._load({"ai": {"ocr_model": "x", "bogus": 1},
                              "html": {"site_cleanup": False, "wikipedia": {"drop_citation_marks": False, "nope": 2}}})
        self.assertEqual(cfg.ai.ocr_model, "x")
        self.assertFalse(cfg.html.site_cleanup)
        self.assertFalse(cfg.html.wikipedia.drop_citation_marks)
        messages = " ".join(c.args[0] for c in warn.call_args_list)
        self.assertIn("'ai' section: bogus", messages)
        self.assertIn("'html.wikipedia' section: nope", messages)

    def test_malformed_section_falls_back_to_defaults(self):
        from unittest.mock import patch
        with patch("textconverter.config.log_warning") as warn:
            cfg = self._load({"html": {"wikipedia": ["see also"]}})
        self.assertEqual(cfg.html.wikipedia, AppConfig().html.wikipedia)
        warn.assert_called_once()

    def test_provider_settings(self):
        cfg = AppConfig()
        self.assertEqual(cfg.provider_settings()["url"], "http://localhost:11434")
        self.assertEqual(cfg.provider_settings("google"), {})
