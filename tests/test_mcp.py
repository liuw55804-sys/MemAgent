from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from memagent.mcp import MCP_PROTOCOL_VERSION, McpServer, run_stdio_server, tool_definitions


class McpServerTest(unittest.TestCase):
    def test_initialize_and_tools_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = McpServer.from_home_arg(tmp, "/tmp/memagent")
            init_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"},
                    },
                }
            )
            self.assertIsNotNone(init_response)
            self.assertEqual(init_response["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)
            self.assertIn("tools", init_response["result"]["capabilities"])

            tools_response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            names = [tool["name"] for tool in tools_response["result"]["tools"]]
            self.assertEqual(
                names,
                [
                    "memagent_recall",
                    "memagent_remember",
                    "memagent_agents_doctor",
                    "memagent_handoff_save",
                    "memagent_handoff_show",
                ],
            )

    def test_tool_definitions_have_valid_basic_schema(self) -> None:
        for tool in tool_definitions():
            self.assertIn("name", tool)
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertIn("properties", tool["inputSchema"])

    def test_remember_and_recall_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            server = McpServer.from_home_arg(str(Path(tmp) / "home"), "/tmp/memagent")
            remember_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_remember",
                        "arguments": {
                            "text": "Use id ranges before attribution accuracy aggregation.",
                            "topic": "Attribution accuracy pitfall",
                            "kind": "pitfall",
                            "triggers": ["attribution", "accuracy"],
                            "cwd": str(project),
                        },
                    },
                }
            )
            self.assertFalse(remember_response["result"]["isError"])
            self.assertIn("Saved memory", remember_response["result"]["content"][0]["text"])

            recall_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_recall",
                        "arguments": {
                            "query": "attribution accuracy",
                            "cwd": str(project),
                            "strategy": "bm25",
                        },
                    },
                }
            )
            text = recall_response["result"]["content"][0]["text"]
            self.assertIn("Attribution accuracy pitfall", text)
            self.assertIn("strategy=bm25", text)
            self.assertIn("matched=attribution, accuracy", text)

    def test_handoff_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            server = McpServer.from_home_arg(str(Path(tmp) / "home"), "/tmp/memagent")
            save_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_handoff_save",
                        "arguments": {
                            "summary": "Saved MCP handoff and should show it later.",
                            "topic": "MCP handoff",
                            "done": ["Added handoff tool."],
                            "next_steps": ["Run MCP tests."],
                            "cwd": str(project),
                        },
                    },
                }
            )
            self.assertFalse(save_response["result"]["isError"])
            self.assertIn("handoff saved", save_response["result"]["content"][0]["text"])

            show_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_handoff_show",
                        "arguments": {
                            "cwd": str(project),
                            "max_lines": 25,
                        },
                    },
                }
            )
            text = show_response["result"]["content"][0]["text"]
            self.assertIn("MCP handoff", text)
            self.assertIn("Run MCP tests", text)

    def test_stdio_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = McpServer.from_home_arg(tmp, "/tmp/memagent")
            stdin = StringIO(
                "\n".join(
                    [
                        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                    ]
                )
                + "\n"
            )
            stdout = StringIO()
            exit_code = run_stdio_server(server, stdin=stdin, stdout=stdout)
            self.assertEqual(exit_code, 0)
            lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)
            self.assertEqual(lines[1]["result"]["tools"][0]["name"], "memagent_recall")

    def test_invalid_tool_call_returns_tool_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = McpServer.from_home_arg(tmp, "/tmp/memagent")
            response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_recall",
                        "arguments": {},
                    },
                }
            )
            self.assertTrue(response["result"]["isError"])
            self.assertIn("missing required string argument", response["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
