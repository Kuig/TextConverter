from __future__ import annotations
from pathlib import Path
import argparse
import subprocess
import sys

from textconverter.api import save_to_file
from textconverter.logger import log_success, log_error


def cmd_convert(args: argparse.Namespace) -> None:
    """Handle the convert subcommand.

    Args:
        args: Parsed argument namespace.
    """
    try:
        save_to_file(
            args.source,
            args.output,
            template=args.template,
            image_handling=args.image_handling,
            code_parsing=args.code_parsing,
            extract_html=args.extract_html,
        )
        log_success(f"Saved to {args.output}")
    except Exception as exc:
        log_error(f"Error: {exc}")
        sys.exit(1)


def cmd_mcp(args: argparse.Namespace) -> None:
    """Handle the mcp subcommand — start the FastMCP server on stdio.

    Args:
        args: Parsed argument namespace (unused).
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        log_error("'mcp' library not installed. Run: pip install mcp")
        sys.exit(1)
    from textconverter.mcp_tools import register_tools
    mcp = FastMCP("TextConverter")
    register_tools(mcp)
    mcp.run()


def cmd_gui(args: argparse.Namespace) -> None:
    """Handle the gui subcommand — launch the Streamlit web interface.

    Args:
        args: Parsed argument namespace (unused).
    """
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(Path(__file__).parent / "gui" / "app.py")])


def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser with subcommands.

    Returns:
        Configured argparse.ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="textconverter",
        description="TextConverter — Multi-format document conversion tool.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_convert = subparsers.add_parser("convert", help="Convert and save a document.")
    p_convert.add_argument("source", help="Source file path or remote URL (e.g., http:// or https://).")
    p_convert.add_argument("output", help="Output file path (format inferred from extension).")
    p_convert.add_argument("--template", default="plain", help="Rendering template (default: plain).")
    p_convert.add_argument(
        "--image-handling",
        default="auto",
        choices=["auto", "describe", "embed", "link", "discard"],
        help="Image handling strategy.",
    )
    p_convert.add_argument("--code-parsing", action="store_true", help="Enable AI-assisted code block detection.")
    p_convert.add_argument("--extract-html", action="store_true", help="Filter noise and extract main content from HTML.")
    p_convert.set_defaults(func=cmd_convert)

    p_mcp = subparsers.add_parser("mcp", help="Start the MCP server on stdio.")
    p_mcp.set_defaults(func=cmd_mcp)

    p_gui = subparsers.add_parser("gui", help="Launch Streamlit web interface.")
    p_gui.set_defaults(func=cmd_gui)

    return parser


def main() -> None:
    """Main entry point for the TextConverter CLI."""
    try:
        from unified_ai_client import silence_sdks
        silence_sdks()
    except ImportError:
        pass
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
