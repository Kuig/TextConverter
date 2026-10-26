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
