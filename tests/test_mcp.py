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
                    "memagent_handoff_draft",
                    "memagent_handoff_promote",
                    "memagent_trace_list",
                    "memagent_trace_show",
                    "memagent_trace_label",
                    "memagent_trace_report",
                    "memagent_trace_eval",
                ],
            )

    def test_tool_definitions_have_valid_basic_schema(self) -> None:
        for tool in tool_definitions():
            self.assertIn("name", tool)
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertIn("properties", tool["inputSchema"])
            self.assertEqual(
                set(tool["annotations"]),
                {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"},
            )
            self.assertFalse(tool["annotations"]["destructiveHint"])
            self.assertFalse(tool["annotations"]["openWorldHint"])

    def test_tool_annotations_classify_read_and_write_tools(self) -> None:
        tools = {tool["name"]: tool for tool in tool_definitions()}
        read_only_tools = {
            "memagent_recall",
            "memagent_agents_doctor",
            "memagent_handoff_show",
            "memagent_trace_list",
            "memagent_trace_show",
            "memagent_trace_report",
        }
        idempotent_tools = {
            "memagent_recall",
            "memagent_agents_doctor",
            "memagent_handoff_show",
            "memagent_trace_list",
            "memagent_trace_show",
            "memagent_trace_report",
            "memagent_trace_eval",
        }
        write_capable_tools = set(tools) - read_only_tools

        for name in read_only_tools:
            annotations = tools[name]["annotations"]
            self.assertTrue(annotations["readOnlyHint"])

        for name in write_capable_tools:
            annotations = tools[name]["annotations"]
            self.assertFalse(annotations["readOnlyHint"])

        for name in idempotent_tools:
            annotations = tools[name]["annotations"]
            self.assertTrue(annotations["idempotentHint"])

        for name in set(tools) - idempotent_tools:
            annotations = tools[name]["annotations"]
            self.assertFalse(annotations["idempotentHint"])

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

            json_recall_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_recall",
                        "arguments": {
                            "query": "attribution accuracy",
                            "cwd": str(project),
                            "strategy": "bm25",
                            "format": "json",
                        },
                    },
                }
            )
            payload = json.loads(json_recall_response["result"]["content"][0]["text"])
            self.assertEqual(payload["schema_version"], "memagent.recall.v1")
            self.assertEqual(payload["matches"][0]["title"], "Attribution accuracy pitfall")
            self.assertIn("text", payload)

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

    def test_handoff_draft_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            server = McpServer.from_home_arg(str(Path(tmp) / "home"), "/tmp/memagent")
            response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_handoff_draft",
                        "arguments": {
                            "text": "\n".join(
                                [
                                    "## Summary",
                                    "Drafted MCP handoff.",
                                    "",
                                    "## Done",
                                    "- Added MCP draft tool.",
                                    "",
                                    "## Next Steps",
                                    "- Run full tests.",
                                ]
                            ),
                            "save": True,
                            "cwd": str(project),
                        },
                    },
                }
            )
            text = response["result"]["content"][0]["text"]
            self.assertIn("[MemAgent handoff draft]", text)
            self.assertIn("Added MCP draft tool.", text)
            self.assertIn("[MemAgent handoff saved]", text)

    def test_handoff_promote_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            home = Path(tmp) / "home"
            server = McpServer.from_home_arg(str(home), "/tmp/memagent")
            server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_handoff_save",
                        "arguments": {
                            "summary": "Promotion source handoff.",
                            "topic": "Promotion",
                            "memory_candidates": ["MCP promotion should create memory."],
                            "cwd": str(project),
                        },
                    },
                }
            )
            response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_handoff_promote",
                        "arguments": {
                            "cwd": str(project),
                            "indices": [1],
                            "write": True,
                        },
                    },
                }
            )
            text = response["result"]["content"][0]["text"]
            self.assertIn("MCP promotion should create memory", text)
            self.assertIn("Status: promoted", text)
            self.assertEqual(len(list((home / "memories").glob("*.memory.yaml"))), 1)

    def test_trace_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            server = McpServer.from_home_arg(str(home), "/tmp/memagent")
            saved = server.store.save_recall_trace(
                {
                    "schema_version": "memagent.recall.v1",
                    "query": "MCP trace query",
                    "context": {"repo_name": "demo", "cwd": str(Path(tmp) / "project")},
                    "total_matches": 1,
                    "matches": [{"title": "MCP trace memory"}],
                    "pack": {"emitted_matches": 1},
                    "text": "[MemAgent recalled context]\n- Memory: MCP trace memory",
                },
                source="test",
            )

            list_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_trace_list",
                        "arguments": {"limit": 3},
                    },
                }
            )
            self.assertIn("MCP trace memory", list_response["result"]["content"][0]["text"])

            show_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_trace_show",
                        "arguments": {"identifier": saved.identifier, "format": "json"},
                    },
                }
            )
            payload = json.loads(show_response["result"]["content"][0]["text"])
            self.assertEqual(payload["trace"]["id"], saved.identifier)

            label_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_trace_label",
                        "arguments": {
                            "identifier": saved.identifier,
                            "rating": "useful",
                            "note": "MCP label works.",
                        },
                    },
                }
            )
            self.assertIn("rating: useful", label_response["result"]["content"][0]["text"])

            report_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_trace_report",
                        "arguments": {"limit": 5},
                    },
                }
            )
            self.assertIn("useful_rate: 1.00", report_response["result"]["content"][0]["text"])

            eval_workspace = Path(tmp) / "trace_eval"
            eval_response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {
                        "name": "memagent_trace_eval",
                        "arguments": {"workspace": str(eval_workspace), "limit": 5},
                    },
                }
            )
            self.assertIn("[MemAgent trace-eval]", eval_response["result"]["content"][0]["text"])
            self.assertTrue((eval_workspace / "report.md").exists())

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
