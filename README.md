# TextConverter

Multi-format document conversion tool with AI-powered image description and heuristic code detection.

## Overview

TextConverter converts between PDF, HTML, Markdown, LaTeX, and JSON formats. It supports:
- **URL Inputs**: Directly convert remote documents (both PDFs and HTML pages) from a remote URL.
- **HTML Content Extraction**: A zero-dependency heuristic parser to clean up webpage boilerplates (like navigation headers, footers, script, and style elements) and isolate the primary content (`<main>`, `<article>`).
- **Remote Image Downloading**: Automatically downloads and cleans remote images referenced in webpages, applying OS-safe filename sanitization and exact binary content-based deduplication to prevent duplicate copies on disk.
- **Image Description**: AI-powered classification and description of embedded images via Ollama.
- **Code Detection**: Fast deterministic local heuristic analysis to detect and fence code blocks in Markdown output.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install .
```

### Optional AI Support (Ollama via UnifiedAiClient)

Core conversion features (such as Markdown, HTML, LaTeX, PDF, and heuristic code detection) run locally without any external AI dependencies.

If you want to use AI-powered image descriptions (`image_handling="describe"`, `image_handling="auto_latex"` or converting standalone image inputs), you must install the `unified_ai_client` package:
```powershell
pip install -r requirements_prod.txt
```

## Configuration

`config.json` at the project root controls Ollama model selection, prompts, and URL:

```json
{
    "ollama": {
        "url": "http://localhost:11434",
        "classification_model": "gemma4:e2b",
        "description_model": "gemma4:e2b"
    }
}
```

## Image Handling

The `--image-handling` option (or the `image_handling` parameter in the API) determines how images in the source document are processed and rendered.

### Supported Strategies

* **`describe`**: AI-powered analysis and description. Traverses the document, classifies each image, and runs category-specific prompts (via local Ollama models) to generate detailed textual descriptions or transcription tables. The description is embedded in the output.
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
  - The system utilizes the vision AI model (via Ollama) to classify the image.
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

## Project Structure

```
TextConverter/
├── config.json              ← Ollama configuration
├── pyproject.toml           ← Packaging and project setup
├── requirements_dev.txt     ← Development dependencies
├── requirements_prod.txt    ← Production dependencies
├── test.py                  ← Local test and validation script
├── README.md
├── DocsInput/               ← Sample input documents
├── DocsOutput/              ← Generated output documents
└── textconverter/           ← Core package
    ├── __init__.py          ← Package initializer
    ├── __main__.py          ← CLI entry point (convert / mcp / gui subcommands)
    ├── api.py               ← Public API: convert(), save_to_file()
    ├── ast.py               ← Document AST node definitions
    ├── code_detector.py     ← Heuristic code block detection
    ├── image_describer.py   ← AI-assisted image classification + description
    ├── logger.py            ← Dual-backend logger (console / Streamlit)
    ├── mcp_tools.py         ← MCP tool definitions
    ├── parsers/             ← Format-specific parsers
    ├── renderers/           ← Format-specific renderers
    └── gui/                 ← Streamlit user interface
        └── app.py           ← Streamlit web interface entrypoint
```
