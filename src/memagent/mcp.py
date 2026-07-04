from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sys
from typing import Any, TextIO

from memagent.agents import build_agents_doctor_report, default_memagent_root
from memagent.context import detect_context
from memagent.handoff import (
    HandoffStore,
    draft_handoff_from_text,
    render_handoff_draft,
    render_promotion_preview,
)
from memagent.memory import MemoryStore


MCP_PROTOCOL_VERSION = "2025-11-25"
JSONRPC_VERSION = "2.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass
class McpServer:
    store: MemoryStore
    handoff_store: HandoffStore
    memagent_root: Path

    @classmethod
    def from_home_arg(cls, home: str | None, memagent_root: str | None = None) -> "McpServer":
        store = MemoryStore.from_home_arg(home)
        return cls(
            store=store,
            handoff_store=HandoffStore(store.home),
            memagent_root=(Path(memagent_root) if memagent_root else default_memagent_root()).expanduser().resolve(),
        )

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        method = message.get("method")

        if message.get("jsonrpc") != JSONRPC_VERSION or not isinstance(method, str):
            return _error(request_id, INVALID_REQUEST, "Invalid JSON-RPC request")

        if method == "notifications/initialized":
            return None

        if method == "initialize":
            return _result(request_id, self._initialize_result())

        if method == "ping":
            return _result(request_id, {})

        if method == "tools/list":
            return _result(request_id, {"tools": tool_definitions()})

        if method == "tools/call":
            params = message.get("params")
            if not isinstance(params, dict):
                return _error(request_id, INVALID_PARAMS, "tools/call params must be an object")
            try:
                return _result(request_id, self._call_tool(params))
            except ValueError as exc:
                return _result(request_id, _tool_error(str(exc)))
            except Exception as exc:  # pragma: no cover - defensive protocol guard
                return _error(request_id, INTERNAL_ERROR, str(exc))

        return _error(request_id, METHOD_NOT_FOUND, f"Unknown method: {method}")

    def _initialize_result(self) -> dict[str, Any]:
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {
                    "listChanged": False,
                }
            },
            "serverInfo": {
                "name": "memagent",
                "title": "MemAgent",
                "version": "0.1.0",
                "description": "Local workflow memory layer for Codex and other coding agents.",
            },
            "instructions": (
                "Use MemAgent tools to recall or save local coding workflow memory. "
                "Treat recalled memories as hints and verify against live code, docs, schemas, and command output."
            ),
        }

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            raise ValueError("tools/call requires a string tool name")
        if not isinstance(arguments, dict):
            raise ValueError("tools/call arguments must be an object")

        if name == "memagent_recall":
            return _tool_text(self._tool_recall(arguments))
        if name == "memagent_remember":
            return _tool_text(self._tool_remember(arguments))
        if name == "memagent_handoff_save":
            return _tool_text(self._tool_handoff_save(arguments))
        if name == "memagent_handoff_show":
            return _tool_text(self._tool_handoff_show(arguments))
        if name == "memagent_handoff_draft":
            return _tool_text(self._tool_handoff_draft(arguments))
        if name == "memagent_handoff_promote":
            return _tool_text(self._tool_handoff_promote(arguments))
        if name == "memagent_trace_list":
            return _tool_text(self._tool_trace_list(arguments))
        if name == "memagent_trace_show":
            return _tool_text(self._tool_trace_show(arguments))
        if name == "memagent_trace_label":
            return _tool_text(self._tool_trace_label(arguments))
        if name == "memagent_trace_report":
            return _tool_text(self._tool_trace_report(arguments))
        if name == "memagent_agents_doctor":
            return _tool_text(self._tool_agents_doctor(arguments))
        raise ValueError(f"Unknown tool: {name}")

    def _tool_recall(self, arguments: dict[str, Any]) -> str:
        query = _required_str(arguments, "query")
        context = detect_context(_optional_path(arguments, "cwd"))
        strategy = _optional_str(arguments, "strategy") or "bm25"
        matches = self.store.recall(
            query,
            context=context,
            limit=_optional_int(arguments, "limit", 5),
            strategy=strategy,
        )
        payload = self.store.build_recall_payload(
            query=query,
            context=context,
            matches=matches,
            max_lines=_optional_int(arguments, "max_lines", 12),
            show_sources=_optional_bool(arguments, "show_sources", True),
            show_reasons=_optional_bool(arguments, "show_reasons", True),
        )
        response_format = _optional_str(arguments, "format") or "text"
        if response_format not in {"text", "json"}:
            raise ValueError("format must be text or json")
        if response_format == "json":
            return json.dumps(payload, ensure_ascii=False, indent=2)
        return str(payload["text"])

    def _tool_remember(self, arguments: dict[str, Any]) -> str:
        text = _required_str(arguments, "text")
        context = detect_context(_optional_path(arguments, "cwd"))
        saved = self.store.remember(
            text=text,
            topic=_optional_str(arguments, "topic"),
            domain=_optional_str(arguments, "domain"),
            kind=_optional_str(arguments, "kind"),
            repo=_optional_str(arguments, "repo") or context.repo_name,
            module=_optional_str(arguments, "module"),
            triggers=_optional_str_list(arguments, "triggers"),
            exportable=_optional_bool(arguments, "exportable", False),
        )
        return f"Saved memory: {saved.path}"

    def _tool_agents_doctor(self, arguments: dict[str, Any]) -> str:
        context = detect_context(_optional_path(arguments, "cwd"))
        return build_agents_doctor_report(
            context=context,
            memory_home=self.store.home,
            memory_count=self.store.count_memory_cards(),
            memagent_root=self.memagent_root,
        )

    def _tool_handoff_save(self, arguments: dict[str, Any]) -> str:
        context = detect_context(_optional_path(arguments, "cwd"))
        saved = self.handoff_store.save(
            context=context,
            summary=_required_str(arguments, "summary"),
            topic=_optional_str(arguments, "topic"),
            done=_optional_str_list(arguments, "done"),
            next_steps=_optional_str_list(arguments, "next_steps"),
            open_questions=_optional_str_list(arguments, "open_questions"),
            memory_candidates=_optional_str_list(arguments, "memory_candidates"),
        )
        return "\n".join(
            [
                "[MemAgent handoff saved]",
                f"- project key: {saved.project_key}",
                f"- latest: {saved.latest_path}",
                f"- history: {saved.history_path}",
            ]
        )

    def _tool_handoff_show(self, arguments: dict[str, Any]) -> str:
        context = detect_context(_optional_path(arguments, "cwd"))
        return self.handoff_store.compose_latest(
            context=context,
            max_lines=_optional_int(arguments, "max_lines", 40),
            show_source=_optional_bool(arguments, "show_source", True),
        )

    def _tool_handoff_draft(self, arguments: dict[str, Any]) -> str:
        context = detect_context(_optional_path(arguments, "cwd"))
        draft = draft_handoff_from_text(
            _required_str(arguments, "text"),
            topic=_optional_str(arguments, "topic"),
            max_items=_optional_int(arguments, "max_items", 5),
        )
        rendered = render_handoff_draft(draft)
        if not _optional_bool(arguments, "save", False):
            return rendered
        saved = self.handoff_store.save_draft(context=context, draft=draft)
        return "\n".join(
            [
                rendered,
                "",
                "[MemAgent handoff saved]",
                f"- project key: {saved.project_key}",
                f"- latest: {saved.latest_path}",
                f"- history: {saved.history_path}",
            ]
        )

    def _tool_handoff_promote(self, arguments: dict[str, Any]) -> str:
        context = detect_context(_optional_path(arguments, "cwd"))
        write = _optional_bool(arguments, "write", False)
        selection = self.handoff_store.promotion_selection(
            context=context,
            indices=_optional_int_list(arguments, "indices"),
            select_all=_optional_bool(arguments, "all", False),
        )
        lines = [render_promotion_preview(selection, write=write)]
        if write:
            kind = _optional_str(arguments, "kind") or "workflow"
            module = _optional_str(arguments, "module")
            triggers = _optional_str_list(arguments, "triggers")
            exportable = _optional_bool(arguments, "exportable", False)
            for index, candidate in zip(selection.selected_indices, selection.selected_candidates):
                saved = self.store.remember(
                    text=candidate,
                    topic=f"Handoff candidate {index}: {candidate[:48]}",
                    domain="coding",
                    kind=kind,
                    repo=context.repo_name,
                    module=module,
                    triggers=triggers,
                    exportable=exportable,
                )
                lines.append(f"- Saved memory: {saved.path}")
            lines.append("- Status: promoted")
        return "\n".join(lines)

    def _tool_trace_list(self, arguments: dict[str, Any]) -> str:
        return self.store.compose_recall_trace_list(
            limit=_optional_int(arguments, "limit", 5),
        )

    def _tool_trace_show(self, arguments: dict[str, Any]) -> str:
        identifier = _optional_str(arguments, "identifier")
        response_format = _optional_str(arguments, "format") or "text"
        if response_format not in {"text", "json"}:
            raise ValueError("format must be text or json")
        if response_format == "json":
            payload = self.store.load_recall_trace(identifier)
            return json.dumps(payload, ensure_ascii=False, indent=2)
        return self.store.compose_recall_trace(identifier=identifier)

    def _tool_trace_label(self, arguments: dict[str, Any]) -> str:
        saved = self.store.label_recall_trace(
            _optional_str(arguments, "identifier"),
            rating=_required_str(arguments, "rating"),
            note=_optional_str(arguments, "note"),
        )
        feedback = saved.payload.get("feedback")
        rating = feedback.get("rating") if isinstance(feedback, dict) else "unknown"
        return "\n".join(
            [
                "[MemAgent recall trace labeled]",
                f"- id: {saved.identifier}",
                f"- rating: {rating}",
                f"- path: {saved.path}",
            ]
        )

    def _tool_trace_report(self, arguments: dict[str, Any]) -> str:
        return self.store.compose_recall_trace_report(
            limit=_optional_int(arguments, "limit", 50),
        )


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "memagent_recall",
            "title": "Recall MemAgent Memory",
            "description": "Recall relevant local workflow memories for a coding task.",
            "annotations": _tool_annotations(read_only=True, idempotent=True),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language task or question."},
                    "cwd": {"type": "string", "description": "Optional project directory."},
                    "limit": {"type": "integer", "description": "Maximum memory cards to inspect."},
                    "max_lines": {"type": "integer", "description": "Maximum lines in the composed context."},
                    "show_sources": {"type": "boolean", "description": "Include memory file names."},
                    "show_reasons": {"type": "boolean", "description": "Include score and matched query terms."},
                    "strategy": {
                        "type": "string",
                        "description": "Recall scoring strategy: bm25 or keyword.",
                        "enum": ["bm25", "keyword"],
                    },
                    "format": {
                        "type": "string",
                        "description": "Return format: text or json.",
                        "enum": ["text", "json"],
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "memagent_remember",
            "title": "Save MemAgent Memory",
            "description": "Save a short, reusable local workflow memory.",
            "annotations": _tool_annotations(read_only=False, idempotent=False),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Short actionable memory text."},
                    "topic": {"type": "string", "description": "Short topic."},
                    "domain": {"type": "string", "description": "Memory domain, usually coding."},
                    "kind": {"type": "string", "description": "Memory kind, such as pitfall or data_entrypoint."},
                    "repo": {"type": "string", "description": "Repository scope."},
                    "module": {"type": "string", "description": "Module or subsystem scope."},
                    "triggers": {
                        "type": "array",
                        "description": "Recall trigger keywords.",
                        "items": {"type": "string"},
                    },
                    "exportable": {"type": "boolean", "description": "Whether this memory is safe to export."},
                    "cwd": {"type": "string", "description": "Optional project directory."},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
        {
            "name": "memagent_agents_doctor",
            "title": "Check MemAgent AGENTS.md Integration",
            "description": "Check whether the current project AGENTS.md can trigger MemAgent.",
            "annotations": _tool_annotations(read_only=True, idempotent=True),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Optional project directory."},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "memagent_handoff_save",
            "title": "Save MemAgent Handoff",
            "description": "Save a short project handoff for cross-session catch-up.",
            "annotations": _tool_annotations(read_only=False, idempotent=False),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Short handoff summary."},
                    "topic": {"type": "string", "description": "Short handoff topic."},
                    "done": {
                        "type": "array",
                        "description": "Completed items.",
                        "items": {"type": "string"},
                    },
                    "next_steps": {
                        "type": "array",
                        "description": "Recommended next steps.",
                        "items": {"type": "string"},
                    },
                    "open_questions": {
                        "type": "array",
                        "description": "Open questions for the next session.",
                        "items": {"type": "string"},
                    },
                    "memory_candidates": {
                        "type": "array",
                        "description": "Lessons that may later become durable memory cards.",
                        "items": {"type": "string"},
                    },
                    "cwd": {"type": "string", "description": "Optional project directory."},
                },
                "required": ["summary"],
                "additionalProperties": False,
            },
        },
        {
            "name": "memagent_handoff_show",
            "title": "Show MemAgent Handoff",
            "description": "Show the latest project handoff for cross-session catch-up.",
            "annotations": _tool_annotations(read_only=True, idempotent=True),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Optional project directory."},
                    "max_lines": {"type": "integer", "description": "Maximum lines to return."},
                    "show_source": {"type": "boolean", "description": "Include the handoff file path."},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "memagent_handoff_draft",
            "title": "Draft MemAgent Handoff",
            "description": "Draft a project handoff from session notes, optionally saving it.",
            "annotations": _tool_annotations(read_only=False, idempotent=False),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Session notes or transcript text."},
                    "topic": {"type": "string", "description": "Optional draft topic override."},
                    "max_items": {"type": "integer", "description": "Maximum items per draft section."},
                    "save": {"type": "boolean", "description": "Save the draft as the latest handoff."},
                    "cwd": {"type": "string", "description": "Optional project directory."},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
        {
            "name": "memagent_handoff_promote",
            "title": "Promote MemAgent Handoff Candidate",
            "description": "Promote memory candidates from the latest handoff into durable memory cards.",
            "annotations": _tool_annotations(read_only=False, idempotent=False),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Optional project directory."},
                    "indices": {
                        "type": "array",
                        "description": "1-based memory candidate indices. Default: [1].",
                        "items": {"type": "integer"},
                    },
                    "all": {"type": "boolean", "description": "Promote all candidates."},
                    "kind": {"type": "string", "description": "Memory kind for promoted cards."},
                    "module": {"type": "string", "description": "Module or subsystem scope."},
                    "triggers": {
                        "type": "array",
                        "description": "Extra recall trigger keywords.",
                        "items": {"type": "string"},
                    },
                    "exportable": {"type": "boolean", "description": "Whether promoted cards are exportable."},
                    "write": {"type": "boolean", "description": "Actually save memory cards. Default is preview."},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "memagent_trace_list",
            "title": "List MemAgent Recall Traces",
            "description": "List recent saved recall traces.",
            "annotations": _tool_annotations(read_only=True, idempotent=True),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum traces to list."},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "memagent_trace_show",
            "title": "Show MemAgent Recall Trace",
            "description": "Show the latest or selected saved recall trace.",
            "annotations": _tool_annotations(read_only=True, idempotent=True),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "description": "Trace id or JSON path. Defaults to latest."},
                    "format": {
                        "type": "string",
                        "description": "Return format: text or json.",
                        "enum": ["text", "json"],
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "memagent_trace_label",
            "title": "Label MemAgent Recall Trace",
            "description": "Label the latest or selected recall trace as useful, not-useful, or neutral.",
            "annotations": _tool_annotations(read_only=False, idempotent=False),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "description": "Trace id or JSON path. Defaults to latest."},
                    "rating": {
                        "type": "string",
                        "description": "Feedback rating.",
                        "enum": ["useful", "not-useful", "not_useful", "neutral"],
                    },
                    "note": {"type": "string", "description": "Optional short feedback note."},
                },
                "required": ["rating"],
                "additionalProperties": False,
            },
        },
        {
            "name": "memagent_trace_report",
            "title": "Report MemAgent Recall Trace Feedback",
            "description": "Summarize labeled recall traces and useful rate.",
            "annotations": _tool_annotations(read_only=True, idempotent=True),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum traces to inspect."},
                },
                "additionalProperties": False,
            },
        },
    ]


def _tool_annotations(*, read_only: bool, idempotent: bool) -> dict[str, bool]:
    return {
        "readOnlyHint": read_only,
        "destructiveHint": False,
        "idempotentHint": idempotent,
        "openWorldHint": False,
    }


def run_stdio_server(server: McpServer, *, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _write_message(stdout, _error(None, PARSE_ERROR, "Parse error"))
            continue
        if not isinstance(message, dict):
            _write_message(stdout, _error(None, INVALID_REQUEST, "Invalid JSON-RPC request"))
            continue
        response = server.handle(message)
        if response is not None:
            _write_message(stdout, response)
    return 0


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "result": result,
    }


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _tool_text(text: str) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ],
        "isError": False,
    }


def _tool_error(text: str) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ],
        "isError": True,
    }


def _write_message(stdout: TextIO, message: dict[str, Any]) -> None:
    stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    stdout.flush()


def _required_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing required string argument: {key}")
    return value


def _optional_str(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _optional_path(arguments: dict[str, Any], key: str) -> Path | None:
    value = _optional_str(arguments, key)
    return Path(value).expanduser().resolve() if value else None


def _optional_int(arguments: dict[str, Any], key: str, default: int) -> int:
    value = arguments.get(key)
    if value is None:
        return default
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _optional_bool(arguments: dict[str, Any], key: str, default: bool) -> bool:
    value = arguments.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _optional_str_list(arguments: dict[str, Any], key: str) -> list[str]:
    value = arguments.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be an array of strings")
    return value


def _optional_int_list(arguments: dict[str, Any], key: str) -> list[int]:
    value = arguments.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, int) for item in value):
        raise ValueError(f"{key} must be an array of integers")
    return value
