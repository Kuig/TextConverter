# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The AST can hold more of a document: `Document` metadata (`title`, `author`, `date`), table
  and figure captions and labels (`Table.caption`/`label`, `Image.caption`/`label`), the
  optional arguments of a citation (`Citation.options`, as in `\citep[e.g.][p.~3]{key}`),
  superscript and subscript text (`Text.script`), unnumbered headings (`Heading.numbered`),
  the start of the appendices (`Appendix`), the first number of an ordered list
  (`ListBlock.start`) and task list items (`ListItem.checked`). The JSON output carries the
  new fields; JSON written by 0.3.0 still loads.
- HTML input reads table captions (`<caption>`), figures (`<figure>` with `<figcaption>`),
  superscript and subscript, `<ol start>` and task list checkboxes; HTML output writes them
  back. Markdown and LaTeX output show a caption as a `Table: ...` / `Figure: ...` paragraph.

### Changed

- HTML output marks the reference macros it writes (`\cite`, `\footnote`, `\ref`, `\label`,
  still shown as LaTeX) with `tc-ref` / `tc-footnote` spans, and the document title block
  with `tc-*` classes, so LaTeX → HTML → LaTeX keeps them; the macros of HTML written by
  0.3.0 are read back too. Macros typed in any other page stay text.
- The optional arguments of a citation (`\citep[e.g.][p.~3]{key}`) are kept in every format.
- HTML output: the page `<title>` is the document title (or the first main heading) instead of
  "Document"; a list item holding one paragraph is written without `<p>`; a display formula or
  a figure is no longer nested inside a `<p>`.
- With `--image-handling discard`, a figure's caption stays as text.
- Wikipedia cleanup also drops the "^" back links of the reference list when the citation
  markers they point to are dropped.

### Fixed

- HTML input with a table `<caption>`, or with text directly inside `<ul>`, `<ol>`, `<table>`
  or `<tr>`, no longer crashes the HTML and Markdown output; such text is kept (in the list's
  last item, or before the table as browsers show it), and a cell outside any row opens one.
- An anchor without `href` (`<a name="top">`) is plain text instead of an empty link, and
  MathML without a TeX annotation keeps its text instead of becoming an empty formula.

## [0.3.0] - 2026-10-26

### Breaking changes

- `convert(source, to_format, options=None, *, from_format, output_dir, image_dir_name,
  config)` and `save_to_file(source, output_path, options=None, *, from_format, config)` take
  a `ConvertOptions` instead of one keyword per option; `is_file` is gone, and text given
  directly goes through the new `convert_text()`. The parsers take keyword-only options with
  uniform names (`parse_html(text, extract_html=...)`, `parse_pdf(path, config=...,
  pdf_mode=...)`, `parse_image(path, config=...)`, `parse_json(text)`), `render_latex(doc)` no
  longer takes `image_handling`, and `config` is a required keyword below the API.
- Requires `mcp>=2.3,<3`; the MCP server runs on `MCPServer` (FastMCP's new name), so
  `textconverter mcp` works again with the mcp 2.x that pip installs.
- MCP: `textconverter_convert_text` takes only text (`text`, `from_format`, `to_format`); files
  and URLs go through the new `textconverter_convert_file`. Errors come back as tool errors
  (`isError`) instead of an `"Error: ..."` result.
- Site profiles are built with their settings (`SiteProfile.from_config()`), and their hooks
  are `skip_subtree(tag, attrs)` and `clean_ast(doc)`.

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
- The Windows context menu also covers `.json` sources.
- `Equation` nodes carry an optional `env` (e.g. `align`, `gather*`), so a display environment
  can be reproduced instead of being forced into `equation`.

### Changed

- The committed `config.json` sets the Ollama `context_size` to 8192: at 4096, a page
  transcribed in PDF raster mode could fill the window by itself and come out truncated.
- An unknown template, image handling mode, PDF mode or format raises `ValueError` before any
  work starts, instead of falling back silently (template, image handling) or failing after
  the AI calls (output format).
- `save_to_file()` refuses an output path that is the source file itself.
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
- A table or formula transcribed from an image inside a document becomes a real table or
  equation, as it already did for an image given as the source: with LaTeX output a table
  used to come out as escaped Markdown text. An image amid text splits its paragraph around
  the transcription. The JSON output holds the transcribed nodes too.
- Image descriptions (`describe`) are parsed like transcriptions in every output: in HTML and
  LaTeX a described table or formula used to be printed as escaped Markdown.
- An AI answer with no text is reported and skipped instead of raising `AttributeError`.
- Tables are padded to their widest row in every output and never cut: LaTeX sized a table on
  its first row and dropped cells beyond it, and Markdown dropped cells beyond the header.
- LaTeX output compiles in more cases: the preamble loads `amsmath`/`amssymb` for equations and
  `natbib` for `\citet`/`\citep`; a multi-line or aligned formula goes into `aligned` (or its
  original `align`, `gather`, ... environment) instead of a bare `equation`; a line break at the
  start or end of a paragraph is dropped; `~` in a link URL is no longer turned into
  `\textasciitilde{}`.
- HTML output renders `javascript:`, `vbscript:` and `data:` links as `#`.
- Strikethrough text is rendered in every format (`~~x~~`, `<s>`, `\sout`), and read from
  HTML `<s>`, `<del>` and `<strike>`.
- HTML main-content extraction (`--extract-html`) no longer corrupts or loses content:
  escaped markup in the text (`a &lt;b&gt;`, code samples) stayed escaped instead of turning
  into tags or vanishing; quoted attributes are no longer truncated; an omitted end tag
  (`</li>`, `</p>`, valid HTML5) inside dropped navigation no longer swallows the rest of the
  page, and a stray end tag no longer ends the main block early.
- HTML parsing: `<br>` (or another void element) inside `<b>`/`<i>` no longer makes the
  following text bold or italic; line breaks of the HTML source are spaces instead of hard
  breaks, and the space between two inline elements (`<b>a</b> <i>b</i>`) is kept; a stray
  end tag (such as `</code>` inside `<pre>`) no longer closes the enclosing block; a first
  row of `<th>` cells without `<thead>` is the table header; unclosed rows and cells are
  closed in place.
- HTML round trips: the page `<title>` becomes the main heading only when the page has no
  `h1` (TextConverter's own HTML is recognized and its placeholder title skipped, so
  md → html → md no longer adds `# Document`); the code language is read from
  `<code class="language-x">` (as written) and only from `language-`/`lang-` classes.
- Lazy-loaded images (`data-src`, `srcset`) keep their real source.
- A block quote starting with "Abstraction" (or any word beginning with "abstract") is no
  longer turned into an abstract.
- A Markdown hard break inside a paragraph is written with two trailing spaces, not four.
- Markdown output escapes literal text that would read back as markup (`*`, `` ` ``, `[`,
  `]`, `$`, word-edge `_`, `~~`, a backslash before punctuation or a macro name, and a line
  starting with `#`, `>`, `-`, `+`, `1.` or `---`); the Markdown parser understands backslash
  escapes. Code spans and code blocks use more backticks than the code holds, and a link or
  image URL with spaces or unbalanced parentheses goes between `<...>`. Markdown round trips
  are stable on the test documents.
- Markdown parsing: the text right after a heading line is no longer dropped; an empty header
  cell (`| | Q1 | Q2 |`) no longer shifts the columns and loses the last one; only a real
  delimiter row (`|---|`) makes a table; an undefined reference (`matrix[i][j]`) stays text
  instead of a link to `#`; an underscore inside a word (`my_var_name`) is not emphasis;
  nested emphasis (`**_x_**`) is bold and italic; `~~x~~` is strikethrough; URLs with
  parentheses (Wikipedia's `Foo_(bar)`) are kept whole; reference links work in list
  continuation lines; `\citet*{...}` is a citation; a code fence right after a `•` item
  belongs to that item; the two trailing spaces of a hard break are not kept as text.
- The described-image block written to Markdown is read back into the image's description
  and category.
- `--code-parsing` no longer alters the code it detects (`__init__` became `init`,
  `a * b * c` became `a  b  c`).
- A root-relative image path in a local HTML file (`/media/x.png`) is kept as is instead of
  being turned into a path on the current drive.
- LaTeX parsing:
  - source line breaks and indentation are spaces, as LaTeX typesets them, instead of hard
    breaks in Markdown and HTML (`\\` stays a line break, which LaTeX output now writes for a
    hard break from any source);
  - `equation*`, `align(*)`, `gather(*)`, `multline(*)`, `flalign(*)` and `eqnarray(*)` are
    equations (the environment is kept), not text like `equation* a=b equation*`;
  - nested lists are kept, `\itemsep` is not an item, and `\item[label]` keeps its label;
  - `%` inside `verbatim`/`lstlisting` is code, not a comment, and `lstlisting`'s
    `language=` sets the code language;
  - `\&` in a table cell is an ampersand, not a column separator;
  - `\emph` and `\textsl` are italic, `\sout` is strikethrough; accents (`\'e`, `` \`a ``,
    `\"o`, `\c{c}`, ...), `\ss`, `\o` and similar, `~` (no-break space), `--`/`---` (dashes),
    `\,` and the other spacing commands become the characters they print;
  - a `\section` after `\sectionmark` is no longer read as plain text;
  - `\citep[e.g.][p. 3]{key}` is a citation;
  - `\texttt{...}` and link URLs lose their LaTeX escapes (`a\_b` is `a_b`);
  - layout environments (`center`, `minipage`, ...) contribute their content instead of their
    name, and `quote` is a block quote;
  - a full-width `\rule` (how LaTeX output writes a horizontal rule) is read back as one.
  LaTeX → LaTeX and Markdown → Markdown round trips are stable on the test documents.
- A transcription with several formulas (`$$a$$ and $$b$$`) is no longer merged into one
  broken equation.
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

[Unreleased]: https://github.com/Kuig/TextConverter/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Kuig/TextConverter/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Kuig/TextConverter/compare/v0.1.4...v0.2.0
[0.1.4]: https://github.com/Kuig/TextConverter/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/Kuig/TextConverter/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Kuig/TextConverter/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Kuig/TextConverter/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Kuig/TextConverter/releases/tag/v0.1.0
