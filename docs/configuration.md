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
    "prompts": { "...": "..." }
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

## `html`

| Field | Default | Meaning |
|---|---|---|
| `site_cleanup` | `true` | Whether site-specific cleanup profiles run during `--extract-html`; `--no-site-cleanup` overrides it for one run |
| `wikipedia.drop_sections` | `["see also", "external links", "further reading"]` | End-matter sections to remove. An English canonical name also removes its known translations; any other entry is matched literally, so non-English wikis can list their own titles |
| `wikipedia.drop_citation_marks` | `true` | Remove inline `[n]` citation markers |
| `wikipedia.keep_reference_list` | `true` | Keep the citation list at the end of the article |
| `wikipedia.extra_strip_selectors` | `[]` | Additional MediaWiki class names or element ids to remove |

## API keys (cloud providers)

TextConverter is Ollama-first: the default provider runs fully locally and needs no API key. If you switch `"provider"` to a cloud backend (`google`, `openai`, `anthropic`, ...), supply the key through an environment variable (`GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`). A [`secrets.json.example`](../secrets.json.example) template is provided for reference, but the app does not auto-load `secrets.json`: environment variables are the supported path.
