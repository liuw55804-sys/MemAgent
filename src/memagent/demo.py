from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
from memagent.memory import MemoryStore
from memagent.wrapper import build_augmented_prompt


DEMO_QUERY = "先看看之前有没有 attribution accuracy 的相关经验"
DEMO_CODEX_PROMPT = "我要继续排查 demo 服务 attribution accuracy，先给我一个排查计划"
DEMO_MEMORY = (
    "For demo attribution accuracy checks, start from the audit_label snapshot "
    "table, sample by primary-key ranges, then compare model output with "
    "human-reviewed labels. Avoid full-table JSON aggregation before sampling."
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
            command=f"{command_prefix} recall {_quote(DEMO_QUERY)} --show-sources --show-reasons",
            output=recalled_context,
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
                f"{command_prefix} codex --dry-run --show-sources --show-reasons "
                f"{_quote(DEMO_CODEX_PROMPT)}"
            ),
            output=final_prompt,
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
