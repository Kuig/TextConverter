# TextConverter

Multi-format document conversion tool with AI-powered image description and heuristic code detection.

## Overview

TextConverter converts between PDF, HTML, Markdown, LaTeX, and JSON formats. It supports:
- **URL Inputs**: Directly convert remote documents (both PDFs and HTML pages) from a remote URL.
- **HTML Content Extraction**: A zero-dependency heuristic parser to clean up webpage boilerplates (like navigation headers, footers, script, and style elements) and isolate the primary content (`<main>`, `<article>`).
- **Remote Image Downloading**: Automatically downloads and cleans remote images referenced in webpages, applying OS-safe filename sanitization and exact binary content-based deduplication to prevent duplicate copies on disk.
- **Image Description**: AI-powered classification and description of embedded images via a configurable provider (Ollama by default).
- **Code Detection**: Fast deterministic local heuristic analysis to detect and fence code blocks.
- **LaTeX Parsing**: Extracts document title, abstract, and typographic quotes from LaTeX source, rendering them semantically in all output formats.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install .
```

### Optional AI Support

Core conversion features (such as Markdown, HTML, LaTeX, PDF, and heuristic code detection) run locally without any external AI dependencies.

If you want to use AI-powered image descriptions (`image_handling="describe"`, `image_handling="auto_latex"` or converting standalone image inputs), you must install the `unified_ai_client` package:
```powershell
pip install -r requirements_prod.txt
```

## Configuration

`config.json` at the project root is split into two sections:

- **`"ai"`** — TextConverter application-level settings: which provider to use, model names, prompts, and token budgets.
- **`"<provider>"`** — Provider connection settings passed directly to `unified_ai_client` (URL, timeout, context size, etc.).

```json
{
  "ai": {
    "provider": "ollama",
    "classification_model": "gemma4:12b",
    "description_model": "gemma4:12b",
    "classification_visual_token_budget": 70,
    "description_visual_token_budget": 1120,
    "provide_extracted_text_to_describer": true,
    "classification_prompt": "...",
    "prompts": { "...": "..." }
  },
  "ollama": {
    "url": "http://localhost:11434",
    "timeout": 300,
    "keep_alive": "15m",
    "context_size": 8192
  }
}
```

The `"ai"` section is provider-agnostic: switching to a different backend only requires changing `"provider"` and adding the corresponding connection block (e.g. `"google"`, `"openai"`).

Configuration is resolved in priority order: **CWD** → package root → built-in defaults. This means you can place a local `config.json` in your working directory to override the project-level settings without modifying the package.

### API Keys (Cloud Providers)

The default provider (Ollama) runs fully locally and needs no API key. If you switch `"provider"` to a cloud backend (`google`, `openai`, `anthropic`, ...), copy [`secrets.json.example`](secrets.json.example) to `secrets.json` at the project root and fill in the relevant key — this file is git-ignored. Environment variables (e.g. `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) are also supported and take priority over `secrets.json`.

## Image Handling

The `--image-handling` option (or the `image_handling` parameter in the API) determines how images in the source document are processed and rendered.

### Supported Strategies

* **`describe`**: AI-powered analysis and description. Traverses the document, classifies each image, and runs category-specific prompts (via the configured AI provider) to generate detailed textual descriptions or transcription tables. The description is embedded in the output.
* **`embed`**: Base64 inline embedding. Reads local or downloaded images from disk, guesses their MIME types, and encodes their binary data into inline Data URLs (`data:image/...;base64,...`). Perfect for creating self-contained documents (like HTML).
* **`link`**: File-based referencing. Preserves or downloads images, sanitizing their filenames, and references them using standard relative paths (`![alt](path)` in Markdown, `<img>` in HTML, `\includegraphics{...}` in LaTeX). No AI processing is executed.
* **`discard`**: Total removal. Strips all `Image` nodes from the AST, omitting them entirely from the final rendered output.
* **`auto_latex`**: Hybrid mode designed for LaTeX/JSON. Traverses the document and uses Ollama to classify and transcribe only text/table/formula images (rendering the text inline). For drawings, photos, or diagrams, it skips the description to save resources and falls back to rendering standard graphics references.

### The `auto` Strategy (`image_handling="auto"`)

When set to `auto` (the default), the tool dynamically maps the strategy based on the target output format (`to_format`):

* **HTML output (`to_format="html"`)**: Resolves to **`embed`**.
  - Local or downloaded images are read from disk, their MIME types are guessed (defaulting to `image/png`), and their binary content is base64-encoded.
  - The image source path is rewritten to an inline Data URL (`data:image/...;base64,...`), embedding the image directly inside the self-contained HTML file.

* **LaTeX output (`to_format="latex"`)**: Resolves to **`auto_latex`**.
  - The system utilizes the vision AI model to classify the image.
  - If the image is classified as `short_text_table_or_formula` (e.g., a math equation, transcription, or raw inline data), the AI transcribes it. The transcript is rendered as text inline, and `render_metadata` is set to `False` to prevent the raw LaTeX image reference from compiling.
  - If the image is classified as any other type (e.g., diagrams or photos), the AI description is skipped to conserve resources, and standard `\includegraphics{...}` markup is rendered.

* **Markdown output (`to_format="markdown"`)**: Resolves to **`link`**.
  - Local or downloaded images are referenced via standard relative paths.
  - The images are rendered as standard Markdown image syntax: `![alt_text](path/to/image "optional_title")`. No description generation is performed.

* **JSON output (`to_format="json"`)**: Resolves to **`auto_latex`**.
  - Like the LaTeX mode, it runs image classification and transcribes only text, tables, and formulas using the vision model, populating the `description` and `category` fields in the resulting JSON AST structure.

---

## Usage

### CLI

```powershell
# Convert a PDF to Markdown
textconverter convert DocsInput/document.pdf DocsOutput/document.md

# Convert directly from a URL (downloads and converts PDF or HTML webpage)
textconverter convert https://example.com DocsOutput/example.md

# Convert a webpage with clean HTML content extraction (strips noise, isolates main body)
textconverter convert https://example.com DocsOutput/example.md --extract-html

# Convert with AI image description
textconverter convert DocsInput/document.pdf DocsOutput/document.md --image-handling describe

# Convert with heuristic code detection
textconverter convert DocsInput/document.md DocsOutput/document.html --code-parsing
```

### MCP Server

```powershell
textconverter mcp
```

Available MCP tools:
- `textconverter_convert_text` — convert text or a file to a target format
- `textconverter_save_file` — convert and save a document to a file

### Streamlit GUI

```powershell
textconverter gui
```

### Library

```python
from textconverter.api import convert, save_to_file

# Convert a file locally
result = convert("DocsInput/document.pdf", to_format="markdown", is_file=True)

# Convert directly from a URL and save locally, with HTML main content extraction
save_to_file(
    "https://example.com", 
    "DocsOutput/example.md", 
    extract_html=True
)
```

### Windows Context Menu Integration

You can integrate `TextConverter` directly into the Windows Explorer right-click context menu. This allows you to right-click any supported file and quickly convert it to your desired format.

#### Features
* **Cascading Menu**: Adds a grouped `"Convert with TextConverter..."` menu.
* **Extension Filtering**: Only shows relevant options:
  * **PDFs**: Shows all output options (.md, .tex, light/dark HTML).
  * **Markdown / LaTeX**: Excludes self-conversion (e.g., no "convert to .md" option for `.md` files). Code detection is disabled for these source types (they are already structured text).
  * **HTML / HTM**: Includes duplicate options for "main content" extraction (`--extract-html` to filter out boilerplate).
  * **Images** (`.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.webp`): Automatically runs with AI image description (`image_handling="describe"`).
* **Smart Defaults**: Executes with `--code-parsing` enabled for all source types except Markdown and LaTeX.

#### Setup
1. Open a PowerShell terminal in the project root.
2. Run the generator script:
   ```powershell
   cd "Windows Integration"
   .\generate_registry_files.ps1
   ```
   This dynamically detects your Python virtual environment path and generates two registry files: `register.reg` and `unregister.reg`.
3. Double-click `register.reg` and approve the prompt to register the context menu.
4. To remove the integration, double-click `unregister.reg`.

---

## Project Structure

```
TextConverter/
├── config.json              ← AI provider and app-level configuration
├── pyproject.toml           ← Packaging and project setup
├── requirements_dev.txt     ← Development dependencies
├── requirements_prod.txt    ← Production dependencies (includes unified_ai_client)
├── test.py                  ← Local test and validation script
├── README.md
├── DocsInput/               ← Sample input documents
├── DocsOutput/              ← Generated output documents
├── Windows Integration/     ← Windows shell context menu integration
│   └── generate_registry_files.ps1  ← Dynamic registry file generator
└── textconverter/           ← Core package
    ├── __init__.py          ← Package initializer
    ├── __main__.py          ← CLI entry point (convert / mcp / gui subcommands)
    ├── api.py               ← Public API: convert(), save_to_file()
    ├── ast.py               ← Document AST node definitions
    ├── code_detector.py     ← Heuristic code block detection
    ├── config.py            ← Configuration loading and provider setup helpers
    ├── image_describer.py   ← AI-assisted image classification + description
    ├── logger.py            ← Dual-backend logger (console / Streamlit)
    ├── mcp_tools.py         ← MCP tool definitions
    ├── parsers/             ← Format-specific parsers
    ├── renderers/           ← Format-specific renderers
    └── gui/                 ← Streamlit user interface
        └── app.py           ← Streamlit web interface entrypoint
```
