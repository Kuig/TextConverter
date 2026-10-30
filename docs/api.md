# Library API

The functions live in `textconverter.api` and, with `ConvertOptions`, are also exported by the `textconverter` package. The CLI, the MCP tools and the GUI are thin wrappers around them.

```python
from textconverter import ConvertOptions, convert, convert_text, save_to_file

md = convert("DocsInput/document.pdf", "markdown")
html = convert_text("# Title", "markdown", "html", ConvertOptions(template="dark"))
save_to_file("https://example.com", "DocsOutput/example.md", ConvertOptions(extract_html=True))
```

## `ConvertOptions`

```python
@dataclass
class ConvertOptions:
    template: str = "plain"
    image_handling: str = "auto"
    code_parsing: bool = False
    extract_html: bool = False
    discard_links: bool = False
    site_cleanup: bool | None = None
    pdf_mode: str = "text"
```
How a document is converted. Values are checked on creation: an unknown `template`, `image_handling` or `pdf_mode` raises `ValueError` before any download or AI call. The accepted values are listed in `textconverter.formats`.

- `template`: HTML template: `"plain"`, `"light"` (also `"light-theme"`, `"pretty"`) or `"dark"` (also `"dark-theme"`). Used for HTML output.
- `image_handling`: `"auto"` (default, format-dependent), `"describe"`, `"embed"`, `"link"` or `"discard"` (see the README's [Image Handling](../README.md#image-handling)). `"auto_latex"` is also accepted, as the mode `auto` uses on LaTeX/JSON output, but it's not meant to be set directly since its behavior may change.
- `code_parsing`: Enable heuristic code-block detection (Markdown sources, and PDF sources in text mode).
- `extract_html`: Strip boilerplate and isolate main content when parsing HTML.
- `discard_links`: Replace every hyperlink with its visible text (any source format).
- `site_cleanup`: Override for site-specific HTML cleanup during `extract_html`. `None` uses the `html.site_cleanup` config default; `False` disables it for this call.
- `pdf_mode`: How PDF input is read. `"text"` (default) uses the text layer; `"raster"` renders every page at 200 DPI and sends it through the AI image pipeline (each page is classified, then transcribed by the OCR model or described), for scans or PDFs whose text layer is unusable. In raster mode `image_handling` only applies to pages that could not be transcribed, which are kept as images.

## `convert()`

```python
def convert(
    source: str,
    to_format: str,
    options: ConvertOptions | None = None,
    *,
    from_format: str | None = None,
    output_dir: str | None = None,
    image_dir_name: str | None = None,
    config: AppConfig | None = None,
) -> str:
```
Convert a file or a remote URL and return the result as a string.

- `source`: A file path, or an `http://`/`https://` URL. A path that does not exist raises `FileNotFoundError`.
- `to_format`: `"markdown"`, `"html"`, `"latex"` or `"json"` (PDF and Word output go through `save_to_file()`).
- `from_format`: `"markdown"`, `"html"`, `"latex"`, `"json"`, `"pdf"`, `"docx"` or `"image"`. Inferred when omitted: from the file extension (`.txt` is read as Markdown); for a URL, from the response's `Content-Type`, then the URL's extension, else HTML. A downloaded text page is decoded with the charset of its `Content-Type` or `<meta charset>`, else UTF-8.
- A URL that cannot be downloaded raises `textconverter._net.DownloadError` (a `RuntimeError`).
- `output_dir` / `image_dir_name`: Base directory and subdirectory name used to write downloaded and extracted images. Image paths in the result are relative to `output_dir` (to the source's folder when it is None), so local images referenced by a source in another folder still resolve.
- `config`: A `textconverter.config.AppConfig` to use instead of `config.json` (e.g. `load_config()` with the AI provider or models changed).

## `convert_text()`

```python
def convert_text(
    text: str,
    from_format: str,
    to_format: str,
    options: ConvertOptions | None = None,
    *,
    output_dir: str | None = None,
    image_dir_name: str | None = None,
    config: AppConfig | None = None,
) -> str:
```
Convert a document given as text. `from_format` is required and must be a text format (`"markdown"`, `"html"`, `"latex"`, `"json"`); the text is never read as a file path, even when it names an existing file. Other parameters as in `convert()`.

## `save_to_file()`

```python
def save_to_file(
    source: str,
    output_path: str,
    options: ConvertOptions | None = None,
    *,
    from_format: str | None = None,
    config: AppConfig | None = None,
) -> None:
```
Convert a file or URL like `convert()` and write the result to `output_path`. The output format comes from its extension (`.md`, `.html`, `.tex`, `.json`, `.pdf`, `.docx`); images go to a `<output stem>_images` folder next to it, unless they are embedded (`embed`, or `auto` for HTML, PDF and Word), which leaves no folder. An output path that is the source file itself raises `ValueError`.

A `.pdf` output path renders the document as HTML with the light theme and prints it: with a headless Edge, Chrome or Chromium when one is installed (full styling, formulas typeset by MathJax when online), otherwise with PyMuPDF's built-in layout engine (simpler styling, formulas shown as TeX). `template` is ignored, and images are embedded in the PDF (`auto` and `link` act as `embed`).

A `.docx` output path writes the document with python-docx (A4, the built-in Word styles): headings, formatting, links, nested lists (each list counts from its own start), quotes, code (style `Code`), tables with a header row, auto-numbered captions (`SEQ` fields), images (embedded; WebP is converted to PNG), and native footnotes. Equations become native Word equations (fractions, scripts, radicals, sums and integrals, delimiters, functions, accents, matrices, `cases` and aligned equations; display environments are read back as `align`); a formula using anything else stays LaTeX text in a style the Word parser reads back, with a warning. Citations and cross-references stay `\cite`/`\ref`/`\label` macros. Not representable and therefore lost: the code language, unnumbered headings, image titles, and a block quote's alert type beyond its label. `template` is ignored, and images are embedded (`auto` and `link` act as `embed`). The file is written to a temporary name and renamed when complete.
