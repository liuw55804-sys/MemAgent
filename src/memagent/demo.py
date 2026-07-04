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
from memagent.handoff import (
    HandoffStore,
    draft_handoff_from_text,
    render_handoff_draft,
    render_promotion_preview,
)
from memagent.memory import MemoryStore
from memagent.wrapper import build_augmented_prompt


DEMO_QUERY = "先看看之前有没有 attribution accuracy 的相关经验"
DEMO_CODEX_PROMPT = "我要继续排查 demo 服务 attribution accuracy，先给我一个排查计划"
DEMO_MEMORY = (
    "For demo attribution accuracy checks, start from the audit_label snapshot "
    "table, sample by primary-key ranges, then compare model output with "
    "human-reviewed labels. Avoid full-table JSON aggregation before sampling."
)
DEMO_HANDOFF = (
    "Demo session wired AGENTS.md, saved one attribution accuracy memory, and "
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
        "- Saved one mock attribution accuracy memory.",
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
        topic="Demo attribution accuracy entrypoint",
        domain="coding",
        kind="data_entrypoint",
        repo="demo_service",
        module="attribution",
        triggers=["attribution", "accuracy", "audit_label"],
        exportable=True,
    )
    steps.append(
        DemoStep(
            title="Remember a workflow memory",
            command=(
                f"{command_prefix} remember --domain coding --kind data_entrypoint "
                '--repo demo_service --module attribution '
                '--topic "Demo attribution accuracy entrypoint" '
                "--trigger attribution --trigger accuracy --trigger audit_label "
                f"{_quote(DEMO_MEMORY)}"
            ),
            output=f"Saved memory: {saved.path}",
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
        note="Demo recall found the intended attribution memory.",
    )
    steps.append(
        DemoStep(
            title="Label recall trace feedback",
            command=f"{command_prefix} trace label {structured_trace.identifier} --rating useful --note {_quote('Demo recall found the intended attribution memory.')}",
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


def _command_prefix(*, root: Path, memory_home: Path) -> str:
    return (
        f"MEMAGENT_HOME={_quote(memory_home)} "
        f"PYTHONPATH={_quote(root / 'src')} python -m memagent.cli"
    )


def _quote(value: str | Path) -> str:
    return shlex.quote(str(value))
