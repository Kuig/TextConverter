# Library API

Both functions live in `textconverter.api` and are also exported by the `textconverter` package. The CLI, the MCP tools and the GUI are thin wrappers around them.

## `convert()`

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
    pdf_mode: str = "text",
) -> str:
    """Convert text or a file to a specific format and return the result as a string."""
```
- `source`: File path, remote URL (`http://`/`https://`), or raw text content.
- `to_format`: Target format: `"markdown"`, `"html"`, `"latex"`, or `"json"` (PDF output goes through `save_to_file()`).
- `from_format`: Source format hint (`"pdf"`, `"markdown"`, `"html"`, `"latex"`, `"json"`, `"image"`). Inferred from the file/URL extension when omitted; required when `source` is raw text with no extension to infer from.
- `template`: HTML rendering template (see [renderers/templates.py](../textconverter/renderers/templates.py)): `"plain"`, `"light-theme"`, or `"dark-theme"`.
- `is_file`: Treat `source` as a file path rather than raw text.
- `output_dir` / `image_dir_name`: Base directory and subdirectory name used to write downloaded/extracted images.
- `image_handling`: `"auto"` (default, format-dependent), `"describe"`, `"embed"`, `"link"`, or `"discard"` (see the README's [Image Handling](../README.md#image-handling)). `"auto_latex"` is also accepted, as the internal fallback `auto` uses on LaTeX/JSON output, but it's not meant to be set directly since its behavior may change.
- `code_parsing`: Enable heuristic code-block detection (Markdown/HTML sources).
- `extract_html`: Strip boilerplate and isolate main content when parsing HTML.
- `discard_links`: Replace every hyperlink with its visible text (any source format).
- `site_cleanup`: Override for site-specific HTML cleanup during `extract_html`. `None` uses the `html.site_cleanup` config default; `False` disables it for this call.
- `config`: A `textconverter.config.AppConfig` to use instead of `config.json` (e.g. `load_config()` with the AI provider or models changed).
- `pdf_mode`: How PDF input is read. `"text"` (default) uses the text layer; `"raster"` renders every page at 200 DPI and sends it through the AI image pipeline (each page is classified, then transcribed by the OCR model or described), for scans or PDFs whose text layer is unusable. In raster mode `image_handling` only applies to pages that could not be transcribed, which are kept as images.

## `save_to_file()`

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
    pdf_mode: str = "text",
) -> None:
    """Convert and write the result directly to output_path (format inferred from its extension)."""
```
Same semantics as `convert()`, but infers both `to_format` (from `output_path`'s extension) and `is_file=True`, and writes the result to disk instead of returning it.

A `.pdf` output path renders the document as HTML with the light theme and prints it: with a headless Edge, Chrome or Chromium when one is installed (full styling, formulas typeset by MathJax when online), otherwise with PyMuPDF's built-in layout engine (simpler styling, formulas shown as TeX). `template` is ignored, and images are embedded in the PDF (`auto` and `link` act as `embed`).
