# Contributing to TextConverter

## Development install

Install in editable mode via `requirements_dev.txt`. This requires [`UnifiedAiClient`](https://github.com/Kuig/UnifiedAiClient) checked out as a sibling directory (`../UnifiedAiClient`, relative to this project's root):

```powershell
pip install -r requirements_dev.txt
```

This installs both `unified_ai_client` and `textconverter` itself in editable mode, so source changes in either project are picked up immediately without reinstalling.

## Running the tests

```powershell
python -m unittest discover -s tests -p "test.py"
```
