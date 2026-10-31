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
- `code_parsing`: Enable heuristic code-block detection (Markdown, Word and PowerPoint sources, and PDF sources in text mode). In Word and PowerPoint it looks at paragraphs of unformatted text, also in quotes and text boxes, and merges the adjacent ones it recognizes; text in a monospaced font or a code style is read as code without it.
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
- `to_format`: `"markdown"`, `"html"`, `"latex"`, `"json"` or `"csv"` (the first table; PDF, Word, PowerPoint and Excel output go through `save_to_file()`, which also writes one CSV file per table).
- `from_format`: `"markdown"`, `"html"`, `"latex"`, `"json"`, `"pdf"`, `"docx"`, `"pptx"`, `"csv"`, `"xlsx"` or `"image"`. Inferred when omitted: from the file extension (`.txt` is read as Markdown); for a URL, from the response's `Content-Type`, then the URL's extension, else HTML. A downloaded text page is decoded with the charset of its `Content-Type` or `<meta charset>`, else UTF-8.
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
) -> list[str]:
```
Convert a file or URL like `convert()`, write the result to `output_path` and return the paths written (`[output_path]`, or one path per table for a `.csv` output with several tables). The output format comes from its extension (`.md`, `.html`, `.tex`, `.json`, `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.csv`); images go to a `<output stem>_images` folder next to it, unless they are embedded (`embed`, or `auto` for HTML, PDF, Word, PowerPoint and Excel), which leaves no folder. An output path that is the source file itself raises `ValueError`.

A `.pdf` output path renders the document as HTML with the light theme and prints it: with a headless Edge, Chrome or Chromium when one is installed (full styling, formulas typeset by MathJax when online), otherwise with PyMuPDF's built-in layout engine (simpler styling, formulas shown as TeX). `template` is ignored, and images are embedded in the PDF (`auto` and `link` act as `embed`).

A `.docx` output path writes the document with python-docx (A4, the built-in Word styles): headings, formatting, links, nested lists (each list counts from its own start), quotes, code (style `Code`), tables with a header row, auto-numbered captions (`SEQ` fields), images (embedded; WebP is converted to PNG), and native footnotes. Equations become native Word equations (fractions, scripts, radicals, sums and integrals, delimiters, functions, accents, matrices, `cases` and aligned equations; display environments are read back as `align`); a formula using anything else stays LaTeX text in a style the Word parser reads back, with a warning. Citations and cross-references stay `\cite`/`\ref`/`\label` macros. Not representable and therefore lost: the code language, unnumbered headings, image titles, and a block quote's alert type beyond its label. `template` is ignored, and images are embedded (`auto` and `link` act as `embed`). The file is written to a temporary name and renamed when complete.

A `.pptx` output path writes the document with python-pptx onto a neutral 16:9 template. A level 1 heading is a PowerPoint section (slides before the first one go to a "Default Section"; a section's own text becomes a slide titled like it, and a section without text has no slide of its own), every deeper heading a slide: a level 3 title starts with `#`, level 4 with `##`, and so on. A slide's text (paragraphs, lists, code, equations) is written in the content placeholder, shrunk down to half size until it fits; tables and pictures follow it, in that order. A block quote whose first paragraph reads `Text box (x 10%, y 50%, w 30%, h 20%)` becomes a text box at that frame (percentages of the slide); any other quote becomes a text box under the content. Footnotes become the slide's speaker notes. The first slide uses the title layout when it holds one or two plain paragraphs of a section's own text, or under a level 2 heading a single line of at most 80 characters. A document made only of level 1 headings without text, which would have no slide, gets a title slide for each. Equations are native PowerPoint equations (a formula the converter cannot translate stays LaTeX text, with a warning). Metadata goes to the file properties and never to a slide. Not representable and therefore lost: the order of text, tables and pictures within a slide, captions as such (they become italic text), a footnote's position in the text, and the boundary between two consecutive footnotes of one slide. `template` is ignored, and images are embedded (`auto` and `link` act as `embed`).

Reading a `.pptx` source gives a level 1 heading per section (none when the file has at most one section) and a level 2 heading per slide, hidden slides included; a title starting with `#` is a deeper slide, and a section's first slide titled like the section merges into it. A slide's main text box (its content placeholders, else the text box with the most text) is its body; every other text box and text-bearing shape is a quote headed by its frame. A font that is monospaced (Consolas, Courier, ...) is code. Speaker notes become a footnote on the slide's heading. Tables are read with their header row, native charts as a table of their cached data (the chart title is the caption), SmartArt as a nested list of its text (its structure is lost; writing it as a text diagram language such as Mermaid is a possible future step), embedded objects as their preview image. The theme, animations and transitions are ignored; video and audio, shapes without text, connectors and links to slides are dropped with a single warning.

Spreadsheets keep only tables. A `.xlsx` output path writes each table of the document as a sheet (XlsxWriter) named after the nearest heading above it (at most 31 characters, `[]:*?/\` replaced by spaces, a repeated name gets ` (2)`; `Sheet1`, `Sheet2`, ... without a heading); the header is the bold first row. A code block in the `excel` language under a table lists its formulas, one per line, as `D2:D100 = B2*C2` (a range, then the formula of its first cell, whose references move with the other cells) or `E5 = SUM(E2:E4)`; each formula cell is written with its table text as the stored result. A cell's text becomes a number, a boolean (`TRUE`/`FALSE`), a date (`2026-10-30`, `2026-10-30 14:30:00`) or a time (`14:30:00`) only when that is exactly how reading would write the value back (`007` and `1,5` stay text). A footnote in a cell is its comment, a link its hyperlink, and an image in it (embedded; `auto` and `link` act as `embed`) is anchored to it. Everything else in the document is dropped, and a document without a table raises `ValueError`. A `.csv` output path writes the tables as UTF-8 with a BOM, comma-separated: the file itself for one table, else `<stem>_<sheet name>.csv` for each; `convert(..., "csv")` returns the first table (with a warning when there are more). In both formats inline code is its text, math stays `$...$` and citations and cross-references stay LaTeX macros.

The tables of a PDF are found in its text layer only when they are drawn with ruled lines: a table laid out by alignment alone (typical of journals) stays text. `pdf_mode="raster"` reads the page images instead, and what it finds depends on the AI model.

Reading a `.xlsx` source gives a level 1 heading and a table per visible sheet (no heading for a workbook with one sheet); the table starts at A1 so the formula coordinates stay true, and its first row is the header. Values are normalized (whole numbers without `.0`, dates in ISO form, `TRUE`/`FALSE`, a formula cell shows its stored result, empty with a warning when the file stores none), comments are footnotes, hyperlinks links, partial bold/italic/strikethrough/script formatting is kept (not on the header row), and an image anchored to a cell is extracted like PDF images. Merged cells (the value stays in the first cell), charts, pivot tables, filters, conditional formatting and array formulas are dropped with a single warning. A `.csv`/`.tsv` source is read as one table whose header is the first row, with the delimiter (`, ; <tab> |`) detected and the encoding UTF-8 (with or without a BOM) or else Windows-1252. The Excel file's title, author and creation date are the document metadata.
