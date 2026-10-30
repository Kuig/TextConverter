from __future__ import annotations

from collections.abc import Callable


def register_tools(mcp: object) -> None:
    """Register all TextConverter MCP tools with the given MCPServer instance.

    A failed conversion is raised as ``ToolError``: the client gets a tool
    error (``isError``) carrying the message, so a failure cannot be mistaken
    for a converted document. (Any other exception would reach the client as a
    bare "Error executing tool".)

    Args:
        mcp: An ``mcp.server.mcpserver.MCPServer`` instance.
    """
    from mcp.server.mcpserver.exceptions import ToolError
    from textconverter.api import convert, convert_text, save_to_file
    from textconverter.options import ConvertOptions

    def _run(call: Callable[[], str]) -> str:
        try:
            return call()
        except Exception as exc:
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc

    @mcp.tool()
    def textconverter_convert_text(
        text: str,
        from_format: str,
        to_format: str,
        template: str = "plain",
        image_handling: str = "auto",
        code_parsing: bool = False,
        extract_html: bool = False,
        discard_links: bool = False,
        site_cleanup: bool | None = None,
        output_dir: str | None = None,
        image_dir_name: str | None = None,
    ) -> str:
        """Convert a document given as text to another format and return it.

        Args:
            text: The source document itself (never read as a file path).
            from_format: Source format: 'markdown', 'html', 'latex', 'json' or 'csv'.
            to_format: Target format: 'markdown', 'html', 'latex', 'json' or 'csv' (the first table).
            template: HTML template: 'plain', 'light' or 'dark'.
            image_handling: 'auto', 'describe', 'embed', 'link' or 'discard'.
            code_parsing: Fence code blocks found by heuristic detection (Markdown sources).
            extract_html: Filter noise and keep the main content of HTML input.
            discard_links: Replace every hyperlink with its visible text.
            site_cleanup: Override for site-specific HTML cleanup (e.g. Wikipedia) during
                extract_html. None uses the config default; False disables it.
            output_dir: Directory for downloaded remote images (the server's current
                directory when None).
            image_dir_name: Subdirectory of output_dir for those images.

        Returns:
            The converted document.
        """
        def call() -> str:
            options = ConvertOptions(template=template, image_handling=image_handling,
                                     code_parsing=code_parsing, extract_html=extract_html,
                                     discard_links=discard_links, site_cleanup=site_cleanup)
            return convert_text(text, from_format, to_format, options,
                                output_dir=output_dir, image_dir_name=image_dir_name)
        return _run(call)

    @mcp.tool()
    def textconverter_convert_file(
        source: str,
        to_format: str,
        from_format: str | None = None,
        template: str = "plain",
        image_handling: str = "auto",
        code_parsing: bool = False,
        extract_html: bool = False,
        discard_links: bool = False,
        site_cleanup: bool | None = None,
        pdf_mode: str = "text",
        output_dir: str | None = None,
        image_dir_name: str | None = None,
    ) -> str:
        """Convert a file or a remote URL to another format and return it.

        Args:
            source: File path, or remote URL (http:// or https://).
            to_format: Target format: 'markdown', 'html', 'latex', 'json' or 'csv' (the first table).
            from_format: Source format ('markdown', 'html', 'latex', 'json', 'pdf', 'docx', 'pptx', 'csv', 'xlsx', 'image').
                Inferred from the extension (for a URL, from its Content-Type) if None.
            template: HTML template: 'plain', 'light' or 'dark'.
            image_handling: 'auto', 'describe', 'embed', 'link' or 'discard'.
            code_parsing: Fence code blocks found by heuristic detection (Markdown
                sources, PDF sources in text mode).
            extract_html: Filter noise and keep the main content of HTML input.
            discard_links: Replace every hyperlink with its visible text.
            site_cleanup: Override for site-specific HTML cleanup (e.g. Wikipedia) during
                extract_html. None uses the config default; False disables it.
            pdf_mode: How to read PDF input: 'text' (its text layer) or 'raster'
                (every page rendered and transcribed by the AI describer).
            output_dir: Directory for downloaded and extracted images (the server's
                current directory when None).
            image_dir_name: Subdirectory of output_dir for those images.

        Returns:
            The converted document.
        """
        def call() -> str:
            options = ConvertOptions(template=template, image_handling=image_handling,
                                     code_parsing=code_parsing, extract_html=extract_html,
                                     discard_links=discard_links, site_cleanup=site_cleanup,
                                     pdf_mode=pdf_mode)
            return convert(source, to_format, options, from_format=from_format,
                           output_dir=output_dir, image_dir_name=image_dir_name)
        return _run(call)

    @mcp.tool()
    def textconverter_save_file(
        source: str,
        output_path: str,
        from_format: str | None = None,
        template: str = "plain",
        image_handling: str = "auto",
        code_parsing: bool = False,
        extract_html: bool = False,
        discard_links: bool = False,
        site_cleanup: bool | None = None,
        pdf_mode: str = "text",
    ) -> str:
        """Convert a file or a remote URL and save the result to a file.

        Args:
            source: File path, or remote URL (http:// or https://). Text is not
                accepted: use textconverter_convert_text for it.
            output_path: Output file path; its extension (.md, .html, .tex, .json,
                .pdf, .docx, .pptx, .xlsx, .csv) sets the format. A .csv output holds the tables only,
                one file per table when there are several. Images go to '<output name>_images' next to it.
            from_format: Source format ('markdown', 'html', 'latex', 'json', 'pdf', 'docx', 'pptx', 'csv', 'xlsx', 'image').
                Inferred from the extension (for a URL, from its Content-Type) if None.
            template: HTML template: 'plain', 'light' or 'dark' (ignored for .pdf, .docx, .pptx and .xlsx).
            image_handling: 'auto', 'describe', 'embed', 'link' or 'discard'.
            code_parsing: Fence code blocks found by heuristic detection (Markdown
                sources, PDF sources in text mode).
            extract_html: Filter noise and keep the main content of HTML input.
            discard_links: Replace every hyperlink with its visible text.
            site_cleanup: Override for site-specific HTML cleanup (e.g. Wikipedia) during
                extract_html. None uses the config default; False disables it.
            pdf_mode: How to read PDF input: 'text' (its text layer) or 'raster'
                (every page rendered and transcribed by the AI describer).

        Returns:
            Confirmation message with the paths written.
        """
        def call() -> str:
            options = ConvertOptions(template=template, image_handling=image_handling,
                                     code_parsing=code_parsing, extract_html=extract_html,
                                     discard_links=discard_links, site_cleanup=site_cleanup,
                                     pdf_mode=pdf_mode)
            written = save_to_file(source, output_path, options, from_format=from_format)
            return f"Successfully saved to {', '.join(written)}"
        return _run(call)
