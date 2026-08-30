from __future__ import annotations


def register_tools(mcp: object) -> None:
    """Register all TextConverter MCP tools with the given FastMCP instance.

    Args:
        mcp: A FastMCP server instance.
    """

    @mcp.tool()
    def textconverter_convert_text(
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
    ) -> str:
        """Convert text or a file to a target document format.

        Args:
            source: Source text content, file path, or remote URL (e.g., http:// or https://).
            to_format: Target format ('html', 'markdown', 'latex', 'json').
            from_format: Optional source format hint. Inferred from extension if None.
            template: Rendering template name (default: 'plain').
            is_file: If True, source is treated as a file path.
            output_dir: Optional directory for extracted assets (images, etc.).
            image_dir_name: Optional name for the image assets subdirectory.
            image_handling: Image handling strategy ('auto', 'describe', 'embed', 'link', 'discard').
            code_parsing: If True, enables AI-assisted code block detection for Markdown output.
            extract_html: If True, filters noise and extracts main content from HTML.

        Returns:
            Converted document as a string.
        """
        try:
            from textconverter.api import convert
            return convert(
                source, to_format, from_format, template,
                is_file, output_dir, image_dir_name, image_handling,
                code_parsing=code_parsing,
                extract_html=extract_html,
            )
        except Exception as exc:
            return f"Error: {exc}"

    @mcp.tool()
    def textconverter_save_file(
        source: str,
        output_path: str,
        template: str = "plain",
        image_handling: str = "auto",
        code_parsing: bool = False,
        extract_html: bool = False,
    ) -> str:
        """Convert a document and save it to a file.

        Args:
            source: Source text content, file path, or remote URL (e.g., http:// or https://).
            output_path: Full output file path (format inferred from extension).
            template: Rendering template name (default: 'plain').
            image_handling: Image handling strategy ('auto', 'describe', 'embed', 'link', 'discard').
            code_parsing: If True, enables AI-assisted code block detection.
            extract_html: If True, filters noise and extracts main content from HTML.

        Returns:
            Confirmation message with the output path.
        """
        try:
            from textconverter.api import save_to_file
            save_to_file(source, output_path, template, image_handling, code_parsing=code_parsing, extract_html=extract_html)
            return f"Successfully saved to {output_path}"
        except Exception as exc:
            return f"Error: {exc}"
