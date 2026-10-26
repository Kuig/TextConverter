# Configuration

TextConverter reads `config.json` from the **current working directory**, falling back to the package root, then to built-in defaults, so the app always starts. Place a local `config.json` in your working directory to override the project-level settings without modifying the package.

`config.json` holds no secrets and is committed: it doubles as its own example.

## `config.json`

```json
{
  "ai": {
    "provider": "ollama",
    "classification_model": "gemma4:e2b",
    "description_model": "gemma4:e2b",
    "classification_visual_token_budget": 70,
    "description_visual_token_budget": 1120,
    "provide_extracted_text_to_describer": true,
    "classification_prompt": "...",
    "prompts": { "...": "..." },
    "ocr_model": "glm-ocr",
    "ocr_prompts": {
      "text": "Text Recognition:",
      "table": "Table Recognition:",
      "formula": "Formula Recognition:",
      "document_scan": "Text Recognition:"
    },
    "classification_temperature": 0,
    "ocr_temperature": 0
  },
  "html": {
    "site_cleanup": true,
    "wikipedia": {
      "drop_sections": ["see also", "external links", "further reading"],
      "drop_citation_marks": true,
      "keep_reference_list": true,
      "extra_strip_selectors": []
    }
  },
  "ollama": {
    "url": "http://localhost:11434",
    "timeout": 300,
    "keep_alive": "15m",
    "context_size": 4096
  }
}
```

The file is split into three kinds of section:

- **`"ai"`**: application-level AI settings: which provider to use, model names, prompts, and token budgets. It is provider-agnostic: switching backend only requires changing `"provider"` and adding the matching connection block (e.g. `"google"`, `"openai"`).
- **`"html"`**: HTML input handling.
- **`"<provider>"`**: connection settings passed directly to `unified_ai_client` (URL, timeout, keep-alive, context size, ...). Their schema is owned by `unified_ai_client`.

## `ai`

| Field | Default | Meaning |
|---|---|---|
| `provider` | `"ollama"` | AI provider name, as known to `unified_ai_client` |
| `classification_model` | `"gemma4:e2b"` | Vision model that assigns each image a category |
| `description_model` | `"gemma4:e2b"` | Vision model that describes or transcribes each image |
| `classification_visual_token_budget` | `70` | Visual tokens for the classification call; `0` leaves the model default |
| `description_visual_token_budget` | `1120` | Visual tokens for the description call; `0` leaves the model default |
| `provide_extracted_text_to_describer` | `false` | Append the text extracted from a vector image to the description prompt |
| `classification_prompt` | built-in | Prompt asking for a JSON object `{"category": ...}` |
| `prompts` | built-in | Description prompt per category, plus `default` |
| `ocr_model` | `""` | Model that transcribes the categories listed in `ocr_prompts` (e.g. `"glm-ocr"`); empty means the description model transcribes them with their `prompts` entry |
| `ocr_prompts` | `text`, `table`, `formula`, `document_scan` | OCR task prompt per category; its keys decide which categories are transcribed instead of described |
| `classification_temperature` | `0` | Sampling temperature of the classification call; `null` leaves the model default |
| `ocr_temperature` | `0` | Sampling temperature of the OCR call; `null` leaves the model default |

Images are processed in three phases, one model each: every image is classified, then the non-OCR categories are described, then the OCR categories are transcribed. Each model is therefore loaded once per conversion, and an OCR model can sit next to the vision model without swapping on every image.

The categories are `photo_drawing_or_comic`, `diagram`, `text`, `table`, `formula`, `chart`, `infographic_or_depliant`, `document_scan`, `logo_or_icon` and `map`. An answer outside `prompts` and `ocr_prompts` falls back to `default`.

## `html`

| Field | Default | Meaning |
|---|---|---|
| `site_cleanup` | `true` | Whether site-specific cleanup profiles run during `--extract-html`; `--no-site-cleanup` overrides it for one run |
| `wikipedia.drop_sections` | `["see also", "external links", "further reading"]` | End-matter sections to remove. An English canonical name also removes its known translations; any other entry is matched literally, so non-English wikis can list their own titles |
| `wikipedia.drop_citation_marks` | `true` | Remove inline `[n]` citation markers |
| `wikipedia.keep_reference_list` | `true` | Keep the citation list at the end of the article |
| `wikipedia.extra_strip_selectors` | `[]` | Additional MediaWiki class names or element ids to remove |

## Saving from the GUI

The GUI starts from `config.json` and offers the provider and the three models as menus. **Save as default** writes the whole configuration, with the chosen provider and models, to `config.json` in the **working directory** (never into the installed package), in the same layout as the committed file, so the change shows up as a small diff.

## API keys (cloud providers)

TextConverter is Ollama-first: the default provider runs fully locally and needs no API key. If you switch `"provider"` to a cloud backend (`google`, `openai`, `anthropic`, ...), supply the key through an environment variable (`GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`). Conversions read the key from the environment only. The GUI provider menu, which asks `unified_ai_client` which providers are usable, also reads a `secrets.json` in the working directory (see [`secrets.json.example`](../secrets.json.example)), so cloud providers with a key there are offered too.
