from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import shutil
import shlex
import subprocess

from memagent.agents import (
    build_agents_doctor_report,
    build_agents_install_plan,
    default_memagent_root,
    render_agents_install_report,
    write_agents_install_plan,
)
from memagent.context import detect_context
from memagent.eval import RecallEvalResult, run_recall_eval, run_trace_eval, run_trace_replay
from memagent.handoff import (
    HandoffStore,
    draft_handoff_from_text,
    render_handoff_draft,
    render_promotion_preview,
)
from memagent.ingest import run_codex_ingest
from memagent.memory import MemoryStore
from memagent.mcp import MCP_PROTOCOL_VERSION, McpServer, tool_definitions
from memagent.wrapper import build_augmented_prompt


DEMO_QUERY = "先看看之前有没有 validation accuracy 的相关经验"
DEMO_CODEX_PROMPT = "我要继续排查 demo 服务 validation accuracy，先给我一个排查计划"
DEMO_MEMORY = (
    "For demo validation accuracy checks, start from the audit_label snapshot "
    "table, sample by primary-key ranges, then compare model output with "
    "human-reviewed labels. Avoid full-table JSON aggregation before sampling."
)
DEMO_HANDOFF = (
    "Demo session wired AGENTS.md, saved one validation accuracy memory, and "
    "verified recall plus Codex prompt patch. Next session should extend the "
    "demo with handoff/catch-up before adding automatic hooks."
)
DEMO_SESSION_NOTES = "\n".join(
    [
        "## Summary",
        DEMO_HANDOFF,
        "",
        "## Done",
        "- Installed MemAgent AGENTS.md block.",
        "- Saved one mock validation accuracy memory.",
        "- Verified recall with sources and reasons.",
        "",
        "## Next Steps",
        "- Use the handoff as the next-session catch-up context.",
        "- Decide whether the mock workflow should become a durable memory card.",
        "",
        "## Open Questions",
        "- Should handoff drafts be generated automatically from session logs?",
        "",
        "## Memory Candidates",
        "- Codex demos benefit from showing handoff before recall.",
    ]
)
DEMO_CODEX_SESSION_RECORDS = (
    {
        "type": "session_meta",
        "timestamp": "2026-07-04T00:00:00Z",
        "payload": {
            "type": "session_meta",
            "id": "demo-codex-session",
            "cwd": "{project_dir}",
            "git": {"root": "{project_dir}"},
        },
    },
    {
        "type": "event_msg",
        "timestamp": "2026-07-04T00:01:00Z",
        "payload": {
            "type": "exec_command",
            "cwd": "{project_dir}",
            "command": "git database query --db demo_project --sql 'select case_id, maintainer from example_snapshot limit 20'",
            "exit_code": 0,
        },
    },
    {
        "type": "response_item",
        "timestamp": "2026-07-04T00:02:00Z",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "沉淀一下：下次做 validation accuracy demo 时，先展示 Codex transcript ingest 生成候选记忆，再由用户决定是否 remember。",
                }
            ],
        },
    },
    {
        "type": "event_msg",
        "timestamp": "2026-07-04T00:03:00Z",
        "payload": {
            "type": "exec_command",
            "cwd": "{project_dir}",
            "command": "memagent trace replay --limit 10",
            "exit_code": 0,
        },
    },
)


@dataclass(frozen=True)
class DemoStep:
    title: str
    command: str
    output: str


@dataclass(frozen=True)
class DemoRunResult:
    workspace: Path
    project_dir: Path
    memory_home: Path
    transcript_path: Path
    transcript: str
    steps: tuple[DemoStep, ...]


@dataclass(frozen=True)
class DemoBundleResult:
    workspace: Path
    report_path: Path
    report: str
    demo: DemoRunResult
    recall_eval: RecallEvalResult
    mcp_demo: "McpDemoResult"
    mcp_tool_count: int


@dataclass(frozen=True)
class McpDemoExchange:
    title: str
    request: dict[str, object]
    response: dict[str, object] | None


@dataclass(frozen=True)
class McpDemoResult:
    workspace: Path
    project_dir: Path
    memory_home: Path
    transcript_path: Path
    transcript: str
    exchanges: tuple[McpDemoExchange, ...]
    seeded_trace_id: str
    trace_eval_report_path: Path
    trace_replay_report_path: Path


def run_demo(
    *,
    workspace: Path,
    memagent_root: Path | None = None,
    reset: bool = False,
) -> DemoRunResult:
    root = (memagent_root or default_memagent_root()).expanduser().resolve()
    workspace = workspace.expanduser().resolve()
    if reset and workspace.exists():
        shutil.rmtree(workspace)

    project_dir = workspace / "project"
    memory_home = workspace / "memagent_home"
    project_dir.mkdir(parents=True, exist_ok=True)
    memory_home.mkdir(parents=True, exist_ok=True)
    _ensure_demo_project(project_dir)

    store = MemoryStore(memory_home)
    handoff_store = HandoffStore(memory_home)
    command_prefix = _command_prefix(root=root, memory_home=memory_home)

    steps: list[DemoStep] = []

    install_context = detect_context(project_dir)
    install_plan = build_agents_install_plan(
        context=install_context,
        target=project_dir / "AGENTS.md",
        memagent_root=root,
    )
    write_agents_install_plan(install_plan)
    steps.append(
        DemoStep(
            title="Install MemAgent AGENTS.md block",
            command=f"{command_prefix} agents-install --cwd {_quote(project_dir)} --write",
            output=render_agents_install_report(install_plan, write=True),
        )
    )

    doctor_context = detect_context(project_dir)
    steps.append(
        DemoStep(
            title="Check AGENTS.md integration",
            command=f"{command_prefix} agents-doctor --cwd {_quote(project_dir)}",
            output=build_agents_doctor_report(
                context=doctor_context,
                memory_home=memory_home,
                memory_count=store.count_memory_cards(),
                memagent_root=root,
            ),
        )
    )

    saved = store.remember(
        text=DEMO_MEMORY,
        topic="Demo validation accuracy entrypoint",
        domain="coding",
        kind="data_entrypoint",
        repo="demo_service",
        module="validation",
        triggers=["validation", "accuracy", "audit_label"],
        exportable=True,
    )
    steps.append(
        DemoStep(
            title="Remember a workflow memory",
            command=(
                f"{command_prefix} remember --domain coding --kind data_entrypoint "
                '--repo demo_service --module validation '
                '--topic "Demo validation accuracy entrypoint" '
                "--trigger validation --trigger accuracy --trigger audit_label "
                f"{_quote(DEMO_MEMORY)}"
            ),
            output=f"Saved memory: {saved.path}",
        )
    )

    codex_sessions_root = workspace / "codex_sessions"
    _write_demo_codex_session(codex_sessions_root=codex_sessions_root, project_dir=project_dir)
    ingest_result = run_codex_ingest(
        sessions_root=codex_sessions_root,
        workspace=workspace / "ingest_codex",
        context=detect_context(project_dir),
        limit=5,
        max_candidates=5,
        project_only=True,
    )
    steps.append(
        DemoStep(
            title="Draft memory candidates from Codex transcript",
            command=(
                f"{command_prefix} ingest codex --sessions-root {_quote(codex_sessions_root)} "
                f"--workspace {_quote(workspace / 'ingest_codex')} --cwd {_quote(project_dir)} "
                "--project-only --max-candidates 5"
            ),
            output="\n".join(
                [
                    "[MemAgent codex ingest]",
                    f"- workspace: {ingest_result.workspace}",
                    f"- sessions root: {ingest_result.sessions_root}",
                    f"- sessions scanned: {ingest_result.sessions_scanned}",
                    f"- records scanned: {ingest_result.records_scanned}",
                    f"- candidates: {len(ingest_result.candidates)}",
                    f"- report: {ingest_result.report_path}",
                    f"- candidates dir: {ingest_result.candidates_dir}",
                    "- mode: review-only; no memory cards were written",
                ]
            ),
        )
    )

    recall_context = detect_context(project_dir)
    matches = store.recall(DEMO_QUERY, context=recall_context, limit=5)
    recalled_context = store.compose_context(
        query=DEMO_QUERY,
        context=recall_context,
        matches=matches,
        max_lines=12,
        show_sources=True,
        show_reasons=True,
    )
    steps.append(
        DemoStep(
            title="Recall with sources and reasons",
            command=f"{command_prefix} recall {_quote(DEMO_QUERY)} --show-sources --show-reasons --strategy bm25",
            output=recalled_context,
        )
    )

    structured_recall = store.build_recall_payload(
        query=DEMO_QUERY,
        context=recall_context,
        matches=matches,
        max_lines=12,
        show_sources=True,
        show_reasons=True,
    )
    structured_trace = store.save_recall_trace(structured_recall, source="demo")
    steps.append(
        DemoStep(
            title="Recall as structured JSON",
            command=f"{command_prefix} recall {_quote(DEMO_QUERY)} --show-sources --show-reasons --strategy bm25 --json --trace",
            output=json.dumps(structured_trace.payload, ensure_ascii=False, indent=2),
        )
    )

    steps.append(
        DemoStep(
            title="List saved recall traces",
            command=f"{command_prefix} trace list --limit 3",
            output=store.compose_recall_trace_list(limit=3),
        )
    )

    labeled_trace = store.label_recall_trace(
        structured_trace.identifier,
        rating="useful",
        note="Demo recall found the intended validation memory.",
    )
    steps.append(
        DemoStep(
            title="Label recall trace feedback",
            command=f"{command_prefix} trace label {structured_trace.identifier} --rating useful --note {_quote('Demo recall found the intended validation memory.')}",
            output="\n".join(
                [
                    "[MemAgent recall trace labeled]",
                    f"- id: {labeled_trace.identifier}",
                    "- rating: useful",
                    f"- path: {labeled_trace.path}",
                ]
            ),
        )
    )

    steps.append(
        DemoStep(
            title="Report recall trace feedback",
            command=f"{command_prefix} trace report --limit 10",
            output=store.compose_recall_trace_report(limit=10),
        )
    )

    trace_eval = run_trace_eval(
        store=store,
        workspace=workspace / "trace_eval",
        limit=10,
    )
    steps.append(
        DemoStep(
            title="Write trace feedback evaluation report",
            command=f"{command_prefix} trace eval --workspace {_quote(workspace / 'trace_eval')} --limit 10",
            output="\n".join(
                [
                    "[MemAgent trace-eval]",
                    f"- workspace: {trace_eval.workspace}",
                    f"- memory home: {trace_eval.memory_home}",
                    f"- report: {trace_eval.report_path}",
                    f"- traces inspected: {trace_eval.traces_inspected}",
                    f"- labeled: {trace_eval.labeled}",
                    f"- useful_rate: {trace_eval.useful_rate:.2f}",
                ]
            ),
        )
    )
    trace_replay = run_trace_replay(
        store=store,
        workspace=workspace / "trace_replay",
        limit=10,
    )
    replay_lines = [
        "[MemAgent trace-replay]",
        f"- workspace: {trace_replay.workspace}",
        f"- memory home: {trace_replay.memory_home}",
        f"- report: {trace_replay.report_path}",
        f"- traces inspected: {trace_replay.traces_inspected}",
    ]
    for strategy_result in trace_replay.strategy_results:
        replay_lines.append(
            f"- {strategy_result.strategy}: "
            f"top_stability={strategy_result.top_stability:.2f}; "
            f"useful_top_stability={strategy_result.useful_top_stability:.2f}"
        )
    steps.append(
        DemoStep(
            title="Replay recall traces against retrievers",
            command=f"{command_prefix} trace replay --workspace {_quote(workspace / 'trace_replay')} --limit 10",
            output="\n".join(replay_lines),
        )
    )

    codex_matches = store.recall(DEMO_CODEX_PROMPT, context=recall_context, limit=5)
    codex_context = store.compose_context(
        query=DEMO_CODEX_PROMPT,
        context=recall_context,
        matches=codex_matches,
        max_lines=12,
        show_sources=True,
        show_reasons=True,
    )
    final_prompt = build_augmented_prompt(DEMO_CODEX_PROMPT, codex_context)
    steps.append(
        DemoStep(
            title="Preview Codex prompt patch",
            command=(
                f"{command_prefix} codex --dry-run --show-sources --show-reasons --strategy bm25 "
                f"{_quote(DEMO_CODEX_PROMPT)}"
            ),
            output=final_prompt,
        )
    )

    session_notes_path = workspace / "session_notes.md"
    session_notes_path.write_text(DEMO_SESSION_NOTES, encoding="utf-8")
    handoff_draft = draft_handoff_from_text(
        DEMO_SESSION_NOTES,
        topic="Demo continuation handoff",
    )
    draft_command = (
        f"{command_prefix} handoff draft --from-file {_quote(session_notes_path)} "
        '--topic "Demo continuation handoff"'
    )
    steps.append(
        DemoStep(
            title="Draft session handoff from notes",
            command=draft_command,
            output=render_handoff_draft(handoff_draft, source=session_notes_path),
        )
    )

    saved_handoff = handoff_store.save_draft(
        context=recall_context,
        draft=handoff_draft,
    )
    steps.append(
        DemoStep(
            title="Save drafted session handoff",
            command=f"{draft_command} --save",
            output="\n".join(
                [
                    render_handoff_draft(handoff_draft, source=session_notes_path),
                    "",
                    "[MemAgent handoff saved]",
                    f"- project key: {saved_handoff.project_key}",
                    f"- latest: {saved_handoff.latest_path}",
                    f"- history: {saved_handoff.history_path}",
                ]
            ),
        )
    )

    steps.append(
        DemoStep(
            title="Catch up from latest handoff",
            command=f"{command_prefix} handoff show",
            output=handoff_store.compose_latest(context=recall_context, max_lines=40, show_source=True),
        )
    )

    promotion = handoff_store.promotion_selection(
        context=recall_context,
        indices=[1],
        select_all=False,
    )
    promoted = store.remember(
        text=promotion.selected_candidates[0],
        topic=f"Handoff candidate 1: {promotion.selected_candidates[0][:48]}",
        domain="coding",
        kind="workflow",
        repo=recall_context.repo_name,
        module=None,
        triggers=["handoff", "demo"],
        exportable=True,
    )
    steps.append(
        DemoStep(
            title="Promote handoff memory candidate",
            command=f"{command_prefix} handoff promote --index 1 --kind workflow --trigger handoff --trigger demo --exportable --write",
            output="\n".join(
                [
                    render_promotion_preview(promotion, write=True),
                    f"- Saved memory: {promoted.path}",
                    "- Status: promoted",
                ]
            ),
        )
    )

    promoted_query = "Codex demos benefit from showing handoff before recall"
    promoted_matches = store.recall(promoted_query, context=recall_context, limit=5)
    promoted_context = store.compose_context(
        query=promoted_query,
        context=recall_context,
        matches=promoted_matches,
        max_lines=12,
        show_sources=True,
        show_reasons=True,
    )
    steps.append(
        DemoStep(
            title="Recall promoted handoff memory",
            command=f"{command_prefix} recall {_quote(promoted_query)} --show-sources --show-reasons --strategy bm25",
            output=promoted_context,
        )
    )

    transcript_path = workspace / "transcript.md"
    transcript = render_demo_transcript(
        workspace=workspace,
        project_dir=project_dir,
        memory_home=memory_home,
        steps=tuple(steps),
    )
    transcript_path.write_text(transcript, encoding="utf-8")
    return DemoRunResult(
        workspace=workspace,
        project_dir=project_dir,
        memory_home=memory_home,
        transcript_path=transcript_path,
        transcript=transcript,
        steps=tuple(steps),
    )


def run_mcp_demo(
    *,
    workspace: Path,
    memagent_root: Path | None = None,
    reset: bool = False,
) -> McpDemoResult:
    root = (memagent_root or default_memagent_root()).expanduser().resolve()
    workspace = workspace.expanduser().resolve()
    if reset and workspace.exists():
        shutil.rmtree(workspace)

    project_dir = workspace / "project"
    memory_home = workspace / "memagent_home"
    project_dir.mkdir(parents=True, exist_ok=True)
    memory_home.mkdir(parents=True, exist_ok=True)
    _ensure_demo_project(project_dir)

    context = detect_context(project_dir)
    install_plan = build_agents_install_plan(
        context=context,
        target=project_dir / "AGENTS.md",
        memagent_root=root,
    )
    write_agents_install_plan(install_plan)

    server = McpServer.from_home_arg(str(memory_home), str(root))
    exchanges: list[McpDemoExchange] = []

    def send(title: str, request: dict[str, object]) -> dict[str, object] | None:
        response = server.handle(request)
        exchanges.append(McpDemoExchange(title=title, request=request, response=response))
        return response

    send(
        "Initialize MCP server",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "memagent-demo", "version": "0"},
            },
        },
    )
    send(
        "Initialized notification",
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        },
    )
    send("List tools", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    send(
        "Check AGENTS.md integration",
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "memagent_agents_doctor",
                "arguments": {"cwd": str(project_dir)},
            },
        },
    )
    send(
        "Remember workflow memory",
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "memagent_remember",
                "arguments": {
                    "text": DEMO_MEMORY,
                    "topic": "MCP demo validation accuracy entrypoint",
                    "domain": "coding",
                    "kind": "data_entrypoint",
                    "repo": "demo_service",
                    "module": "validation",
                    "triggers": ["validation", "accuracy", "audit_label"],
                    "exportable": True,
                    "cwd": str(project_dir),
                },
            },
        },
    )
    send(
        "Recall workflow memory",
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "memagent_recall",
                "arguments": {
                    "query": DEMO_QUERY,
                    "cwd": str(project_dir),
                    "strategy": "bm25",
                    "show_sources": True,
                    "show_reasons": True,
                    "format": "json",
                },
            },
        },
    )
    send(
        "Save handoff",
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "memagent_handoff_save",
                "arguments": {
                    "cwd": str(project_dir),
                    "topic": "MCP demo handoff",
                    "summary": DEMO_HANDOFF,
                    "done": ["Exercised MCP remember and recall tools."],
                    "next_steps": ["Review generated MCP transcript."],
                    "memory_candidates": ["MCP demos should show protocol requests and responses."],
                },
            },
        },
    )
    send(
        "Show handoff",
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "memagent_handoff_show",
                "arguments": {"cwd": str(project_dir), "max_lines": 30},
            },
        },
    )

    recall_context = detect_context(project_dir)
    matches = server.store.recall(DEMO_QUERY, context=recall_context, limit=5, strategy="bm25")
    payload = server.store.build_recall_payload(
        query=DEMO_QUERY,
        context=recall_context,
        matches=matches,
        max_lines=12,
        show_sources=True,
        show_reasons=True,
    )
    seeded_trace = server.store.save_recall_trace(payload, source="mcp-demo-seed")
    send(
        "List seeded recall traces",
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "memagent_trace_list",
                "arguments": {"limit": 5},
            },
        },
    )
    send(
        "Label recall trace",
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "memagent_trace_label",
                "arguments": {
                    "identifier": seeded_trace.identifier,
                    "rating": "useful",
                    "note": "MCP transcript recall found the intended memory.",
                },
            },
        },
    )
    send(
        "Report trace feedback",
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "memagent_trace_report",
                "arguments": {"limit": 10},
            },
        },
    )
    trace_eval_report_path = workspace / "trace_eval" / "report.md"
    trace_replay_report_path = workspace / "trace_replay" / "report.md"
    send(
        "Write trace feedback eval",
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "memagent_trace_eval",
                "arguments": {"workspace": str(trace_eval_report_path.parent), "limit": 10},
            },
        },
    )
    send(
        "Replay recall traces",
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "memagent_trace_replay",
                "arguments": {"workspace": str(trace_replay_report_path.parent), "limit": 10},
            },
        },
    )

    transcript = render_mcp_demo_transcript(
        workspace=workspace,
        project_dir=project_dir,
        memory_home=memory_home,
        exchanges=tuple(exchanges),
        seeded_trace_id=seeded_trace.identifier,
        trace_eval_report_path=trace_eval_report_path,
        trace_replay_report_path=trace_replay_report_path,
    )
    transcript_path = workspace / "mcp_transcript.md"
    transcript_path.write_text(transcript, encoding="utf-8")
    return McpDemoResult(
        workspace=workspace,
        project_dir=project_dir,
        memory_home=memory_home,
        transcript_path=transcript_path,
        transcript=transcript,
        exchanges=tuple(exchanges),
        seeded_trace_id=seeded_trace.identifier,
        trace_eval_report_path=trace_eval_report_path,
        trace_replay_report_path=trace_replay_report_path,
    )


def run_demo_bundle(
    *,
    workspace: Path,
    memagent_root: Path | None = None,
    reset: bool = False,
) -> DemoBundleResult:
    root = (memagent_root or default_memagent_root()).expanduser().resolve()
    workspace = workspace.expanduser().resolve()
    if reset and workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    demo = run_demo(
        workspace=workspace / "agents_flow",
        memagent_root=root,
        reset=True,
    )
    recall_eval = run_recall_eval(workspace=workspace / "recall_eval")
    mcp_demo = run_mcp_demo(
        workspace=workspace / "mcp_flow",
        memagent_root=root,
        reset=True,
    )
    tools = tool_definitions()
    report = render_demo_bundle_report(
        workspace=workspace,
        memagent_root=root,
        demo=demo,
        recall_eval=recall_eval,
        mcp_demo=mcp_demo,
        tools=tools,
    )
    report_path = workspace / "interview_demo.md"
    report_path.write_text(report, encoding="utf-8")
    return DemoBundleResult(
        workspace=workspace,
        report_path=report_path,
        report=report,
        demo=demo,
        recall_eval=recall_eval,
        mcp_demo=mcp_demo,
        mcp_tool_count=len(tools),
    )


def render_demo_transcript(
    *,
    workspace: Path,
    project_dir: Path,
    memory_home: Path,
    steps: tuple[DemoStep, ...],
) -> str:
    lines = [
        "# MemAgent Demo Transcript",
        "",
        "This transcript is generated from a local mock project. It is safe to share.",
        "",
        f"- Workspace: `{workspace}`",
        f"- Project: `{project_dir}`",
        f"- Memory home: `{memory_home}`",
        "",
    ]
    for index, step in enumerate(steps, start=1):
        lines.extend(
            [
                f"## {index}. {step.title}",
                "",
                "Command:",
                "",
                "```bash",
                step.command,
                "```",
                "",
                "Output:",
                "",
                "```text",
                step.output,
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_demo_bundle_report(
    *,
    workspace: Path,
    memagent_root: Path,
    demo: DemoRunResult,
    recall_eval: RecallEvalResult,
    mcp_demo: McpDemoResult,
    tools: list[dict[str, object]],
) -> str:
    trace_eval_report = demo.workspace / "trace_eval" / "report.md"
    trace_replay_report = demo.workspace / "trace_replay" / "report.md"
    ingest_report = demo.workspace / "ingest_codex" / "report.md"
    bm25 = _strategy_summary(recall_eval, "bm25")
    keyword = _strategy_summary(recall_eval, "keyword")
    regenerate_workspace = _display_path(workspace, root=memagent_root)
    lines = [
        "# MemAgent Interview Demo Bundle",
        "",
        "This bundle is generated from local mock data. It is safe to share.",
        "",
        "## Artifacts",
        "",
        "| Artifact | Path | What it proves |",
        "|---|---|---|",
        f"| AGENTS.md flow transcript | `{_display_path(demo.transcript_path, root=workspace)}` | Codex natural-language triggers, recall, handoff, prompt patch |",
        f"| Codex ingest candidates | `{_display_path(ingest_report, root=workspace)}` | Old Codex session logs can become review-only memory drafts |",
        f"| Trace feedback eval | `{_display_path(trace_eval_report, root=workspace)}` | Real-use recall feedback can be labeled and reported |",
        f"| Trace replay eval | `{_display_path(trace_replay_report, root=workspace)}` | Saved trace queries can be replayed against current retrievers |",
        f"| Recall benchmark | `{_display_path(recall_eval.report_path, root=workspace)}` | BM25 recall can be compared against a keyword baseline |",
        f"| MCP JSON-RPC transcript | `{_display_path(mcp_demo.transcript_path, root=workspace)}` | MCP initialize, tools/list, and tools/call are exercised end-to-end |",
        f"| Demo project AGENTS.md | `{_display_path(demo.project_dir / 'AGENTS.md', root=workspace)}` | The integration can be installed and checked in a project |",
        "",
        "## System Story",
        "",
        "```mermaid",
        "flowchart LR",
        '  A["Codex + AGENTS.md<br>Natural language trigger"] --> B["MemAgent CLI / MCP<br>tool surface"]',
        '  B --> C["Transcript Ingest<br>candidate drafts"]',
        '  C --> D["Memory Cards<br>workflow lessons"]',
        '  D --> E["RAG Recall<br>BM25 + explanations"]',
        '  E --> F["Context Pack<br>short Codex prompt patch"]',
        '  F --> G["Trace Feedback<br>useful / not_useful labels"]',
        '  G --> H["Eval Reports<br>mock + real-use evidence"]',
        "```",
        "",
        "## Capability Evidence",
        "",
        "| Capability | Evidence |",
        "|---|---|",
        f"| AGENTS.md integration | `demo-run` generated `{len(demo.steps)}` reproducible steps and a ready doctor check |",
        f"| RAG evaluation | `bm25` {bm25}; `keyword` {keyword} |",
        f"| MCP protocol surface | `{len(tools)}` tools exposed with annotations; `{len(mcp_demo.exchanges)}` JSON-RPC exchanges captured |",
        "| Agent memory lifecycle | ingest candidate -> remember -> recall -> handoff -> promote -> recall promoted memory |",
        "| Feedback loop | recall trace -> label useful -> report -> trace eval -> trace replay |",
        "",
        "## MCP Tool Surface",
        "",
        "| Tool | Read-only | Idempotent | Purpose |",
        "|---|---|---|---|",
    ]
    for tool in tools:
        annotations = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
        lines.append(
            "| "
            f"{tool.get('name')} | "
            f"{_yes_no(bool(annotations.get('readOnlyHint')))} | "
            f"{_yes_no(bool(annotations.get('idempotentHint')))} | "
            f"{_md_cell(str(tool.get('description') or ''))} |"
        )

    lines.extend(
        [
            "",
            "## Five-Minute Demo Script",
            "",
            "1. Open the AGENTS.md flow transcript and show the doctor output marked `Status: ready`.",
            "2. Show Codex transcript ingest to explain how old sessions become review-only memory candidates.",
            "3. Show the recall step with sources, matched terms, and BM25 strategy.",
            "4. Show the Codex dry-run prompt patch to prove MemAgent augments Codex instead of replacing it.",
            "5. Show the MCP JSON-RPC transcript to prove the protocol surface is executable.",
            "6. Show handoff and promotion to explain memory lifecycle beyond plain RAG.",
            "7. Show recall-eval, trace-eval, and trace-replay reports to explain offline, real-use, and regression evaluation.",
            "",
            "## Positioning",
            "",
            "MemAgent is not another general agent platform. It is a Codex-first workflow memory layer:",
            "",
            "- AGENTS.md teaches Codex when to call MemAgent.",
            "- Codex transcript ingest turns old sessions into review-only memory candidates.",
            "- Memory cards store reusable workflow lessons, not whole chat history.",
            "- Recall output is short, source-backed, explainable, and pack-budgeted.",
            "- MCP exposes the same capabilities to other coding-agent clients.",
            "- Evaluation combines controlled mock retrieval, real trace feedback, and trace replay.",
            "",
            "## Regenerate",
            "",
            "```bash",
            f"memagent demo-bundle --workspace {_quote(regenerate_workspace)} --reset",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def render_mcp_demo_transcript(
    *,
    workspace: Path,
    project_dir: Path,
    memory_home: Path,
    exchanges: tuple[McpDemoExchange, ...],
    seeded_trace_id: str,
    trace_eval_report_path: Path,
    trace_replay_report_path: Path,
) -> str:
    lines = [
        "# MemAgent MCP JSON-RPC Transcript",
        "",
        "This transcript is generated from a local mock project. It is safe to share.",
        "",
        f"- Workspace: `{workspace}`",
        f"- Project: `{project_dir}`",
        f"- Memory home: `{memory_home}`",
        f"- Protocol version: `{MCP_PROTOCOL_VERSION}`",
        f"- Exchanges: `{len(exchanges)}`",
        f"- Seeded trace: `{seeded_trace_id}`",
        f"- Trace eval report: `{trace_eval_report_path}`",
        f"- Trace replay report: `{trace_replay_report_path}`",
        "",
        "## Flow",
        "",
        "```mermaid",
        "sequenceDiagram",
        "  participant C as MCP Client",
        "  participant S as MemAgent MCP Server",
        "  C->>S: initialize",
        "  C->>S: tools/list",
        "  C->>S: tools/call remember",
        "  C->>S: tools/call recall",
        "  C->>S: tools/call handoff / trace",
        "  C->>S: tools/call trace replay",
        "  S-->>C: JSON-RPC results",
        "```",
        "",
    ]
    for index, exchange in enumerate(exchanges, start=1):
        lines.extend(
            [
                f"## {index}. {exchange.title}",
                "",
                "Request:",
                "",
                "```json",
                json.dumps(exchange.request, ensure_ascii=False, indent=2),
                "```",
                "",
                "Response:",
                "",
            ]
        )
        if exchange.response is None:
            lines.extend(["```text", "(notification; no response)", "```", ""])
        else:
            lines.extend(
                [
                    "```json",
                    json.dumps(exchange.response, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _ensure_demo_project(project_dir: Path) -> None:
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.exists():
        pyproject.write_text(
            "\n".join(
                [
                    "[project]",
                    'name = "demo-service"',
                    'version = "0.0.0"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
    if not (project_dir / ".git").exists():
        try:
            subprocess.run(
                ["git", "init", "-q"],
                cwd=project_dir,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def _write_demo_codex_session(*, codex_sessions_root: Path, project_dir: Path) -> Path:
    session_dir = codex_sessions_root / "2026" / "07" / "04"
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "rollout-demo-codex-ingest.jsonl"
    records = []
    for record in DEMO_CODEX_SESSION_RECORDS:
        encoded = json.dumps(record, ensure_ascii=False)
        encoded = encoded.replace("{project_dir}", str(project_dir))
        records.append(json.loads(encoded))
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")
    return path


def _command_prefix(*, root: Path, memory_home: Path) -> str:
    del root
    return f"MEMAGENT_HOME={_quote(memory_home)} memagent"


def _quote(value: str | Path) -> str:
    return shlex.quote(str(value))


def _strategy_summary(result: RecallEvalResult, strategy: str) -> str:
    for item in result.strategy_results:
        if item.strategy == strategy:
            return f"hit@1={item.hit_at_1:.2f}, mrr={item.mrr:.2f}"
    return "not run"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _display_path(path: Path, *, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
