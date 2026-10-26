"""The MCP tools, called in-process through MCPServer.

Usage: python -m unittest discover -s tests -p "test_mcp.py"
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from _support import BaseConverterTest, setUpModule, tearDownModule, INPUT_DIR


class TestMcpTools(BaseConverterTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from mcp.server.mcpserver import MCPServer
        from textconverter.mcp_tools import register_tools
        cls.server = MCPServer("TextConverter")
        register_tools(cls.server)

    def _call(self, name: str, **arguments) -> str:
        result = asyncio.run(self.server.call_tool(name, arguments))
        return result.content[0].text

    def test_tool_names(self):
        tools = asyncio.run(self.server.list_tools())
        self.assertEqual({t.name for t in tools},
                         {"textconverter_convert_text", "textconverter_convert_file", "textconverter_save_file"})

    def test_convert_text(self):
        html = self._call("textconverter_convert_text", text="# Title", from_format="markdown",
                          to_format="html", template="dark")
        self.assertIn("<h1>Title</h1>", html)

    def test_convert_file(self):
        md = self._call("textconverter_convert_file", source=str(INPUT_DIR / "SampleLatex.tex"),
                        to_format="markdown")
        self.assertTrue(md.strip())

    def test_save_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.html"
            message = self._call("textconverter_save_file", source=str(INPUT_DIR / "SampleMD.md"),
                                 output_path=str(out))
            self.assertIn(str(out), message)
            self.assertTrue(out.exists())

    def test_errors_are_tool_errors_with_the_message(self):
        """A failure reaches the client as isError with a readable message, not as a document."""
        from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
        cases = [
            ("textconverter_convert_text", {"text": "# a", "from_format": "markdown", "to_format": "md"}, "to_format"),
            ("textconverter_convert_text", {"text": "# a", "from_format": "markdown", "to_format": "html",
                                            "template": "drak"}, "template"),
            ("textconverter_convert_file", {"source": "no/such.md", "to_format": "html"}, "FileNotFoundError"),
        ]
        for name, arguments, expected in cases:
            with self.subTest(name=name, expected=expected):
                with self.assertRaises(ToolError) as ctx:
                    asyncio.run(self.server.call_tool(name, arguments))
                self.assertNotIsInstance(ctx.exception, UnexpectedToolError)
                self.assertIn(expected, str(ctx.exception))
