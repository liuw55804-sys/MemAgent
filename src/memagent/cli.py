from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

from memagent.agents import (
    build_agents_doctor_report,
    build_agents_install_plan,
    build_agents_snippet,
    render_agents_install_report,
    write_agents_install_plan,
)
from memagent.activity import build_activity_report, render_activity_report
from memagent.codex_skill import (
    build_user_codex_skill_plan,
    render_user_codex_doctor,
    render_user_codex_skill_report,
    uninstall_user_codex_skill,
    write_user_codex_skill_plan,
    write_user_codex_skill_uninstall,
)
from memagent.context import detect_context
from memagent.demo import run_demo, run_demo_bundle, run_mcp_demo
from memagent.draft import draft_memory, render_memory_draft
from memagent.eval import run_recall_eval, run_trace_eval, run_trace_replay
from memagent.handoff import (
    HandoffStore,
    draft_handoff_from_text,
    render_handoff_draft,
    render_promotion_preview,
)
from memagent.ingest import (
    DEFAULT_CODEX_INGEST_WORKSPACE,
    DEFAULT_CODEX_SESSIONS_ROOT,
    run_codex_ingest,
)
from memagent.interaction import process_interaction, process_payload_json, render_process_result
from memagent.llm import activate_semantic_profile, check_llm_provider, configure_semantic_mode, render_llm_doctor
from memagent.memory import DEFAULT_RECALL_STRATEGY, MemoryStore
from memagent.mcp import McpServer, run_stdio_server
from memagent.router import render_route_decision, route_interaction
from memagent.wrapper import build_augmented_prompt, process_result_context_for_prompt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memagent",
        description="Local workflow memory for Codex and other coding agents.",
    )
    parser.add_argument(
        "--home",
        help="Override memory home directory. Defaults to MEMAGENT_HOME or ~/.memagent.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    remember = subparsers.add_parser("remember", help="Write a memory card from text.")
    remember.add_argument("text", help="Lesson, workflow note, or pitfall to remember.")
    remember.add_argument("--topic", help="Short memory topic.")
    remember.add_argument(
        "--domain",
        help="Memory domain. Defaults to coding. Examples: coding, learning, life.",
    )
    remember.add_argument(
        "--kind",
        help="Memory kind. Defaults to note. Examples: tool_recipe, skill_route, pitfall.",
    )
    remember.add_argument("--repo", help="Repository scope.")
    remember.add_argument("--module", help="Module or subsystem scope.")
    remember.add_argument(
        "--trigger",
        action="append",
        default=[],
        help="Keyword that should recall this memory. Can be repeated.",
    )
    remember.add_argument(
        "--exportable",
        action="store_true",
        help="Mark this memory as exportable. Default is local/internal only.",
    )

    recall = subparsers.add_parser("recall", help="Recall relevant memory cards.")
    recall.add_argument("query", help="Natural-language task or question.")
    recall.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of memory cards to inspect. Default: 5.",
    )
    recall.add_argument(
        "--max-lines",
        type=int,
        default=12,
        help="Maximum lines in the composed recall context. Default: 12.",
    )
    recall.add_argument(
        "--show-sources",
        action="store_true",
        help="Include matching memory card file names.",
    )
    recall.add_argument(
        "--show-reasons",
        action="store_true",
        help="Include simple recall score and matched query terms.",
    )
    recall.add_argument(
        "--strategy",
        default=DEFAULT_RECALL_STRATEGY,
        choices=["bm25", "keyword"],
        help="Recall scoring strategy. Default: bm25.",
    )
    recall.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON recall payload instead of text.",
    )
    recall.add_argument(
        "--trace",
        action="store_true",
        help="Save this recall payload under the local recall_traces directory.",
    )

    route = subparsers.add_parser(
        "route",
        help="Classify a natural Codex interaction into a MemAgent action.",
    )
    route.add_argument("message", help="Latest user message or task.")
    route.add_argument(
        "--cwd",
        help="Project directory for routing context. Defaults to the current working directory.",
    )
    route.add_argument(
        "--semantic-mode",
        choices=["heuristic", "llm", "hybrid"],
        help="Semantic mode. Defaults to local config or heuristic.",
    )
    route.add_argument(
        "--recent-text",
        default="",
        help="Optional recent conversation excerpt for memory drafting decisions.",
    )
    route.add_argument(
        "--from-file",
        help='Read recent conversation text from a file, or "-" for stdin.',
    )
    route.add_argument(
        "--provider",
        default="heuristic",
        choices=["heuristic", "openai-compatible"],
        help="Routing provider. Default: heuristic.",
    )
    route.add_argument("--llm-profile", help="Named LLM provider profile for openai-compatible routing.")
    route.add_argument("--llm-config", help="Optional LLM provider profile config path.")
    route.add_argument(
        "--recent-trace",
        action="store_true",
        help="Tell the router a recent recall trace exists for feedback labeling.",
    )
    route.add_argument(
        "--pending-draft",
        action="store_true",
        help="Tell the router a pending memory preview exists for confirmation saving.",
    )
    route.add_argument(
        "--json",
        action="store_true",
        help="Print structured route payload instead of text.",
    )

    process = subparsers.add_parser(
        "process",
        help="Route and handle a natural Codex interaction with MemAgent.",
    )
    process.add_argument("message", help="Latest user message or task.")
    process.add_argument(
        "--cwd",
        help="Project directory for interaction context. Defaults to the current working directory.",
    )
    process.add_argument(
        "--semantic-mode",
        choices=["heuristic", "llm", "hybrid"],
        help="Semantic mode. Defaults to local config or heuristic.",
    )
    process.add_argument(
        "--recent-text",
        default="",
        help="Optional recent conversation excerpt for drafting or handoff.",
    )
    process.add_argument(
        "--from-file",
        help='Read recent conversation text from a file, or "-" for stdin.',
    )
    process.add_argument(
        "--provider",
        default="heuristic",
        choices=["heuristic", "openai-compatible"],
        help="Routing/drafting provider. Default: heuristic.",
    )
    process.add_argument("--llm-profile", help="Named LLM provider profile for openai-compatible processing.")
    process.add_argument("--llm-config", help="Optional LLM provider profile config path.")
    process.add_argument(
        "--draft-provider",
        choices=["heuristic", "openai-compatible"],
        help="Optional provider for memory-draft quality only. Router provider remains unchanged.",
    )
    process.add_argument("--draft-llm-profile", help="Named profile for memory-draft quality only.")
    process.add_argument("--draft-llm-config", help="Optional profile config path for memory-draft quality only.")
    process.add_argument(
        "--no-write",
        action="store_true",
        help="Do not write trace feedback, handoff, trace, or evaluation artifacts.",
    )
    process.add_argument(
        "--no-trace",
        action="store_true",
        help="Do not save recall traces when processing recall actions.",
    )
    process.add_argument(
        "--trace-none",
        action="store_true",
        help="Also save process traces for no-op actions. Useful for self-tests or debug sessions.",
    )
    process.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum memory cards to inspect for recall actions. Default: 5.",
    )
    process.add_argument(
        "--max-lines",
        type=int,
        default=12,
        help="Maximum lines in recalled context. Default: 12.",
    )
    process.add_argument(
        "--strategy",
        default=DEFAULT_RECALL_STRATEGY,
        choices=["bm25", "keyword"],
        help="Recall scoring strategy for recall actions. Default: bm25.",
    )
    process.add_argument("--eval-workspace", help="Explicit workspace for trace eval reports.")
    process.add_argument("--replay-workspace", help="Explicit workspace for trace replay reports.")
    process.add_argument(
        "--json",
        action="store_true",
        help="Print structured process payload instead of text.",
    )

    llm = subparsers.add_parser(
        "llm",
        help="Inspect optional LLM provider configuration.",
    )
    llm_subparsers = llm.add_subparsers(dest="llm_command", required=True)
    llm_doctor = llm_subparsers.add_parser(
        "doctor",
        help="Check OpenAI-compatible provider readiness.",
    )
    llm_doctor.add_argument(
        "--provider",
        default="openai-compatible",
        choices=["openai-compatible"],
        help="LLM provider to check. Default: openai-compatible.",
    )
    llm_doctor.add_argument(
        "--mode",
        choices=["heuristic", "llm", "hybrid"],
        help="Override the configured semantic mode for this report.",
    )
    llm_doctor.add_argument(
        "--profile",
        help="Named provider profile from ~/.memagent/config.json (legacy local profiles remain readable).",
    )

    configure = subparsers.add_parser(
        "configure",
        help="Configure local-only, optional LLM, or hybrid semantic routing without storing an API key.",
    )
    configure.add_argument("--mode", choices=["heuristic", "llm", "hybrid"], help="Semantic mode to save.")
    configure.add_argument("--profile", default="default", help="Profile name for an OpenAI-compatible service.")
    configure.add_argument(
        "--use-profile",
        action="store_true",
        help="Activate an existing profile without asking for base URL, model, or API key.",
    )
    configure.add_argument("--base-url", help="OpenAI-compatible base URL.")
    configure.add_argument("--model", help="Model name.")
    configure.add_argument("--api-key-env", default="MEMAGENT_LLM_API_KEY", help="Environment variable that holds the API key.")
    configure.add_argument("--no-api-key", action="store_true", help="Allow a local compatible service without an API key.")
    configure.add_argument("--config", help="Config path. Defaults to ~/.memagent/config.json.")
    llm_doctor.add_argument(
        "--config",
        help="Optional MemAgent config path. Defaults to ~/.memagent/config.json.",
    )
    llm_doctor.add_argument(
        "--check-live",
        action="store_true",
        help="Send a small chat completion request to verify the API. Default only checks env vars.",
    )
    llm_doctor.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Live check timeout in seconds. Default: 30.",
    )
    llm_doctor.add_argument(
        "--json",
        action="store_true",
        help="Print structured LLM doctor payload instead of text.",
    )

    draft = subparsers.add_parser(
        "draft",
        help="Draft reviewable MemAgent artifacts without writing durable memory.",
    )
    draft_subparsers = draft.add_subparsers(dest="draft_command", required=True)
    draft_memory_parser = draft_subparsers.add_parser(
        "memory",
        help="Draft a reviewable memory card preview from text.",
    )
    draft_memory_parser.add_argument(
        "text",
        nargs="?",
        help="Source text to rewrite into a memory draft.",
    )
    draft_memory_parser.add_argument(
        "--from-file",
        help='Read source text from a file, or "-" for stdin.',
    )
    draft_memory_parser.add_argument(
        "--cwd",
        help="Project directory for draft context. Defaults to the current working directory.",
    )
    draft_memory_parser.add_argument(
        "--provider",
        default="heuristic",
        choices=["heuristic", "openai-compatible"],
        help="Drafting provider. Default: heuristic.",
    )
    draft_memory_parser.add_argument("--llm-profile", help="Named LLM provider profile for openai-compatible drafting.")
    draft_memory_parser.add_argument("--llm-config", help="Optional LLM provider profile config path.")
    draft_memory_parser.add_argument("--topic", help="Optional topic override.")
    draft_memory_parser.add_argument("--kind", help="Optional memory kind override.")
    draft_memory_parser.add_argument(
        "--max-chars",
        type=int,
        default=420,
        help="Maximum characters in drafted memory text. Default: 420.",
    )
    draft_memory_parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured memory draft payload instead of text.",
    )

    codex = subparsers.add_parser(
        "codex",
        help="Start Codex with recalled MemAgent context prepended to the prompt.",
    )
    codex.add_argument("prompt", help="Prompt to pass to Codex.")
    codex.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of memory cards to inspect. Default: 5.",
    )
    codex.add_argument(
        "--max-lines",
        type=int,
        default=12,
        help="Maximum lines in the composed recall context. Default: 12.",
    )
    codex.add_argument(
        "--show-sources",
        action="store_true",
        help="Include matching memory card file names in the Codex prompt.",
    )
    codex.add_argument(
        "--show-reasons",
        action="store_true",
        help="Include simple recall score and matched query terms in the Codex prompt.",
    )
    codex.add_argument(
        "--strategy",
        default=DEFAULT_RECALL_STRATEGY,
        choices=["bm25", "keyword"],
        help="Recall scoring strategy. Default: bm25.",
    )
    codex.add_argument(
        "--provider",
        default="heuristic",
        choices=["heuristic", "openai-compatible"],
        help="MemAgent preflight provider. Default: heuristic.",
    )
    codex.add_argument("--llm-profile", help="Named LLM provider profile for openai-compatible preflight.")
    codex.add_argument("--llm-config", help="Optional LLM provider profile config path.")
    codex.add_argument(
        "--no-write",
        action="store_true",
        help="Do not let preflight write trace feedback, handoff, trace, or evaluation artifacts.",
    )
    codex.add_argument(
        "--no-trace",
        action="store_true",
        help="Do not save recall traces during preflight recall actions.",
    )
    codex.add_argument(
        "--trace-none",
        action="store_true",
        help="Also save process traces for no-op preflight actions. Useful for self-tests or debug sessions.",
    )
    codex.add_argument(
        "--no-memory",
        action="store_true",
        help="Pass the prompt to Codex without MemAgent preflight.",
    )
    codex.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the final prompt instead of starting Codex.",
    )
    codex.add_argument(
        "--codex-bin",
        default="codex",
        help="Codex executable to run. Default: codex.",
    )
    codex.add_argument(
        "codex_args",
        nargs=argparse.REMAINDER,
        help="Extra Codex CLI arguments after --, for example: -- --model gpt-5.4",
    )

    snippet = subparsers.add_parser(
        "agents-snippet",
        help="Print AGENTS.md instructions for natural-language MemAgent signals.",
    )
    snippet.add_argument(
        "--memagent-root",
        help="MemAgent project root. Defaults to the installed package root.",
    )

    doctor = subparsers.add_parser(
        "agents-doctor",
        help="Check whether the current project AGENTS.md is wired to MemAgent.",
    )
    doctor.add_argument(
        "--cwd",
        help="Project directory to inspect. Defaults to the current working directory.",
    )
    doctor.add_argument(
        "--memagent-root",
        help="MemAgent project root. Defaults to the installed package root.",
    )

    install = subparsers.add_parser(
        "agents-install",
        help="Preview or write MemAgent instructions into an AGENTS.md file.",
    )
    install.add_argument(
        "--cwd",
        help="Project directory to inspect. Defaults to the current working directory.",
    )
    install.add_argument(
        "--target",
        help="AGENTS.md path to update. Defaults to <cwd>/AGENTS.md.",
    )
    install.add_argument(
        "--memagent-root",
        help="MemAgent project root. Defaults to the installed package root.",
    )
    install.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace an existing unmarked MemAgent section.",
    )
    install.add_argument(
        "--write",
        action="store_true",
        help="Write the planned AGENTS.md change. Default is dry-run preview.",
    )

    user_codex_install = subparsers.add_parser(
        "install-user-codex",
        help="Install the MemAgent skill under the user's Codex skills directory, never in a project repo.",
    )
    user_codex_install.add_argument(
        "--target",
        help="Target SKILL.md path. Defaults to $CODEX_HOME/skills/memagent/SKILL.md.",
    )
    user_codex_install.add_argument(
        "--memagent-root",
        help="MemAgent project root used by the generated command. Defaults to the installed package root.",
    )
    user_codex_install.add_argument(
        "--command-prefix",
        help="Override the command embedded in the user-level skill.",
    )
    user_codex_install.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing non-managed skill only after reviewing it.",
    )
    user_codex_install.add_argument(
        "--write",
        action="store_true",
        help="Write the user-level skill. Default is dry-run preview.",
    )

    user_codex_doctor = subparsers.add_parser(
        "user-codex-doctor",
        help="Check the user-level MemAgent Codex skill without inspecting or changing a project repo.",
    )
    user_codex_doctor.add_argument(
        "--target",
        help="Target SKILL.md path. Defaults to $CODEX_HOME/skills/memagent/SKILL.md.",
    )
    user_codex_doctor.add_argument(
        "--memagent-root",
        help="MemAgent project root used by the generated command. Defaults to the installed package root.",
    )

    user_codex_uninstall = subparsers.add_parser(
        "uninstall-user-codex",
        help="Remove only the managed user-level MemAgent Codex skill.",
    )
    user_codex_uninstall.add_argument(
        "--target",
        help="Target SKILL.md path. Defaults to $CODEX_HOME/skills/memagent/SKILL.md.",
    )
    user_codex_uninstall.add_argument(
        "--force",
        action="store_true",
        help="Remove a non-managed skill only after reviewing it.",
    )
    user_codex_uninstall.add_argument(
        "--write",
        action="store_true",
        help="Remove the user-level skill. Default is dry-run preview.",
    )

    activity = subparsers.add_parser(
        "activity",
        help="Summarize local MemAgent actions for one project without changing the project repo.",
    )
    activity.add_argument(
        "--cwd",
        help="Project directory to summarize. Defaults to the current working directory.",
    )
    activity_window = activity.add_mutually_exclusive_group()
    activity_window.add_argument(
        "--today",
        action="store_true",
        help="Only include activity from the current local calendar day.",
    )
    activity_window.add_argument(
        "--since",
        help="Only include activity on or after this local date (YYYY-MM-DD).",
    )
    activity.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum recent events to print. Default: 20.",
    )
    activity.add_argument(
        "--json",
        action="store_true",
        help="Print structured activity data instead of text.",
    )

    demo = subparsers.add_parser(
        "demo-run",
        help="Run an isolated AGENTS.md integration demo and write a Markdown transcript.",
    )
    demo.add_argument(
        "--workspace",
        default="~/.memagent/demos/demo_run",
        help="Demo workspace directory. Default: ~/.memagent/demos/demo_run.",
    )
    demo.add_argument(
        "--memagent-root",
        help="MemAgent project root. Defaults to the installed package root.",
    )
    demo.add_argument(
        "--reset",
        action="store_true",
        help="Delete the demo workspace before running.",
    )

    demo_bundle = subparsers.add_parser(
        "demo-bundle",
        help="Generate a shareable interview demo bundle from mock data.",
    )
    demo_bundle.add_argument(
        "--workspace",
        default="~/.memagent/demos/demo_bundle",
        help="Demo bundle workspace directory. Default: ~/.memagent/demos/demo_bundle.",
    )
    demo_bundle.add_argument(
        "--memagent-root",
        help="MemAgent project root. Defaults to the installed package root.",
    )
    demo_bundle.add_argument(
        "--reset",
        action="store_true",
        help="Delete the bundle workspace before running.",
    )

    mcp_demo = subparsers.add_parser(
        "mcp-demo",
        help="Generate a local MCP JSON-RPC transcript from mock data.",
    )
    mcp_demo.add_argument(
        "--workspace",
        default="~/.memagent/demos/mcp_demo",
        help="MCP demo workspace directory. Default: ~/.memagent/demos/mcp_demo.",
    )
    mcp_demo.add_argument(
        "--memagent-root",
        help="MemAgent project root. Defaults to the installed package root.",
    )
    mcp_demo.add_argument(
        "--reset",
        action="store_true",
        help="Delete the MCP demo workspace before running.",
    )

    mcp = subparsers.add_parser(
        "mcp-stdio",
        help="Run a minimal MCP stdio server exposing MemAgent recall/remember tools.",
    )
    mcp.add_argument(
        "--memagent-root",
        help="MemAgent project root. Defaults to the installed package root.",
    )

    eval_parser = subparsers.add_parser(
        "recall-eval",
        help="Run a mock recall benchmark and write a Markdown evaluation report.",
    )
    eval_parser.add_argument(
        "--workspace",
        default="~/.memagent/reports/recall_eval",
        help="Evaluation workspace directory. Default: ~/.memagent/reports/recall_eval.",
    )

    ingest = subparsers.add_parser(
        "ingest",
        help="Draft memory candidates from external coding-agent transcripts.",
    )
    ingest_subparsers = ingest.add_subparsers(dest="ingest_command", required=True)
    ingest_codex = ingest_subparsers.add_parser(
        "codex",
        help="Draft memory candidates from local Codex session JSONL files.",
    )
    ingest_codex.add_argument(
        "--sessions-root",
        default=DEFAULT_CODEX_SESSIONS_ROOT,
        help=f"Codex sessions root. Default: {DEFAULT_CODEX_SESSIONS_ROOT}.",
    )
    ingest_codex.add_argument(
        "--workspace",
        default=DEFAULT_CODEX_INGEST_WORKSPACE,
        help=f"Output workspace. Default: {DEFAULT_CODEX_INGEST_WORKSPACE}.",
    )
    ingest_codex.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum recent session files to inspect. Default: 5.",
    )
    ingest_codex.add_argument(
        "--max-candidates",
        type=int,
        default=12,
        help="Maximum candidate drafts to write. Default: 12.",
    )
    ingest_codex.add_argument(
        "--cwd",
        help="Project cwd used for --project-only filtering. Defaults to current directory.",
    )
    ingest_codex.add_argument(
        "--project-only",
        action="store_true",
        help="Only inspect records whose cwd is under the detected current project.",
    )

    trace = subparsers.add_parser(
        "trace",
        help="Inspect saved recall traces.",
    )
    trace_subparsers = trace.add_subparsers(dest="trace_command", required=True)
    trace_list = trace_subparsers.add_parser(
        "list",
        help="List recent recall traces.",
    )
    trace_list.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum traces to list. Default: 5.",
    )
    trace_show = trace_subparsers.add_parser(
        "show",
        help="Show one recall trace. Defaults to the latest trace.",
    )
    trace_show.add_argument(
        "identifier",
        nargs="?",
        help="Trace id, trace JSON path, or omitted for the latest trace.",
    )
    trace_show.add_argument(
        "--json",
        action="store_true",
        help="Print the full saved trace JSON.",
    )
    trace_label = trace_subparsers.add_parser(
        "label",
        help="Label one recall trace as useful, not-useful, or neutral.",
    )
    trace_label.add_argument(
        "identifier",
        nargs="?",
        help="Trace id, trace JSON path, or omitted for the latest trace.",
    )
    trace_label.add_argument(
        "--rating",
        required=True,
        choices=["useful", "not-useful", "not_useful", "neutral"],
        help="Feedback rating for this trace.",
    )
    trace_label.add_argument(
        "--note",
        help="Optional short feedback note.",
    )
    trace_report = trace_subparsers.add_parser(
        "report",
        help="Summarize labeled recall traces.",
    )
    trace_report.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum traces to inspect. Default: 50.",
    )
    trace_eval = trace_subparsers.add_parser(
        "eval",
        help="Write a Markdown evaluation report from saved recall trace feedback.",
    )
    trace_eval.add_argument(
        "--workspace",
        default="~/.memagent/reports/trace_eval",
        help="Trace evaluation workspace directory. Default: ~/.memagent/reports/trace_eval.",
    )
    trace_eval.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum traces to inspect. Default: 50.",
    )
    trace_replay = trace_subparsers.add_parser(
        "replay",
        help="Replay saved recall trace queries against current retrievers.",
    )
    trace_replay.add_argument(
        "--workspace",
        default="~/.memagent/reports/trace_replay",
        help="Trace replay workspace directory. Default: ~/.memagent/reports/trace_replay.",
    )
    trace_replay.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum traces to inspect. Default: 50.",
    )

    handoff = subparsers.add_parser(
        "handoff",
        help="Save or show a project handoff for cross-session catch-up.",
    )
    handoff_subparsers = handoff.add_subparsers(dest="handoff_command", required=True)

    handoff_save = handoff_subparsers.add_parser(
        "save",
        help="Save the latest project handoff.",
    )
    handoff_save.add_argument("summary", help="Short session handoff summary.")
    handoff_save.add_argument("--topic", help="Short handoff topic.")
    handoff_save.add_argument(
        "--cwd",
        help="Project directory. Defaults to the current working directory.",
    )
    handoff_save.add_argument(
        "--done",
        action="append",
        default=[],
        help="Completed item. Can be repeated.",
    )
    handoff_save.add_argument(
        "--next-step",
        action="append",
        default=[],
        help="Recommended next step. Can be repeated.",
    )
    handoff_save.add_argument(
        "--open-question",
        action="append",
        default=[],
        help="Open question to carry into the next session. Can be repeated.",
    )
    handoff_save.add_argument(
        "--memory-candidate",
        action="append",
        default=[],
        help="Candidate lesson that may later be promoted to long-term memory. Can be repeated.",
    )

    handoff_show = handoff_subparsers.add_parser(
        "show",
        help="Show the latest project handoff.",
    )
    handoff_show.add_argument(
        "--cwd",
        help="Project directory. Defaults to the current working directory.",
    )
    handoff_show.add_argument(
        "--max-lines",
        type=int,
        default=40,
        help="Maximum lines to print. Default: 40.",
    )
    handoff_show.add_argument(
        "--no-source",
        action="store_true",
        help="Do not print the handoff file path.",
    )

    handoff_draft = handoff_subparsers.add_parser(
        "draft",
        help="Draft a handoff from a Markdown/session note file.",
    )
    handoff_draft.add_argument(
        "--from-file",
        required=True,
        help='Source Markdown/session note file. Use "-" to read stdin.',
    )
    handoff_draft.add_argument("--topic", help="Override the draft topic.")
    handoff_draft.add_argument(
        "--cwd",
        help="Project directory. Defaults to the current working directory.",
    )
    handoff_draft.add_argument(
        "--max-items",
        type=int,
        default=5,
        help="Maximum items per draft section. Default: 5.",
    )
    handoff_draft.add_argument(
        "--save",
        action="store_true",
        help="Save the draft as the latest handoff after printing it.",
    )

    handoff_promote = handoff_subparsers.add_parser(
        "promote",
        help="Promote memory candidates from the latest handoff into durable memory cards.",
    )
    handoff_promote.add_argument(
        "--cwd",
        help="Project directory. Defaults to the current working directory.",
    )
    handoff_promote.add_argument(
        "--index",
        action="append",
        type=int,
        default=[],
        help="1-based memory candidate index to promote. Can be repeated. Default: 1.",
    )
    handoff_promote.add_argument(
        "--all",
        action="store_true",
        help="Promote all memory candidates from the latest handoff.",
    )
    handoff_promote.add_argument(
        "--kind",
        default="workflow",
        help="Memory kind for promoted cards. Default: workflow.",
    )
    handoff_promote.add_argument("--module", help="Module or subsystem scope for promoted cards.")
    handoff_promote.add_argument(
        "--trigger",
        action="append",
        default=[],
        help="Extra recall trigger keyword for promoted cards. Can be repeated.",
    )
    handoff_promote.add_argument(
        "--exportable",
        action="store_true",
        help="Mark promoted memory cards as exportable.",
    )
    handoff_promote.add_argument(
        "--write",
        action="store_true",
        help="Write selected candidates as memory cards. Default is dry-run preview.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "agents-snippet":
        print(build_agents_snippet(Path(args.memagent_root) if args.memagent_root else None))
        return 0

    if args.command == "demo-run":
        result = run_demo(
            workspace=Path(args.workspace).expanduser(),
            memagent_root=Path(args.memagent_root).expanduser() if args.memagent_root else None,
            reset=args.reset,
        )
        print("[MemAgent demo-run]")
        print(f"- workspace: {result.workspace}")
        print(f"- project: {result.project_dir}")
        print(f"- memory home: {result.memory_home}")
        print(f"- transcript: {result.transcript_path}")
        print(f"- steps: {len(result.steps)}")
        return 0

    if args.command == "demo-bundle":
        result = run_demo_bundle(
            workspace=Path(args.workspace).expanduser(),
            memagent_root=Path(args.memagent_root).expanduser() if args.memagent_root else None,
            reset=args.reset,
        )
        print("[MemAgent demo-bundle]")
        print(f"- workspace: {result.workspace}")
        print(f"- report: {result.report_path}")
        print(f"- transcript: {result.demo.transcript_path}")
        print(f"- ingest candidates: {result.demo.workspace / 'ingest_codex' / 'report.md'}")
        print(f"- recall eval: {result.recall_eval.report_path}")
        print(f"- trace eval: {result.demo.workspace / 'trace_eval' / 'report.md'}")
        print(f"- trace replay: {result.demo.workspace / 'trace_replay' / 'report.md'}")
        print(f"- mcp transcript: {result.mcp_demo.transcript_path}")
        print(f"- mcp tools: {result.mcp_tool_count}")
        return 0

    if args.command == "mcp-demo":
        result = run_mcp_demo(
            workspace=Path(args.workspace).expanduser(),
            memagent_root=Path(args.memagent_root).expanduser() if args.memagent_root else None,
            reset=args.reset,
        )
        print("[MemAgent mcp-demo]")
        print(f"- workspace: {result.workspace}")
        print(f"- project: {result.project_dir}")
        print(f"- memory home: {result.memory_home}")
        print(f"- transcript: {result.transcript_path}")
        print(f"- exchanges: {len(result.exchanges)}")
        print(f"- trace eval: {result.trace_eval_report_path}")
        print(f"- trace replay: {result.trace_replay_report_path}")
        return 0

    if args.command == "mcp-stdio":
        return run_stdio_server(McpServer.from_home_arg(args.home, args.memagent_root))

    if args.command == "recall-eval":
        result = run_recall_eval(workspace=Path(args.workspace).expanduser())
        print("[MemAgent recall-eval]")
        print(f"- workspace: {result.workspace}")
        print(f"- project: {result.project_dir}")
        print(f"- memory home: {result.memory_home}")
        print(f"- report: {result.report_path}")
        for strategy_result in result.strategy_results:
            print(
                f"- {strategy_result.strategy}: "
                f"hit@1={strategy_result.hit_at_1:.2f}; mrr={strategy_result.mrr:.2f}"
            )
        return 0

    if args.command == "ingest":
        if args.ingest_command == "codex":
            context = detect_context(Path(args.cwd) if args.cwd else None)
            result = run_codex_ingest(
                sessions_root=Path(args.sessions_root).expanduser(),
                workspace=Path(args.workspace).expanduser(),
                context=context,
                limit=args.limit,
                max_candidates=args.max_candidates,
                project_only=args.project_only,
            )
            print("[MemAgent codex ingest]")
            print(f"- workspace: {result.workspace}")
            print(f"- sessions root: {result.sessions_root}")
            print(f"- sessions scanned: {result.sessions_scanned}")
            print(f"- records scanned: {result.records_scanned}")
            print(f"- candidates: {len(result.candidates)}")
            print(f"- report: {result.report_path}")
            print(f"- candidates dir: {result.candidates_dir}")
            print("- mode: review-only; no memory cards were written")
            return 0

    if args.command == "llm":
        if args.llm_command == "doctor":
            result = check_llm_provider(
                provider=args.provider,
                profile=args.profile,
                config_path=Path(args.config) if args.config else None,
                check_live=args.check_live,
                timeout_seconds=args.timeout,
                mode=args.mode,
            )
            if args.json:
                print(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
            else:
                print(render_llm_doctor(result))
            return 0

    if args.command == "configure":
        mode = args.mode or input("Semantic mode [heuristic/llm/hybrid] (default heuristic): ").strip() or "heuristic"
        if args.use_profile:
            try:
                config_path = activate_semantic_profile(
                    mode=mode,
                    profile=args.profile,
                    config_path=Path(args.config) if args.config else None,
                )
            except ValueError as exc:
                parser.error(str(exc))
            print("[MemAgent configure]\n- semantic mode: " + mode + "\n- active profile: " + args.profile + "\n- API key: read from the configured environment variable\n- config: " + str(config_path))
            return 0
        if mode == "heuristic":
            config_path = configure_semantic_mode(mode=mode, config_path=Path(args.config) if args.config else None)
            print("[MemAgent configure]\n- semantic mode: heuristic\n- LLM: disabled\n- API key: not stored\n- config: " + str(config_path))
            return 0
        base_url = args.base_url or input("OpenAI-compatible base URL: ").strip()
        model = args.model or input("Model name: ").strip()
        api_key_env = args.api_key_env or "MEMAGENT_LLM_API_KEY"
        config_path = configure_semantic_mode(
            mode=mode,
            profile=args.profile,
            base_url=base_url,
            model=model,
            api_key_env=api_key_env,
            allow_no_key=args.no_api_key,
            config_path=Path(args.config) if args.config else None,
        )
        key_note = "no key required for this local service" if args.no_api_key else f"set {api_key_env} in your shell before use"
        print("[MemAgent configure]\n- semantic mode: " + mode + "\n- provider: openai-compatible\n- profile: " + args.profile + "\n- API key: " + key_note + "\n- config: " + str(config_path))
        return 0

    store = MemoryStore.from_home_arg(args.home)
    if args.command == "install-user-codex":
        plan = build_user_codex_skill_plan(
            target=Path(args.target) if args.target else None,
            memagent_root=Path(args.memagent_root) if args.memagent_root else None,
            command_prefix=args.command_prefix,
            force=args.force,
        )
        if args.write:
            write_user_codex_skill_plan(plan)
        print(render_user_codex_skill_report(plan, write=args.write))
        return 1 if plan.blocked and args.write else 0

    if args.command == "user-codex-doctor":
        print(render_user_codex_doctor(target=Path(args.target) if args.target else None))
        return 0

    if args.command == "uninstall-user-codex":
        plan = uninstall_user_codex_skill(
            target=Path(args.target) if args.target else None,
            force=args.force,
        )
        if args.write:
            write_user_codex_skill_uninstall(plan)
        print(render_user_codex_skill_report(plan, write=args.write))
        return 1 if plan.blocked and args.write else 0

    if args.command == "activity":
        context = detect_context(Path(args.cwd) if args.cwd else None)
        since = None
        if args.today:
            since = datetime.now().astimezone().date()
        elif args.since:
            try:
                since = datetime.strptime(args.since, "%Y-%m-%d").date()
            except ValueError:
                parser.error("--since must use YYYY-MM-DD")
        report = build_activity_report(
            store=store,
            handoff_store=HandoffStore(store.home),
            context=context,
            since=since,
            limit=args.limit,
        )
        if args.json:
            print(json.dumps(report.to_payload(), ensure_ascii=False, indent=2))
        else:
            print(render_activity_report(report))
        return 0

    if args.command == "agents-doctor":
        context = detect_context(Path(args.cwd) if args.cwd else None)
        print(
            build_agents_doctor_report(
                context=context,
                memory_home=store.home,
                memory_count=store.count_memory_cards(),
                memagent_root=Path(args.memagent_root) if args.memagent_root else None,
            )
        )
        return 0

    if args.command == "agents-install":
        context = detect_context(Path(args.cwd) if args.cwd else None)
        plan = build_agents_install_plan(
            context=context,
            target=Path(args.target) if args.target else None,
            memagent_root=Path(args.memagent_root) if args.memagent_root else None,
            replace_existing=args.replace_existing,
        )
        if args.write:
            write_agents_install_plan(plan)
        print(render_agents_install_report(plan, write=args.write))
        return 1 if plan.blocked and args.write else 0

    if args.command == "route":
        context = detect_context(Path(args.cwd) if args.cwd else None)
        if args.from_file:
            source_text = sys.stdin.read() if args.from_file == "-" else Path(args.from_file).expanduser().read_text(encoding="utf-8")
            recent_text = "\n".join(part for part in (args.recent_text, source_text) if part)
        else:
            recent_text = args.recent_text
        try:
            decision = route_interaction(
                args.message,
                recent_text=recent_text,
                context=context,
                provider=args.provider,
                semantic_mode=args.semantic_mode,
                llm_profile=args.llm_profile,
                llm_config_path=Path(args.llm_config) if args.llm_config else None,
                has_recent_trace=True if args.recent_trace else None,
                has_pending_draft=True if args.pending_draft else None,
            )
        except ValueError as exc:
            parser.error(str(exc))
        if args.json:
            print(json.dumps(decision.to_payload(context=context), ensure_ascii=False, indent=2))
        else:
            print(render_route_decision(decision, context=context))
        return 0

    if args.command == "process":
        context = detect_context(Path(args.cwd) if args.cwd else None)
        if args.from_file:
            source_text = sys.stdin.read() if args.from_file == "-" else Path(args.from_file).expanduser().read_text(encoding="utf-8")
            recent_text = "\n".join(part for part in (args.recent_text, source_text) if part)
        else:
            recent_text = args.recent_text
        handoff_store = HandoffStore(store.home)
        try:
            result = process_interaction(
                message=args.message,
                recent_text=recent_text,
                context=context,
                store=store,
                handoff_store=handoff_store,
                provider=args.provider,
                semantic_mode=args.semantic_mode,
                llm_profile=args.llm_profile,
                llm_config_path=Path(args.llm_config) if args.llm_config else None,
                draft_provider=args.draft_provider,
                draft_llm_profile=args.draft_llm_profile,
                draft_llm_config_path=Path(args.draft_llm_config) if args.draft_llm_config else None,
                allow_writes=not args.no_write,
                trace_recall=not args.no_trace,
                trace_none=args.trace_none,
                limit=args.limit,
                max_lines=args.max_lines,
                strategy=args.strategy,
                eval_workspace=Path(args.eval_workspace).expanduser() if args.eval_workspace else None,
                replay_workspace=Path(args.replay_workspace).expanduser() if args.replay_workspace else None,
            )
        except ValueError as exc:
            parser.error(str(exc))
        if args.json:
            print(process_payload_json(result, context=context))
        else:
            print(render_process_result(result, context=context))
        return 0

    if args.command == "draft":
        if args.draft_command == "memory":
            context = detect_context(Path(args.cwd) if args.cwd else None)
            source_parts = [args.text] if args.text else []
            if args.from_file:
                source_text = sys.stdin.read() if args.from_file == "-" else Path(args.from_file).expanduser().read_text(encoding="utf-8")
                source_parts.append(source_text)
            source_text = "\n".join(part for part in source_parts if part)
            if not source_text.strip():
                parser.error("draft memory requires text or --from-file")
            try:
                memory_draft = draft_memory(
                    source_text,
                    context=context,
                    provider=args.provider,
                    llm_profile=args.llm_profile,
                    llm_config_path=Path(args.llm_config) if args.llm_config else None,
                    topic=args.topic,
                    kind=args.kind,
                    max_chars=args.max_chars,
                )
            except ValueError as exc:
                parser.error(str(exc))
            if args.json:
                print(json.dumps(memory_draft.to_payload(context=context), ensure_ascii=False, indent=2))
            else:
                print(render_memory_draft(memory_draft, context=context))
            return 0

    if args.command == "trace":
        try:
            if args.trace_command == "list":
                print(store.compose_recall_trace_list(limit=args.limit))
                return 0
            if args.trace_command == "show":
                if args.json:
                    payload = store.load_recall_trace(args.identifier)
                    print(json.dumps(payload, ensure_ascii=False, indent=2))
                else:
                    print(store.compose_recall_trace(identifier=args.identifier))
                return 0
            if args.trace_command == "label":
                saved = store.label_recall_trace(
                    args.identifier,
                    rating=args.rating,
                    note=args.note,
                )
                feedback = saved.payload.get("feedback")
                rating = feedback.get("rating") if isinstance(feedback, dict) else args.rating
                print("[MemAgent recall trace labeled]")
                print(f"- id: {saved.identifier}")
                print(f"- rating: {rating}")
                print(f"- path: {saved.path}")
                return 0
            if args.trace_command == "report":
                print(store.compose_recall_trace_report(limit=args.limit))
                return 0
            if args.trace_command == "eval":
                result = run_trace_eval(
                    store=store,
                    workspace=Path(args.workspace).expanduser(),
                    limit=args.limit,
                )
                print("[MemAgent trace-eval]")
                print(f"- workspace: {result.workspace}")
                print(f"- memory home: {result.memory_home}")
                print(f"- report: {result.report_path}")
                print(f"- traces inspected: {result.traces_inspected}")
                print(f"- labeled: {result.labeled}")
                print(f"- useful_rate: {result.useful_rate:.2f}")
                return 0
            if args.trace_command == "replay":
                result = run_trace_replay(
                    store=store,
                    workspace=Path(args.workspace).expanduser(),
                    limit=args.limit,
                )
                print("[MemAgent trace-replay]")
                print(f"- workspace: {result.workspace}")
                print(f"- memory home: {result.memory_home}")
                print(f"- report: {result.report_path}")
                print(f"- traces inspected: {result.traces_inspected}")
                for strategy_result in result.strategy_results:
                    print(
                        f"- {strategy_result.strategy}: "
                        f"top_stability={strategy_result.top_stability:.2f}; "
                        f"useful_top_stability={strategy_result.useful_top_stability:.2f}"
                    )
                return 0
        except ValueError as exc:
            parser.error(str(exc))

    if args.command == "remember":
        context = detect_context()
        try:
            card = store.remember(
                text=args.text,
                topic=args.topic,
                domain=args.domain,
                kind=args.kind,
                repo=args.repo or context.repo_name,
                module=args.module,
                triggers=args.trigger,
                exportable=args.exportable,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(f"Saved memory: {card.path}")
        return 0

    if args.command == "handoff":
        handoff_store = HandoffStore(store.home)
        context = detect_context(Path(args.cwd) if getattr(args, "cwd", None) else None)
        if args.handoff_command == "save":
            try:
                saved = handoff_store.save(
                    context=context,
                    summary=args.summary,
                    topic=args.topic,
                    done=args.done,
                    next_steps=args.next_step,
                    open_questions=args.open_question,
                    memory_candidates=args.memory_candidate,
                )
            except ValueError as exc:
                parser.error(str(exc))
            print("[MemAgent handoff saved]")
            print(f"- project key: {saved.project_key}")
            print(f"- latest: {saved.latest_path}")
            print(f"- history: {saved.history_path}")
            return 0
        if args.handoff_command == "show":
            print(
                handoff_store.compose_latest(
                    context=context,
                    max_lines=args.max_lines,
                    show_source=not args.no_source,
                )
            )
            return 0
        if args.handoff_command == "draft":
            source_path = None if args.from_file == "-" else Path(args.from_file).expanduser().resolve()
            source_text = sys.stdin.read() if args.from_file == "-" else source_path.read_text(encoding="utf-8")
            try:
                draft = draft_handoff_from_text(
                    source_text,
                    topic=args.topic,
                    max_items=args.max_items,
                )
            except ValueError as exc:
                parser.error(str(exc))
            print(render_handoff_draft(draft, source=source_path))
            if args.save:
                saved = handoff_store.save_draft(context=context, draft=draft)
                print("")
                print("[MemAgent handoff saved]")
                print(f"- project key: {saved.project_key}")
                print(f"- latest: {saved.latest_path}")
                print(f"- history: {saved.history_path}")
            return 0
        if args.handoff_command == "promote":
            try:
                selection = handoff_store.promotion_selection(
                    context=context,
                    indices=args.index,
                    select_all=args.all,
                )
                print(render_promotion_preview(selection, write=args.write))
                if args.write:
                    for index, candidate in zip(selection.selected_indices, selection.selected_candidates):
                        saved = store.remember(
                            text=candidate,
                            topic=f"Handoff candidate {index}: {candidate[:48]}",
                            domain="coding",
                            kind=args.kind,
                            repo=context.repo_name,
                            module=args.module,
                            triggers=args.trigger,
                            exportable=args.exportable,
                        )
                        print(f"- Saved memory: {saved.path}")
                    print("- Status: promoted")
            except ValueError as exc:
                parser.error(str(exc))
            return 0

    if args.command == "recall":
        context = detect_context()
        matches = store.recall(args.query, context=context, limit=args.limit, strategy=args.strategy)
        payload = store.build_recall_payload(
            query=args.query,
            context=context,
            matches=matches,
            max_lines=args.max_lines,
            show_sources=args.show_sources,
            show_reasons=args.show_reasons,
        )
        saved_trace = store.save_recall_trace(payload, source="cli") if args.trace else None
        output_payload = saved_trace.payload if saved_trace else payload
        if args.json:
            print(json.dumps(output_payload, ensure_ascii=False, indent=2))
        else:
            print(output_payload["text"])
            if saved_trace:
                print("")
                print("[MemAgent recall trace saved]")
                print(f"- id: {saved_trace.identifier}")
                print(f"- path: {saved_trace.path}")
        return 0

    if args.command == "codex":
        context = detect_context()
        preflight_context = ""
        if not args.no_memory:
            try:
                result = process_interaction(
                    message=args.prompt,
                    recent_text="",
                    context=context,
                    store=store,
                    handoff_store=HandoffStore(store.home),
                    provider=args.provider,
                    llm_profile=args.llm_profile,
                    llm_config_path=Path(args.llm_config) if args.llm_config else None,
                    allow_writes=not args.no_write,
                    trace_recall=not args.no_trace,
                    trace_none=args.trace_none,
                    limit=args.limit,
                    max_lines=args.max_lines,
                    show_sources=args.show_sources,
                    show_reasons=args.show_reasons,
                    strategy=args.strategy,
                )
            except ValueError as exc:
                parser.error(str(exc))
            preflight_context = process_result_context_for_prompt(result)
        final_prompt = build_augmented_prompt(args.prompt, preflight_context)
        if args.dry_run:
            print(final_prompt)
            return 0
        cmd = [args.codex_bin, *normalize_remainder(args.codex_args), final_prompt]
        return subprocess.run(cmd, check=False).returncode

    parser.error(f"unknown command: {args.command}")
    return 2


def normalize_remainder(items: list[str]) -> list[str]:
    if items and items[0] == "--":
        return items[1:]
    return items


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
