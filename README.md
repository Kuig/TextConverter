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
git clone https://github.com/Kuig/TextConverter.git
cd TextConverter
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

### Development

For local development (editable installs, running the test suite), see [CONTRIBUTING.md](CONTRIBUTING.md).

## Configuration

`config.json` (read from the working directory, then the project root) selects the AI provider, models and prompts (`"ai"`), tunes HTML cleanup (`"html"`), and holds the provider connection settings (e.g. `"ollama"`). The default provider is a local Ollama server and needs no API key; cloud providers read their key from an environment variable.

Every field is documented in **[docs/configuration.md](docs/configuration.md)**.

## Image Handling

The `--image-handling` option (or the `image_handling` parameter in the API) determines how images in the source document are processed and rendered.

### Supported Strategies

* **`describe`**: AI-powered analysis and description. Classifies every image, then describes photos, diagrams, charts and the like with the description model, and transcribes text, tables, formulas and page scans with the OCR model (GLM-OCR by default; without one, the description model transcribes them). The calls are grouped by model, so each model is loaded once per conversion. The description is embedded in the output.
* **`embed`**: Base64 inline embedding. Reads local or downloaded images from disk, guesses their MIME types, and encodes their binary data into inline Data URLs (`data:image/...;base64,...`). Perfect for creating self-contained documents (like HTML).
* **`link`**: File-based referencing. Preserves or downloads images, sanitizing their filenames, and references them using standard relative paths (`![alt](path)` in Markdown, `<img>` in HTML, `\includegraphics{...}` in LaTeX). No AI processing is executed.
* **`discard`**: Total removal. Strips all `Image` nodes from the AST, omitting them entirely from the final rendered output.
* **`auto_latex`** (internal): Hybrid mode designed for LaTeX/JSON, used automatically by `auto` for those formats (see below). Traverses the document and uses Ollama to classify and transcribe only text/table/formula images (rendering the text inline); for drawings, photos, or diagrams, it skips the description to save resources and falls back to rendering standard graphics references. It is not an explicit `--image-handling` CLI choice, and its behavior may change, so avoid setting it directly through the API/MCP `image_handling` parameter.

### The `auto` Strategy (`image_handling="auto"`)

When set to `auto` (the default), the tool dynamically maps the strategy based on the target output format (`to_format`):

* **HTML output (`to_format="html"`)**: Resolves to **`embed`**.
  - Local or downloaded images are read from disk, their MIME types are guessed (defaulting to `image/png`), and their binary content is base64-encoded.
  - The image source path is rewritten to an inline Data URL (`data:image/...;base64,...`), embedding the image directly inside the self-contained HTML file.

* **LaTeX output (`to_format="latex"`)**: Resolves to **`auto_latex`**.
  - The system utilizes the vision AI model to classify the image.
  - If the image is classified as `text`, `table` or `formula`, the AI transcribes it. The transcript is rendered as text inline (a formula becomes an equation), and `render_metadata` is set to `False` to prevent the raw LaTeX image reference from compiling.
  - If the image is classified as any other type (e.g., diagrams or photos), the AI description is skipped to conserve resources, and standard `\includegraphics{...}` markup is rendered.

* **Markdown output (`to_format="markdown"`)**: Resolves to **`link`**.
  - Local or downloaded images are referenced via standard relative paths.
  - The images are rendered as standard Markdown image syntax: `![alt_text](path/to/image "optional_title")`. No description generation is performed.

* **JSON output (`to_format="json"`)**: Resolves to **`auto_latex`**.
  - Like the LaTeX mode, it runs image classification and transcribes only text, tables, and formulas, populating the `description` and `category` fields in the resulting JSON AST structure.

---

## HTML Extraction & Site Cleanup

`--extract-html` (API: `extract_html=True`) runs a generic pre-pass that drops noise tags (`script`, `nav`, `footer`, …), whitelists attributes, and isolates the `<main>` / `<article>` block.

On top of that, **site-specific cleanup profiles** activate automatically for pages they recognize. The only profile today is **Wikipedia** (any language edition), matched by a `*.wikipedia.org` URL or a MediaWiki fingerprint in the HTML. It removes `[edit]` links, navboxes, maintenance banners, hatnotes, the table of contents, category footers and inline `[n]` citation markers, and prunes a configurable set of end-matter sections (`See also`, `External links`, `Further reading` by default, including their known translations). The infobox, the reference list, and all images are kept — image handling stays governed by `--image-handling`.

- Turn site profiles off for one run with `--no-site-cleanup` (API: `site_cleanup=False`); the run then behaves like plain `--extract-html`.
- Change the default, or tune the Wikipedia profile, in the `"html"` section of `config.json` (see [docs/configuration.md](docs/configuration.md#html)). Non-English wikis can add their own section titles to `drop_sections`.

`--discard-links` (API: `discard_links=True`) is independent of HTML extraction and of the source format: it replaces every hyperlink with its visible text (a link wrapping an image keeps the image).

## Usage

### CLI

```powershell
# Convert a PDF to Markdown
textconverter convert DocsInput/document.pdf DocsOutput/document.md

# Convert directly from a URL (downloads and converts PDF or HTML webpage)
textconverter convert https://example.com DocsOutput/example.md

# Convert a webpage with clean HTML content extraction (strips noise, isolates main body)
textconverter convert https://example.com DocsOutput/example.md --extract-html

# Wikipedia article: --extract-html also runs the Wikipedia cleanup profile automatically
textconverter convert https://en.wikipedia.org/wiki/Modena DocsOutput/modena.md --extract-html
#   ...add --no-site-cleanup to fall back to generic extraction, or --discard-links to drop hyperlinks

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
- `textconverter_convert_text`: convert text or a file to a target format
- `textconverter_save_file`: convert and save a document to a file

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

#### API Reference

```python
def convert(
    source: str,
    to_format: str,
    from_format: str | None = None,
    template: str = "plain",
    is_file: bool = False,
    output_dir: str | None = None,
    image_dir_name: str | None = None,
    image_handling: str = "auto",
    code_parsing: bool = False,
    extract_html: bool = False,
    discard_links: bool = False,
    site_cleanup: bool | None = None,
    config: AppConfig | None = None,
) -> str:
    """Convert text or a file to a specific format and return the result as a string."""
```
- `source`: File path, remote URL (`http://`/`https://`), or raw text content.
- `to_format`: Target format: `"markdown"`, `"html"`, `"latex"`, or `"json"`.
- `from_format`: Source format hint (`"pdf"`, `"markdown"`, `"html"`, `"latex"`, `"json"`, `"image"`). Inferred from the file/URL extension when omitted; required when `source` is raw text with no extension to infer from.
- `template`: HTML rendering template (see [renderers/templates.py](textconverter/renderers/templates.py)): `"plain"`, `"light-theme"`, or `"dark-theme"`.
- `is_file`: Treat `source` as a file path rather than raw text.
- `output_dir` / `image_dir_name`: Base directory and subdirectory name used to write downloaded/extracted images.
- `image_handling`: `"auto"` (default, format-dependent), `"describe"`, `"embed"`, `"link"`, or `"discard"` (see [Image Handling](#image-handling)). `"auto_latex"` is also accepted, as the internal fallback `auto` uses on LaTeX/JSON output, but it's not meant to be set directly since its behavior may change.
- `code_parsing`: Enable heuristic code-block detection (Markdown/HTML sources).
- `extract_html`: Strip boilerplate and isolate main content when parsing HTML.
- `discard_links`: Replace every hyperlink with its visible text (any source format).
- `site_cleanup`: Override for site-specific HTML cleanup during `extract_html`. `None` uses the `html.site_cleanup` config default; `False` disables it for this call.
- `config`: A `textconverter.config.AppConfig` to use instead of `config.json` (e.g. `load_config()` with the AI provider or models changed).

```python
def save_to_file(
    source: str,
    output_path: str,
    template: str = "plain",
    image_handling: str = "auto",
    code_parsing: bool = False,
    extract_html: bool = False,
    discard_links: bool = False,
    site_cleanup: bool | None = None,
    config: AppConfig | None = None,
) -> None:
    """Convert and write the result directly to output_path (format inferred from its extension)."""
```
Same semantics as `convert()`, but infers both `to_format` (from `output_path`'s extension) and `is_file=True`, and writes the result to disk instead of returning it.

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

#### GUI Launcher

A `launch_gui.bat` shortcut in the `Windows Integration/` folder activates the virtual environment and launches the Streamlit web interface with a double-click, without needing to open a terminal.

You can also:
- Create a shortcut to `launch_gui.bat` on your Desktop or Start Menu for quick access.
- Pin it to the Start Menu or taskbar for even faster launching.

---

## Documentation

- [docs/configuration.md](docs/configuration.md): every `config.json` field.
- [CHANGELOG.md](CHANGELOG.md): notable changes per release.
- [ARCHITECTURE.md](ARCHITECTURE.md): pipeline design, module map, and internal data flow.
- [CONTRIBUTING.md](CONTRIBUTING.md): development install and how to run the test suite.
