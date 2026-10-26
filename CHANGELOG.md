# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

### Changed

- Requires `unified-ai-client>=0.8.0` for AI features. Since 0.8.0 the library no longer sends
  default sampling values (temperature, top_k, top_p), so the model's own defaults apply.
- The default classification and description model is `gemma4:e2b` (was `gemma4:12b`).
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

[Unreleased]: https://github.com/Kuig/TextConverter/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/Kuig/TextConverter/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/Kuig/TextConverter/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Kuig/TextConverter/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Kuig/TextConverter/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Kuig/TextConverter/releases/tag/v0.1.0
