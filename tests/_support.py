"""Shared helpers for the test suite (not collected by discovery: no ``test`` prefix).

Test modules import ``setUpModule`` / ``tearDownModule`` from here so every module
runs with the silent logger, and derive their cases from ``BaseConverterTest``,
which blocks any live AI call.
"""
from __future__ import annotations

import functools
import os
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Core conversion must work without the optional AI client: stand in a mock when
# it is not installed so the lazy imports in image_describer still resolve.
try:
    import unified_ai_client  # noqa: F401
except ImportError:
    sys.modules["unified_ai_client"] = MagicMock()

import textconverter.logger as logger

TEST_DIR = Path(__file__).resolve().parent
INPUT_DIR = TEST_DIR / "Input"
OUTPUT_DIR = TEST_DIR / "Output"

_AI_ENTRY_POINTS = ("call_ai", "preload_model", "warm_up", "unload_model")


def setUpModule():
    """Silence pipeline logging for the whole module."""
    logger.set_backend("silent")


def tearDownModule():
    logger.set_backend("console")


@functools.cache
def is_connected() -> bool:
    """True if a public DNS server is reachable; probed once per test run."""
    try:
        with socket.create_connection(("8.8.8.8", 53), timeout=3):
            return True
    except OSError:
        return False


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _blocked_ai_call(*args, **kwargs):
    raise RuntimeError("live AI call attempted in an offline test")


class BaseConverterTest(unittest.TestCase):
    """Creates the output folder and blocks every live AI call.

    Conversions to LaTeX or JSON resolve ``image_handling="auto"`` to an AI
    mode, so without the block a test could load a model on a local server.
    A test that needs AI responses patches the same entry points itself; its
    patch takes precedence over this one for the duration of the test.
    """

    @classmethod
    def setUpClass(cls):
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    def setUp(self):
        for name in _AI_ENTRY_POINTS:
            patcher = patch(f"unified_ai_client.{name}", side_effect=_blocked_ai_call, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _out(self, filename: str) -> Path:
        """Return output path, deleting any existing file first."""
        p = OUTPUT_DIR / filename
        if p.exists():
            p.unlink()
        return p

    def convert_fixture(self, name: str, out_name: str, **opts) -> str:
        """Convert ``Input/<name>`` to ``Output/<out_name>`` and return the output text.

        ``opts`` are passed to ``save_to_file``; the test fails if no file is written.
        """
        from textconverter import save_to_file
        out_path = self._out(out_name)
        save_to_file(str(INPUT_DIR / name), str(out_path), **opts)
        self.assertTrue(out_path.exists(), f"{out_name} was not written")
        return read(out_path)


class FakeAi:
    """Stands in for ``call_ai``: classifies images in order, then answers per model.

    JSON-mode calls (classification) return the next category; other calls
    return the answer keyed by prompt, else by model, else "". Every
    (model, prompt) pair is recorded so tests can check routing and ordering.
    """

    def __init__(self, categories: list[str], answers: dict[str, str]):
        self.categories = iter(categories)
        self.answers = answers
        self.calls: list[tuple[str, str]] = []

    def __call__(self, **kwargs):
        self.calls.append((kwargs["model"], kwargs["prompt"]))
        if kwargs.get("format_json"):
            text = f'{{"category": "{next(self.categories)}"}}'
        else:
            text = self.answers.get(kwargs["prompt"], self.answers.get(kwargs["model"], ""))
        return MagicMock(text=text)
