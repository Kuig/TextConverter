# TextConverter Architecture

TextConverter needs to convert between five heterogeneous document formats (PDF, HTML, Markdown, LaTeX, JSON), share the same image handling and code detection logic across all of them, and expose that logic through four different interfaces (CLI, MCP, GUI, library) without duplicating it once per interface. The rest of this document explains how the codebase is organized to satisfy that.

## Codemap

```
TextConverter/
├── config.json                      ← AI provider and app-level configuration
├── secrets.json.example             ← Template for API keys (copy to secrets.json)
├── pyproject.toml                   ← Packaging and project setup
├── requirements_dev.txt             ← Development dependencies
├── requirements_prod.txt            ← Production dependencies (includes unified_ai_client)
├── test.py                          ← Convenience wrapper around tests/test.py
├── README.md
├── ARCHITECTURE.md
├── CONTRIBUTING.md
├── DocsInput/                       ← Sample input documents
├── DocsOutput/                      ← Generated output documents
├── tests/                           ← Unit test suite (unittest)
├── Windows Integration/             ← Windows shell context menu integration
│   └── generate_registry_files.ps1  ← Dynamic registry file generator
└── textconverter/                   ← Core package
    ├── __init__.py                  ← Package initializer, UTF-8 console setup
    ├── __main__.py                  ← CLI entry point (convert / mcp / gui subcommands)
    ├── api.py                       ← Public API: convert(), save_to_file()
    ├── ast.py                       ← Document AST node definitions
    ├── code_detector.py             ← Heuristic code block detection
    ├── config.py                    ← Configuration loading and provider setup helpers
    ├── image_describer.py           ← AI-assisted image classification and description
    ├── logger.py                    ← Dual-backend logger (console / Streamlit)
    ├── mcp_tools.py                 ← MCP tool definitions
    ├── parsers/                     ← Format-specific parsers
    ├── renderers/                   ← Format-specific renderers
    └── gui/                         ← Streamlit user interface
        └── app.py                   ← Streamlit web interface entrypoint
```

Every format flows through the same **parser → AST → renderer** pipeline: it is converted to and from a single, format-agnostic in-memory document tree, so adding a new format only requires a new parser and/or renderer; the rest of the pipeline (image handling, code detection, CLI/MCP/GUI) is shared automatically.

1. **Parse**: `parsers/` turns a source (file, raw text, or downloaded URL content) into a `Document` tree (`ast.py`): `pdf_parser.py` (via `pymupdf4llm`), `html_parser.py` (zero-dependency heuristic `HTMLParser` subclass, also used for `--extract-html` boilerplate stripping), `latex_parser.py`, `markdown_parser.py`, `json_parser.py`, and `image_parser.py` (delegates to the AI describer, then re-parses the resulting Markdown).
2. **Transform**: `api.py`'s `convert()` orchestrates cross-cutting steps on the AST: downloading and deduplicating remote images, resolving the `image_handling` strategy (`describe`, `embed`, `link`, `discard`, `auto_latex`, or `auto`'s per-format default; see the README's [Image Handling](README.md#image-handling) section), and optionally running `code_detector.py`'s heuristic to fence detected code blocks.
3. **Render**: `renderers/` turns the (possibly transformed) `Document` back into a string in the target format: `markdown_renderer.py`, `html_renderer.py` (using `templates.py`), `latex_renderer.py`, `json_renderer.py`.

### The AST

A small set of `@dataclass` node types (`Document`, `Paragraph`, `Heading`, `Text`, `Link`, `Image`, `Table`, `CodeBlock`, `Equation`, `Citation`, `Footnote`, ...) in `ast.py` models the structural and inline elements common across PDF, HTML, Markdown, LaTeX, and JSON. `Image` nodes carry both the raw source path and AI-derived metadata (`description`, `category`, `extracted_text`) populated during the transform step.

## Interfaces

All four interfaces are thin wrappers around the same `convert()`/`save_to_file()` API in `api.py`:

- **CLI** (`__main__.py`): `argparse` subcommands (`convert`, `mcp`, `gui`).
- **MCP server** (`mcp_tools.py`): FastMCP tools over stdio, for use from AI agents/IDEs.
- **Python library**: direct import of `textconverter.api`.
- **Streamlit GUI** (`gui/app.py`): sidebar for options, main area for source/output and results.

## Invariants

- No business logic is duplicated between the four interfaces above: each one only parses its own kind of input (CLI args, MCP tool parameters, Streamlit widgets) and calls into `api.py`.
- `image_describer.py` is the project's only optional dependency boundary: core parsing and rendering work without `unified_ai_client` installed, and nothing outside `image_describer.py` imports it.

## Cross-cutting concerns

**AI image description** (`image_describer.py`): when `image_handling` requires it, each `Image` node is classified (one of 8 categories: photo, diagram, chart, text/table/formula, infographic, document scan, logo, map) and then described with a category-specific prompt, via `unified_ai_client`'s `call_ai()`/`preload_model()`/`configure_provider()`.

**Configuration** (`config.py`): `config.json` is loaded into typed dataclasses (`AppConfig`/`AiConfig`), resolved in priority order CWD, then package root, then built-in defaults, so the app always starts even without a `config.json` present. Provider connection settings (e.g. the `"ollama"` block) intentionally stay a plain `dict`: their shape is provider-specific and owned by `unified_ai_client`, not by TextConverter.

**Logging** (`logger.py`): a dual-backend logger (`log_success`, `log_error`, `log_action`, ...) prints to the console by default and switches to Streamlit widgets when `set_backend("streamlit")` is called by the GUI, so the same business logic code path drives both interfaces without any conditional branching.
