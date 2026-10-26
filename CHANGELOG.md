# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The GUI exposes the provider's context size as a slider (4k to 256k tokens), saved to
  `config.json` with **Save as default**.

- `convert_text()` converts a document given as text; `convert()` now takes only file paths and
  URLs, so text that happens to name an existing file is no longer read from disk.
- `ConvertOptions` groups the conversion options in one validated dataclass, and `formats.py`
  declares the formats, image handling modes, PDF modes and template names in one place.
- `save_to_file()` accepts `from_format`, for URLs or files whose extension does not tell the
  format.
- `.txt` files are read as Markdown.
- `--from` (CLI) and `from_format` (MCP `textconverter_save_file`) set the source format.
- MCP: `textconverter_convert_file` converts a file or URL; `textconverter_convert_text` now
  takes only text (`text`, `from_format`, `to_format`).
- The Windows context menu also covers `.json` sources.
- `Equation` nodes carry an optional `env` (e.g. `align`, `gather*`), so a display environment
  can be reproduced instead of being forced into `equation`.

### Changed

- The committed `config.json` sets the Ollama `context_size` to 8192: at 4096, a page
  transcribed in PDF raster mode could fill the window by itself and come out truncated.
- **Breaking:** `convert(source, to_format, options=None, *, from_format, output_dir,
  image_dir_name, config)` and `save_to_file(source, output_path, options=None, *, from_format,
  config)` take a `ConvertOptions` instead of one keyword per option; `is_file` is gone. The
  parsers take keyword-only options with uniform names (`parse_html(text, extract_html=...)`,
  `parse_pdf(path, config=..., pdf_mode=...)`, `parse_image(path, config=...)`,
  `parse_json(text)`), `render_latex(doc)` no longer takes `image_handling`, and `config` is a
  required keyword below the API.
- An unknown template, image handling mode, PDF mode or format raises `ValueError` before any
  work starts, instead of falling back silently (template, image handling) or failing after
  the AI calls (output format).
- `save_to_file()` refuses an output path that is the source file itself.
- **Breaking:** requires `mcp>=2.3,<3`; the MCP server runs on `MCPServer` (FastMCP's new name),
  so `textconverter mcp` works again with the mcp 2.x that pip installs.
- MCP tools raise their errors as tool errors (`isError` with the message) instead of returning
  `"Error: ..."` as if it were a converted document.
- The CLI, the GUI and the MCP docstrings take their template, image handling and PDF mode
  choices from the format registry; `--template` rejects unknown names. The GUI file dialogs
  list every supported extension (`.markdown`, `.latex`, `.txt` included).
- The Windows context menu runs the CLI (through `convert.cmd`) with its default options: images
  follow `--image-handling auto` like on the command line, code detection applies to PDF
  sources in text mode, and a failed conversion keeps its window open to show the error.
- JSON input is checked against an explicit registry of node types: an unknown or missing
  `type`, a missing required field or a child list that is not a list raises `ValueError`
  instead of silently dropping the node from the output.
- A URL source's format comes from the response's `Content-Type` first, so a PDF served from
  a URL without `.pdf` (e.g. arXiv) is no longer read as HTML. A failed download raises
  `DownloadError` (a `RuntimeError`).
- Image and file sources downloaded from a URL go to the system temporary folder, not to the
  output or current directory.

### Fixed

- Downloaded pages are decoded with the charset of their `Content-Type` or `<meta charset>`:
  accented letters of a non-UTF-8 page were silently dropped.
- Images are found wherever the output goes: embedding, description and transcription used to
  look for downloaded images next to the source while they were saved next to the output, and
  `convert()` resolved a file's relative images against the current directory. Image links in
  the output are relative to the output folder, so a Markdown file written to another folder
  still points at the source's local images.
- An image with an empty `src` on a web page no longer downloads the page itself as an image;
  a response typed as a non-image (an HTML error page) is not saved as one; an image served as
  `application/octet-stream` keeps its extension instead of becoming `.bin`.
- Protocol-relative image sources (`//host/x.png`) are downloaded instead of being opened as
  network paths on Windows; `data:` images are no longer looked up as files.
- With LaTeX or JSON output, image sources and PDF pages in raster mode are no longer sent to
  the AI a second time.
- Without a `config.json`, changing a setting in the GUI (e.g. the context size) no longer
  changes the built-in defaults for every later configuration in the same process.
- A `config.json` section that is not a JSON object (e.g. `"wikipedia": [...]`) is reported
  with a warning before it is replaced by defaults, instead of being ignored silently.
- The GUI's site cleanup checkbox starts from `html.site_cleanup` in `config.json` (it was always
  ticked, so `false` was ignored in the GUI).
- GUI log messages are shown as text: a URL or an error message containing `<` no longer
  injects markup into the page.

### Removed

- `config.get_ai_config()`, which had no callers; use `AppConfig.ai`. `AppConfig` gains
  `provider_settings()` for the active provider's settings block.

## [0.2.0] - 2026-10-26

### Added

- **Site-specific HTML cleanup.** During `--extract-html`, a Wikipedia profile (any language
  edition, recognized by URL or by the MediaWiki markup) removes edit links, navboxes,
  maintenance banners, hatnotes, the table of contents, category footers and inline `[n]`
  citation markers, and drops configurable end-matter sections. `--no-site-cleanup` turns it
  off for one run; the `html` section of `config.json` sets the default and tunes the profile.
- `--discard-links` (API: `discard_links=True`) replaces every hyperlink with its visible text,
  for any source format.
- The GUI exposes the site cleanup and discard links options.
- `docs/configuration.md` documents every `config.json` field.
- **OCR model for text, tables and formulas.** Images are classified first; text, tables,
  formulas and page scans are then transcribed by `ai.ocr_model` (default `glm-ocr`) with its
  task prompts (`ai.ocr_prompts`), while the other categories are still described by the
  description model. HTML tables in OCR answers become regular tables.
- `convert()` and `save_to_file()` take an optional `config` that overrides `config.json`.
- **PDF raster mode.** `--pdf-mode raster` (API and MCP: `pdf_mode="raster"`) renders every
  page and sends it through the AI image pipeline (classification, then OCR or description),
  for scanned PDFs or PDFs with an unusable text layer. A page that cannot be transcribed is
  kept as an image.
- Opt-in live tests against the configured AI provider (`TEXTCONVERTER_LIVE_AI=1`).
- **The GUI offers the available providers and models as menus**, listed by UnifiedAiClient:
  local servers that answer and cloud providers with a key, and the models that accept images,
  for classification, description and OCR. A saved value that is not available stays selected,
  with a warning; a provider that cannot list its models falls back to a text field; a refresh
  button reloads the lists. **Save as default** writes the choice to `./config.json`
  (`AppConfig.save()`).
- The GUI also offers the PDF input mode, PDF as an output type, and images as input files.
- `docs/api.md` documents the library functions (moved out of the README).
- The Windows context menu offers PDF output for every non-PDF source, and a "(raster)"
  variant of every command for PDF sources.
- **PDF output.** An output path ending in `.pdf` prints the light-theme HTML rendering, with
  images embedded: through a headless Edge, Chrome or Chromium when one is installed
  (formulas typeset by MathJax), otherwise through PyMuPDF's built-in layout engine. No new
  dependency.

### Changed

- Requires `unified-ai-client>=0.8.0` for AI features. Since 0.8.0 the library no longer sends
  default sampling values (temperature, top_k, top_p), so the model's own defaults apply.
- The default classification and description model is `gemma4:e2b` (was `gemma4:12b`).
- **Image processing runs in phases, one model at a time** (classify all, describe, then
  transcribe), so each model is loaded once per conversion instead of alternating per image.
- The image category `short_text_table_or_formula` is split into `text`, `table` and `formula`;
  a `config.json` that still uses the old key falls back to the `default` prompt for it.
- Classification and OCR calls use temperature 0 (`ai.classification_temperature`,
  `ai.ocr_temperature`).
- Without `unified_ai_client`, LaTeX and JSON output (`image_handling="auto"`) keep images as
  plain references with a warning instead of failing.
- `pymupdf4llm` is pinned to `>=0.3.4,<1` and `pymupdf` is declared explicitly. Newer
  `pymupdf4llm` releases need `onnxruntime`; where it is unavailable (e.g. on new Python
  versions) pip installed `pymupdf4llm` 2.0, an empty package, and PDF input failed.
- HTML main-content extraction drops a skipped element together with all its nested children.
- The test suite is split into one `tests/test_<area>.py` per area and runs with
  `python -m unittest discover -s tests`; the root `test.py` wrapper is gone. No test can
  reach a live AI model any more (a LaTeX conversion test used to preload one).

### Removed

- The unused `config.configure_provider_from_config()` helper.

### Fixed

- The `--code-parsing` help text described the detection as AI-assisted; it is heuristic.
- The GUI file dialogs sometimes failed with "main thread is not in main loop"; they now run
  in a separate process.
- PDF input no longer prints the `pymupdf_layout` recommendation on stdout, which could also
  corrupt the MCP protocol stream.
- LaTeX output omitted `\usepackage{graphicx}` (or `hyperref`) when the only image or link sat
  inside a link or a table header.
- PDF input left the extraction folder prefix on image paths found in table headers.

## [0.1.4] - 2026-09-10

### Fixed

- Markdown tables: escaped pipes and pipes inside inline code no longer split cells.
- HTML tables with `colspan`/`rowspan` (e.g. from Word) are expanded into a regular grid
  instead of losing or shifting cells; line breaks inside cells are kept in every renderer.

## [0.1.3] - 2026-09-03

### Fixed

- Downloads (URL sources, remote images) failed with "certificate has expired" on systems with
  a stale CA bundle. TLS is now verified against the operating system trust store
  (`truststore`), falling back to `certifi`.

## [0.1.2] - 2026-08-30

### Changed

- AI provider setup and model preloading run once per conversion instead of once per image.
- A failed image description is skipped with a warning instead of writing an error string into
  the document.
- `config.json` loading reports unknown keys and invalid JSON instead of failing silently; the
  JSON AST loader ignores unknown keys with a warning.
- The MCP server routes log output to stderr so it cannot corrupt the protocol stream.
- Documentation split into README, `ARCHITECTURE.md` and `CONTRIBUTING.md`.

## [0.1.1] - 2026-08-08

### Fixed

- Images wrapped in a link were rendered broken.

## [0.1.0] - 2026-08-08

### Added

- First tagged release: conversion between PDF, HTML, Markdown, LaTeX and JSON through a shared
  document AST, with URL inputs, HTML main-content extraction, remote image download, AI image
  classification and description, heuristic code detection, equations, and CLI, MCP, GUI and
  library interfaces.

[Unreleased]: https://github.com/Kuig/TextConverter/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Kuig/TextConverter/compare/v0.1.4...v0.2.0
[0.1.4]: https://github.com/Kuig/TextConverter/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/Kuig/TextConverter/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Kuig/TextConverter/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Kuig/TextConverter/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Kuig/TextConverter/releases/tag/v0.1.0
