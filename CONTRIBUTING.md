# Contributing to TextConverter

## Development install

Install in editable mode via `requirements_dev.txt`. This requires [`UnifiedAiClient`](https://github.com/Kuig/UnifiedAiClient) checked out as a sibling directory (`../UnifiedAiClient`, relative to this project's root):

```powershell
pip install -r requirements_dev.txt
```

This installs both `unified_ai_client` and `textconverter` itself in editable mode, so source changes in either project are picked up immediately without reinstalling.

## Running the tests

```powershell
python -m unittest discover -s tests                         # full suite
python -m unittest discover -s tests -p "test_latex.py"      # one file
python -m unittest discover -s tests -k abstract_roundtrip   # tests whose name contains the text
```

Tests live in `tests/test_<area>.py`, with shared helpers in `tests/_support.py`. They need neither a network nor an AI server: every AI call is mocked or blocked, and `test_remote.py` skips itself when offline. Fixtures are in `tests/Input/`; outputs go to `tests/Output/` (gitignored).

`tests/test_live_ai.py` checks classification, GLM-OCR transcription and the phase order against the provider in `config.json`. It is skipped unless you opt in, and needs the configured models installed:

```powershell
$env:TEXTCONVERTER_LIVE_AI=1; python -m unittest discover -s tests -p "test_live_ai.py"
```
