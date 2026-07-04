from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import textwrap

from memagent.context import ProjectContext


MEMAGENT_BLOCK_START = "<!-- memagent:start -->"
MEMAGENT_BLOCK_END = "<!-- memagent:end -->"
MEMAGENT_SECTION_HEADING = "## MemAgent Natural Language Triggers"


@dataclass(frozen=True)
class AgentsFileCheck:
    path: Path
    has_memagent_section: bool
    has_recall_command: bool
    has_remember_command: bool
    has_explainable_recall: bool

    @property
    def is_ready(self) -> bool:
        return (
            self.has_memagent_section
            and self.has_recall_command
            and self.has_remember_command
            and self.has_explainable_recall
        )


@dataclass(frozen=True)
class AgentsInstallPlan:
    target: Path
    action: str
    changed: bool
    blocked: bool
    reason: str
    next_content: str
    snippet: str


def default_memagent_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_agents_snippet(memagent_root: Path | None = None) -> str:
    root = (memagent_root or default_memagent_root()).expanduser().resolve()
    src_path = root / "src"
    command_prefix = f"PYTHONPATH={src_path} python -m memagent.cli"
    body = textwrap.dedent(
        f"""
        ## MemAgent Natural Language Triggers

        MemAgent is a local workflow memory layer for Codex/coding-agent sessions.
        Use it when the user explicitly asks to recall or save reusable workflow memory.

        ### Recall

        When the user says phrases like:

        - `召回一下相关记忆`
        - `先看看之前有没有相关经验`
        - `有没有以前踩过类似坑`
        - `用 MemAgent 看看`
        - `查一下 MemAgent memory`

        Run:

        ```bash
        {command_prefix} recall "<user task>" --show-sources --show-reasons
        ```

        Then use the recalled context as hints only. Continue checking live code,
        schemas, docs, command output, and tool results before acting.

        ### Remember

        When the user says phrases like:

        - `记住这个`
        - `沉淀一下`
        - `下次别再踩这个坑`
        - `把这次排查做成 memory`
        - `保存为 MemAgent 记忆`

        Summarize one short, actionable memory from the current thread, choose a
        suitable `kind`, then run:

        ```bash
        {command_prefix} remember \\
          --domain coding \\
          --kind <kind> \\
          --topic "<short topic>" \\
          --trigger "<keyword>" \\
          "<short actionable memory>"
        ```

        Kind guide:

        - `tool_recipe`: reusable CLI/MCP/bytedcli command or tool usage
        - `skill_route`: use an existing skill for a task family
        - `data_entrypoint`: database, table, API, config, or doc entrypoint
        - `pitfall`: failed path or repeated mistake to avoid
        - `verification`: how to verify a change or diagnosis
        - `workflow`: multi-step debugging or implementation flow
        - `note`: fallback when no specific kind fits

        ### Safety

        - Treat recalled memories as hints, not source of truth.
        - Verify with live code, schemas, docs, command output, and tool results.
        - Local private memories may keep exact reusable engineering entrypoints,
          such as command syntax, database/table names, API paths, headers, and
          environment names, when those details are the reusable lesson.
        - Never store tokens, cookies, passwords, private keys, raw sensitive
          business samples, long query results, or large request/response bodies.
        - Generalize or redact memories before public demos, exports, resumes, or
          shared examples.
        - Keep stable repo rules in AGENTS.md; keep dynamic workflow lessons in
          MemAgent.
        """
    ).strip()
    return f"{MEMAGENT_BLOCK_START}\n{body}\n{MEMAGENT_BLOCK_END}"


def build_agents_doctor_report(
    *,
    context: ProjectContext,
    memory_home: Path,
    memory_count: int,
    memagent_root: Path | None = None,
) -> str:
    root = (memagent_root or default_memagent_root()).expanduser().resolve()
    command_prefix = f"PYTHONPATH={root / 'src'} python -m memagent.cli"
    checks = [_check_agents_file(path) for path in context.agents_files]
    ready = any(check.is_ready for check in checks)

    lines = [
        "[MemAgent AGENTS.md doctor]",
        f"- cwd: {context.cwd}",
        f"- repo: {context.repo_name or 'unknown'}",
        f"- git root: {context.git_root or 'unknown'}",
        f"- branch: {context.branch or 'unknown'}",
        f"- memory home: {memory_home.expanduser().resolve()}",
        f"- memory cards: {memory_count}",
    ]

    if not checks:
        lines.append("- AGENTS.md files: none found")
    else:
        lines.append("- AGENTS.md files:")
        for check in checks:
            state = "ready" if check.is_ready else "incomplete"
            lines.append(f"  - {check.path}: {state}")
            lines.append(f"    - MemAgent section: {_yes_no(check.has_memagent_section)}")
            lines.append(f"    - recall command: {_yes_no(check.has_recall_command)}")
            lines.append(f"    - remember command: {_yes_no(check.has_remember_command)}")
            lines.append(f"    - explainable recall: {_yes_no(check.has_explainable_recall)}")

    if ready:
        lines.extend(
            [
                "- Status: ready",
                (
                    '- Next step: in Codex, say "召回一下相关记忆，<your task>"; '
                    "MemAgent should be called from AGENTS.md instructions."
                ),
            ]
        )
    else:
        lines.extend(
            [
                "- Status: setup needed",
                "- Next step: generate the current snippet and paste it into the target AGENTS.md:",
                f"  {command_prefix} agents-snippet",
            ]
        )
    return "\n".join(lines)


def build_agents_install_plan(
    *,
    context: ProjectContext,
    target: Path | None,
    memagent_root: Path | None = None,
    replace_existing: bool = False,
) -> AgentsInstallPlan:
    target_path = ((target or (context.cwd / "AGENTS.md")).expanduser().resolve())
    snippet = build_agents_snippet(memagent_root)
    if not target_path.exists():
        return AgentsInstallPlan(
            target=target_path,
            action="create",
            changed=True,
            blocked=False,
            reason="target AGENTS.md does not exist",
            next_content=f"{snippet}\n",
            snippet=snippet,
        )

    raw = target_path.read_text(encoding="utf-8", errors="replace")
    marked = _replace_marked_block(raw, snippet)
    if marked is not None:
        changed = marked != raw
        return AgentsInstallPlan(
            target=target_path,
            action="replace-marked" if changed else "noop",
            changed=changed,
            blocked=False,
            reason="managed MemAgent block found",
            next_content=marked,
            snippet=snippet,
        )

    if MEMAGENT_SECTION_HEADING in raw:
        if not replace_existing:
            return AgentsInstallPlan(
                target=target_path,
                action="blocked",
                changed=False,
                blocked=True,
                reason=(
                    "existing unmarked MemAgent section found; rerun with "
                    "--replace-existing to replace that section"
                ),
                next_content=raw,
                snippet=snippet,
            )
        replaced = _replace_unmarked_section(raw, snippet)
        return AgentsInstallPlan(
            target=target_path,
            action="replace-existing",
            changed=replaced != raw,
            blocked=False,
            reason="existing unmarked MemAgent section replaced",
            next_content=replaced,
            snippet=snippet,
        )

    separator = "\n\n" if raw.strip() else ""
    next_content = f"{raw.rstrip()}{separator}{snippet}\n"
    return AgentsInstallPlan(
        target=target_path,
        action="append" if raw.strip() else "create",
        changed=next_content != raw,
        blocked=False,
        reason="no existing MemAgent block found",
        next_content=next_content,
        snippet=snippet,
    )


def render_agents_install_report(plan: AgentsInstallPlan, *, write: bool) -> str:
    mode = "write" if write else "dry-run"
    lines = [
        "[MemAgent AGENTS.md install]",
        f"- target: {plan.target}",
        f"- mode: {mode}",
        f"- action: {plan.action}",
        f"- changed: {_yes_no(plan.changed)}",
        f"- blocked: {_yes_no(plan.blocked)}",
        f"- reason: {plan.reason}",
    ]
    if plan.blocked:
        lines.append("- Status: blocked")
    elif write and plan.changed:
        lines.append("- Status: written")
    elif write:
        lines.append("- Status: already up to date")
    else:
        lines.append("- Status: preview only; rerun with --write to apply")

    if not write and not plan.blocked and plan.changed:
        lines.extend(
            [
                "",
                "[Snippet to install]",
                plan.snippet,
            ]
        )
    return "\n".join(lines)


def write_agents_install_plan(plan: AgentsInstallPlan) -> None:
    if plan.blocked or not plan.changed:
        return
    plan.target.parent.mkdir(parents=True, exist_ok=True)
    plan.target.write_text(plan.next_content, encoding="utf-8")


def _check_agents_file(path: Path) -> AgentsFileCheck:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return AgentsFileCheck(
        path=path.resolve(),
        has_memagent_section="MemAgent" in raw and "Natural Language Triggers" in raw,
        has_recall_command="memagent.cli recall" in raw,
        has_remember_command="memagent.cli remember" in raw,
        has_explainable_recall="--show-reasons" in raw,
    )


def _replace_marked_block(raw: str, snippet: str) -> str | None:
    start = raw.find(MEMAGENT_BLOCK_START)
    end = raw.find(MEMAGENT_BLOCK_END)
    if start < 0 or end < 0 or end < start:
        return None
    end += len(MEMAGENT_BLOCK_END)
    return f"{raw[:start]}{snippet}{raw[end:]}"


def _replace_unmarked_section(raw: str, snippet: str) -> str:
    start = raw.find(MEMAGENT_SECTION_HEADING)
    if start < 0:
        return raw
    line_start = raw.rfind("\n", 0, start) + 1
    next_heading = raw.find("\n## ", start + len(MEMAGENT_SECTION_HEADING))
    if next_heading < 0:
        prefix = raw[:line_start].rstrip()
        separator = "\n\n" if prefix else ""
        return f"{prefix}{separator}{snippet}\n"
    prefix = raw[:line_start].rstrip()
    suffix = raw[next_heading:].lstrip("\n")
    separator = "\n\n" if prefix else ""
    return f"{prefix}{separator}{snippet}\n\n{suffix}"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
