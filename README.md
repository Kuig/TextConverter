# TextConverter

Multi-format document conversion tool with AI-powered image description and heuristic code detection.

## Overview

TextConverter converts between PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), CSV, HTML, Markdown, plain text (.txt), LaTeX, and JSON formats (JSON is the parsed document, the AST, in `.aston` files; PDF output is printed from a print version of the light HTML theme; Word, PowerPoint and Excel output are written natively; CSV and Excel carry the tables only; plain text keeps the structure (underlined headings, lists, grid tables) but no formatting; in a PDF's text layer only tables drawn with ruled lines are found). It supports:
- **URL Inputs**: Directly convert remote documents (both PDFs and HTML pages) from a remote URL.
- **HTML Content Extraction**: A zero-dependency heuristic parser to clean up webpage boilerplates (like navigation headers, footers, script, and style elements) and isolate the primary content (`<main>`, `<article>`).
- **Remote Image Downloading**: Automatically downloads and cleans remote images referenced in webpages, applying OS-safe filename sanitization and exact binary content-based deduplication to prevent duplicate copies on disk.
- **Image Description**: AI-powered classification and description of embedded images via a configurable provider (Ollama by default).
- **Code Detection**: Fast deterministic local heuristic analysis to detect and fence code blocks.
- **LaTeX Parsing**: Extracts the title block, abstract, figure and table captions and labels, and typographic quotes from LaTeX source, rendering them semantically in all output formats. Citations, cross-references and the bibliography stay LaTeX macros in every format, so they come back unchanged; `\input` files in the source's folder are included and the author's macros expanded.

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

If you want the AI to read images (any `image_handling` from `split` on, LaTeX output with `auto`, or converting image files and raster PDFs), you must install the `unified_ai_client` package:
```powershell
pip install -r requirements_prod.txt
```

### Development

For local development (editable installs, running the test suite), see [CONTRIBUTING.md](CONTRIBUTING.md).

## Configuration

`config.json` (read from the working directory, then the project root) selects the AI provider, models and prompts (`"ai"`), tunes HTML cleanup (`"html"`), and holds the provider connection settings (e.g. `"ollama"`). The default provider is a local Ollama server and needs no API key; cloud providers read their key from an environment variable.

Every field is documented in **[docs/configuration.md](docs/configuration.md)**.

## Image Handling

Two independent options decide what happens to the images of a document: `--image-handling` (API: `image_handling`) says what becomes of them in the document, `--image-output` (API: `image_output`) how the ones left are written to the output.

### What Happens to the Images

The AI models tell two kinds of image apart: *text images*, whose category is in `ai.ocr_prompts` (text, tables, formulas, page scans), which can be transcribed, and *figures*, all the others (photos, diagrams, charts, ...), which can only be described.

| `image_handling` | AI | A text image becomes | A figure becomes |
|---|---|---|---|
| `discard` | no | removed | removed |
| `keep` | no | the image | the image |
| `split` | classification, regions | the image | the image |
| `transcribe` | + OCR | its text | the image |
| `describe` | + OCR, description | its text | the image and its description |
| `replace` | + OCR, description | its text | its description |
| `append` | + OCR, description | the image and its text | the image and its description |

From `split` on, a page holding more than text (a scan, a raster PDF page, an image file) is cut into regions when `ai.region_model` is set, in reading order, and each region is treated like an image. Tables, formulas and formatting in an answer become real tables, equations and text in every format. Next to an image that stays, its text goes between `----- Start/End of picture description -----` lines, after the paragraph, table or heading when the image is in a link, a table cell or a heading; Excel output keeps it in the cell's comment, JSON output in the image's `description`. An image the AI could not process stays an image, and so does what is left out: images under `ai.min_image_pixels`, forms no model reads such as SVG, and the rest of a phase after three failed calls in a row. Images with the same content are read once. An image file or a raster PDF is the document itself, so it takes the same values, except `discard`, which raises an error (`replace` leaves the text alone). With an image file as the source and an analysis, `<output stem>_regions.png` next to the output shows what the AI found in it. To check an image classified badly inside a document, convert that image on its own.

`auto`, the default, depends on the conversion:

1. An image file or a raster PDF as the source, or LaTeX as the output: `transcribe`.
2. CSV or plain text as the output: `discard`.
3. Anything else: `keep`.

### How the Images Are Written

`embed` puts an image inside the output as a Data URL or in the file, so no image folder is left next to it. `link` references a file with a relative path; downloaded and extracted images go to a `<output stem>_images` folder.

| Output | `auto` | Available |
|---|---|---|
| HTML, JSON (`.aston`) | `embed` | `embed`, `link` |
| Markdown | `link` | `link`, `embed` |
| LaTeX | `link` | `link` |
| PDF, Word, PowerPoint, Excel | `embed` | `embed` |
| CSV, plain text | none | none |

Asking for a way the format does not offer gives a warning, and its default.

---

## HTML Extraction & Site Cleanup

`--extract-html` (API: `extract_html=True`) runs a generic pre-pass that drops noise tags (`script`, `nav`, `footer`, …), whitelists attributes, and isolates the `<main>` / `<article>` block.

On top of that, **site-specific cleanup profiles** activate automatically for pages they recognize. The only profile today is **Wikipedia** (any language edition), matched by a `*.wikipedia.org` URL or a MediaWiki fingerprint in the HTML. It removes `[edit]` links, navboxes, maintenance banners, hatnotes, the table of contents, category footers and inline `[n]` citation markers, and prunes a configurable set of end-matter sections (`See also`, `External links`, `Further reading` by default, including their known translations). The infobox, the reference list, and all images are kept: image handling stays governed by `--image-handling`.

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

# Scanned PDF: render every page and transcribe it with AI (classification, regions, then OCR or description)
textconverter convert DocsInput/scan.pdf DocsOutput/scan.md --pdf-mode raster

# Any source to Word (images embedded, equations kept as LaTeX text, real footnotes)
textconverter convert DocsInput/document.md DocsOutput/document.docx

# Any source to PowerPoint (a section is a section, a slide is a level 2 heading; footnotes become speaker notes)
textconverter convert DocsInput/document.md DocsOutput/slides.pptx

# A presentation to Markdown (text boxes become quotes that give their position on the slide and their font size)
textconverter convert DocsInput/slides.pptx DocsOutput/slides.md

# A workbook to Markdown (a heading and a table per sheet, formulas as an `excel` code block under each table)
textconverter convert DocsInput/book.xlsx DocsOutput/book.md

# The tables of any source to Excel (the heading above a table names its sheet) or to CSV (one file per table)
textconverter convert DocsInput/document.md DocsOutput/tables.xlsx
textconverter convert DocsInput/document.md DocsOutput/tables.csv

# Any source to plain text (headings underlined, tables as grids, notes at the end), and back
textconverter convert DocsInput/document.docx DocsOutput/document.txt
textconverter convert DocsInput/notes.txt DocsOutput/notes.html

# A .txt file written in Markdown
textconverter convert DocsInput/notes.txt DocsOutput/notes.html --from markdown

# Any source to PDF (printed with Edge/Chrome when installed, else a built-in renderer)
textconverter convert DocsInput/document.md DocsOutput/document.pdf

# Convert with AI image description
textconverter convert DocsInput/document.pdf DocsOutput/document.md --image-handling describe

# Convert with heuristic code detection
textconverter convert DocsInput/document.md DocsOutput/document.html --code-parsing

# Tell the source format when neither the extension nor the server's Content-Type does
textconverter convert https://example.com/export DocsOutput/export.md --from markdown
```

### MCP Server

```powershell
textconverter mcp
```

Available MCP tools:
- `textconverter_convert_text`: convert a document given as text to a target format
- `textconverter_convert_file`: convert a file or a URL to a target format
- `textconverter_save_file`: convert a file or a URL and save the result to a file

A failed conversion is returned as a tool error (`isError`) with its message.

### Streamlit GUI

```powershell
textconverter gui
textconverter gui DocsInput/document.pdf   # starts with the file as the source
```

The sidebar holds the conversion options, with one line saying what the image options come to for the paths typed, and the AI selection: a provider menu (local servers that answer and cloud providers with a key) and menus for the classification, description and OCR models, listing the models that accept images, plus a context size slider (4k to 256k tokens). **Save as default** writes the selection to `config.json` in the working directory.

### Library

```python
from textconverter import ConvertOptions, convert, convert_text, save_to_file

# Convert a file locally
result = convert("DocsInput/document.pdf", "markdown")

# Convert text you already have
html = convert_text("# Title\n\nSome *text*.", "markdown", "html")

# Convert directly from a URL and save locally, with HTML main content extraction
save_to_file("https://example.com", "DocsOutput/example.md", ConvertOptions(extract_html=True))
```

Every parameter of `convert()`, `convert_text()`, `save_to_file()` and `ConvertOptions` is documented in **[docs/api.md](docs/api.md)**.

### Windows Context Menu Integration

You can integrate `TextConverter` directly into the Windows Explorer right-click context menu. This allows you to right-click any supported file and quickly convert it to your desired format.

#### Features
* **Cascading Menu**: Adds a grouped `"Convert with TextConverter..."` menu.
* **Every conversion**: Each source offers Markdown, plain text, LaTeX, HTML (no theme, light, dark), PDF, Word, PowerPoint, Excel, CSV and AST (`.aston`, the parsed document, for debugging or for reusing it), except its own format; HTML is a target of HTML too, to clean a page up. Excel and CSV keep the tables only, and fail on a document without tables. Images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.webp`) are transcribed with the AI models of `config.json`.
* **Same behavior as the CLI**: Every conversion runs `Windows Integration/convert.cmd`, which calls `textconverter convert` with its default options (so `--image-handling auto`). PDF sources also get `--code-parsing`. If a conversion fails, the window stays open to show the error.
* **Open with TextConverter**: Opens the GUI with the file as its source, for every other option: what happens to the images, raster PDF pages, the main content of an HTML page, and so on. Explorer shows at most 16 entries of a menu, submenus included, so the menu does not hold the options itself.
* **Nothing is overwritten**: The result goes next to the source file as `<name>_converted<ext>`, then `<name>_converted2<ext>` and so on.

#### Setup
1. Open a PowerShell terminal in the project root.
2. Run the generator script:
   ```powershell
   cd "Windows Integration"
   .\generate_registry_files.ps1
   ```
   This dynamically detects the project folder and generates two registry files: `register.reg` and `unregister.reg`. Run it again (and re-import `register.reg`, which replaces the earlier entries) after moving the project or updating TextConverter.
3. Double-click `register.reg` and approve the prompt to register the context menu. On Windows 11 the entries are under **Show more options**.
4. To remove the integration, double-click `unregister.reg`.

#### GUI Launcher

A `launch_gui.bat` shortcut in the `Windows Integration/` folder activates the virtual environment and launches the Streamlit web interface with a double-click, without needing to open a terminal. Given a file (`launch_gui.bat <file>`, what **Open with TextConverter** runs), the GUI starts with it as the source.

You can also:
- Create a shortcut to `launch_gui.bat` on your Desktop or Start Menu for quick access.
- Pin it to the Start Menu or taskbar for even faster launching.

---

## Documentation

- [docs/configuration.md](docs/configuration.md): every `config.json` field.
- [docs/api.md](docs/api.md): the library functions and their parameters.
- [CHANGELOG.md](CHANGELOG.md): notable changes per release.
- [ARCHITECTURE.md](ARCHITECTURE.md): pipeline design, module map, and internal data flow.
- [CONTRIBUTING.md](CONTRIBUTING.md): development install and how to run the test suite.
