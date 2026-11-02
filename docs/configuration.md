# Configuration

TextConverter reads `config.json` from the **current working directory**, falling back to the package root, then to built-in defaults, so the app always starts. Place a local `config.json` in your working directory to override the project-level settings without modifying the package.

Loading is tolerant: a missing key takes its default, and an unknown key, or a section that is not a JSON object, is reported as a warning and ignored (the section then takes its defaults).

`config.json` holds no secrets and is committed: it doubles as its own example.

## `config.json`

```json
{
  "ai": {
    "provider": "ollama",
    "classification_model": "gemma4:e2b",
    "description_model": "gemma4:e2b",
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
    "ocr_temperature": 0,
    "description_thinking": false,
    "description_context": 500,
    "min_image_pixels": 1024,
    "description_max_tokens": 4096,
    "ocr_max_tokens": 4096,
    "region_model": "gemma4:12b",
    "region_prompt": "...",
    "region_max_tokens": 1500
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
    "timeout": 600,
    "keep_alive": "15m",
    "context_size": 8192
  }
}
```

The file is split into three kinds of section:

- **`"ai"`**: application-level AI settings: which provider to use, model names, and prompts. It is provider-agnostic: switching backend only requires changing `"provider"` and adding the matching connection block (e.g. `"google"`, `"openai"`).
- **`"html"`**: HTML input handling.
- **`"<provider>"`**: connection settings passed directly to `unified_ai_client` (URL, timeout, keep-alive, context size, ...). Their schema is owned by `unified_ai_client`.

## `ai`

| Field | Default | Meaning |
|---|---|---|
| `provider` | `"ollama"` | AI provider name, as known to `unified_ai_client` |
| `classification_model` | `"gemma4:e2b"` | Vision model that assigns each image a category |
| `description_model` | `"gemma4:e2b"` | Vision model that describes or transcribes each image |
| `provide_extracted_text_to_describer` | `false` | Append the text extracted from a vector image to the description prompt |
| `classification_prompt` | built-in | Prompt asking for a JSON object `{"category": ...}` |
| `prompts` | built-in | Description prompt per category, plus `default` |
| `ocr_model` | `""` | Model that transcribes the categories listed in `ocr_prompts` (e.g. `"glm-ocr"`); empty means the description model transcribes them with their `prompts` entry |
| `ocr_prompts` | `text`, `table`, `formula`, `document_scan` | OCR task prompt per category; its keys decide which categories are transcribed instead of described |
| `classification_temperature` | `0` | Sampling temperature of the classification call; `null` leaves the model default |
| `ocr_temperature` | `0` | Sampling temperature of the OCR call; `null` leaves the model default |
| `description_thinking` | `false` | Leave thinking to the model in description calls; every other image call has it off |
| `description_context` | `500` | Characters of text around an image given to the description call, per side; `0` turns it off |
| `min_image_pixels` | `1024` | Width times height under which an image of a document is left out of the analysis; `0` turns it off |
| `description_max_tokens` | `4096` | Limit of a description, thinking included; `null` means no limit |
| `ocr_max_tokens` | `4096` | Limit of a transcription; `null` means no limit |
| `region_model` | `"gemma4:12b"` | Vision model that labels the blocks of a page; empty turns regions off |
| `region_prompt` | built-in | Prompt asking for a JSON object from tile number to label; `{count}` becomes the number of tiles |
| `region_max_tokens` | `1500` | Limit of the labelling answer; `null` means no limit |

Images are processed in phases, one model each: every image is classified, then pages are split into regions, then the non-OCR categories are described, then the OCR categories are transcribed. Models therefore swap between phases and never image by image, so an OCR model can sit next to the vision model. Before that, the images of a document under `min_image_pixels` (32 by 32 by default: tracking pixels and icons) and those in a form no model reads (SVG, EMF, WMF, anything Pillow cannot open) are left out and stay as they are; an image that is the source itself is always read. Three failed calls in a row, an empty answer included, stop a phase and leave the rest as images; a stopped classification ends the analysis. Each of those calls has the provider's own retries behind it.

A description is told what surrounds its image, so that the model can recognize what a picture alone does not say: the document's title, the section, and `description_context` characters of text on each side, a caption included. On a split page that text is the transcription of the page, so the OCR phase runs before the descriptions; with the same model for labels and descriptions this costs one more swap, and `description_context: 0` avoids it.

A page is an image classified as `text` or `document_scan`. Its blocks are found with Pillow, and a page of plain text stops there, with no model involved. Otherwise `region_model` labels the blocks, shown to it as numbered tiles on one contact sheet, and a page with more than one kind of content is split: each run of text, table, formula and figure is then treated as `image_handling` says. Any failure leaves the page whole. Locating content is left to Pillow because the small vision models place boxes too loosely to crop from. The labels need a model of at least the size of `gemma4:12b`: `gemma4:e2b` answers with text copied from the tiles. Thinking stays off in the labelling call, where it can use up the token limit before any answer.

With Ollama, the resolution at which Gemma 4 reads an image is chosen by the server from the image's size; it cannot be configured.

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

The GUI starts from `config.json` and offers the provider and the three models as menus, and the provider's `context_size` as a slider (4k, 8k, ... 256k tokens). The context window holds both the image and the answer: a full page sent to the OCR model takes several thousand tokens, so a window that is too small truncates the transcription. **Save as default** writes the whole configuration, with the chosen provider, models and context size, to `config.json` in the **working directory** (never into the installed package), in the same layout as the committed file, so the change shows up as a small diff.

## API keys (cloud providers)

TextConverter is Ollama-first: the default provider runs fully locally and needs no API key. If you switch `"provider"` to a cloud backend (`google`, `openai`, `anthropic`, ...), supply the key through an environment variable (`GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`). Conversions read the key from the environment only. The GUI provider menu, which asks `unified_ai_client` which providers are usable, also reads a `secrets.json` in the working directory (see [`secrets.json.example`](../secrets.json.example)), so cloud providers with a key there are offered too.
