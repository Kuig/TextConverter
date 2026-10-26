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
        discard_links: bool = False,
        site_cleanup: bool | None = None,
        pdf_mode: str = "text",
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
            code_parsing: If True, enables heuristic code block detection for Markdown output.
            extract_html: If True, filters noise and extracts main content from HTML.
            discard_links: If True, replaces every hyperlink with its visible text.
            site_cleanup: Override for site-specific HTML cleanup (e.g. Wikipedia) during
                extract_html. None uses the config default; False disables it.
            pdf_mode: How to read PDF input: 'text' (its text layer) or 'raster'
                (every page rendered and transcribed by the AI describer).

        Returns:
            Converted document as a string.
        """
        try:
            import os
            from textconverter.api import convert, convert_text
            from textconverter.options import ConvertOptions
            options = ConvertOptions(
                template=template,
                image_handling=image_handling,
                code_parsing=code_parsing,
                extract_html=extract_html,
                discard_links=discard_links,
                site_cleanup=site_cleanup,
                pdf_mode=pdf_mode,
            )
            if is_file or source.startswith(("http://", "https://")) or os.path.isfile(source):
                return convert(source, to_format, options, from_format=from_format,
                               output_dir=output_dir, image_dir_name=image_dir_name)
            if from_format is None:
                raise ValueError("from_format must be specified when converting raw text.")
            return convert_text(source, from_format, to_format, options,
                                output_dir=output_dir, image_dir_name=image_dir_name)
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
        discard_links: bool = False,
        site_cleanup: bool | None = None,
        pdf_mode: str = "text",
    ) -> str:
        """Convert a document and save it to a file.

        Args:
            source: Source text content, file path, or remote URL (e.g., http:// or https://).
            output_path: Full output file path (format inferred from extension).
            template: Rendering template name (default: 'plain').
            image_handling: Image handling strategy ('auto', 'describe', 'embed', 'link', 'discard').
            code_parsing: If True, enables heuristic code block detection.
            extract_html: If True, filters noise and extracts main content from HTML.
            discard_links: If True, replaces every hyperlink with its visible text.
            site_cleanup: Override for site-specific HTML cleanup (e.g. Wikipedia) during
                extract_html. None uses the config default; False disables it.
            pdf_mode: How to read PDF input: 'text' (its text layer) or 'raster'
                (every page rendered and transcribed by the AI describer).

        Returns:
            Confirmation message with the output path.
        """
        try:
            from textconverter.api import save_to_file
            from textconverter.options import ConvertOptions
            save_to_file(source, output_path, ConvertOptions(
                template=template,
                image_handling=image_handling,
                code_parsing=code_parsing,
                extract_html=extract_html,
                discard_links=discard_links,
                site_cleanup=site_cleanup,
                pdf_mode=pdf_mode,
            ))
            return f"Successfully saved to {output_path}"
        except Exception as exc:
            return f"Error: {exc}"
