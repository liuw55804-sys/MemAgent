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
    has_handoff_command: bool
    has_trace_command: bool
    has_explainable_recall: bool
    has_bm25_strategy: bool

    @property
    def is_ready(self) -> bool:
        return (
            self.has_memagent_section
            and self.has_recall_command
            and self.has_remember_command
            and self.has_handoff_command
            and self.has_trace_command
            and self.has_explainable_recall
            and self.has_bm25_strategy
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
        Use it as a small background memory helper. The user does not need to
        know words like recall, trace, eval, replay, candidate, or handoff.

        When the intent is unclear, ask MemAgent's router for a read-only
        recommendation before choosing a memory action:

        ```bash
        {command_prefix} route "<latest user message>" --json
        ```

        ### Task-Start Memory Check

        Before a non-trivial coding, debugging, data, or tool-heavy task, decide
        whether prior workflow memory may help. Prefer a quick MemAgent check
        when the task mentions repeated domains, tools, repos, data entrypoints,
        or past failure signals such as:

        - `有没有以前踩过类似坑`
        - `之前是不是查过这个`
        - `又要查 bytedcli / RDS / owner`
        - `继续排查 audit_rule_lib`
        - `类似上次那个问题`
        - `先按你觉得最省时间的方式来`

        Run:

        ```bash
        {command_prefix} recall "<short user task>" --show-sources --show-reasons --strategy bm25 --trace
        ```

        Use the recalled context as hints only. Summarize any useful memory in
        one short sentence, then continue checking live code, schemas, docs,
        command output, and tool results before acting. If no memory is found,
        continue normally without making the missing memory the center of the
        conversation.

        Skip MemAgent for tiny edits, purely mechanical refactors, generic
        questions, or tasks where live code/docs are obviously sufficient.

        ### Opportunistic Memory Capture

        When the user says phrases like these, or when the thread clearly
        produced a reusable workflow lesson, draft a short memory preview first:

        - `记住这个`
        - `沉淀一下`
        - `下次别再踩这个坑`
        - `把这次排查做成 memory`
        - `保存为 MemAgent 记忆`
        - `这个入口下次别忘了`
        - `这个命令以后还会用`
        - `刚刚绕路的原因记一下`

        The preview should include `topic`, `kind`, `triggers`, and a 1-3
        sentence memory. Draft the preview first:

        ```bash
        {command_prefix} draft memory "<recent lesson text>"
        ```

        Ask the user to confirm before saving. After the user accepts the
        preview, run:

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

        At the end of a task, if a durable lesson appeared but the user did not
        explicitly ask to save it, suggest at most one memory candidate in plain
        language. Do not save it until the user confirms.

        ### Handoff / Catch-up

        When the user says phrases like:

        - `上次做到哪`
        - `接着上次继续`
        - `catch me up`
        - `where did we leave off`
        - `看看上次交接`

        Run:

        ```bash
        {command_prefix} handoff show
        ```

        Also use this when the user opens a new thread with vague continuation
        language such as `继续刚才的`, `接着做`, or `我们上回到哪了`.

        When the user says phrases like:

        - `交接一下`
        - `记录当前进展`
        - `下次接着做`
        - `保存一个 handoff`
        - `生成 handoff draft`
        - `先到这`
        - `换个会话继续`

        If a session note, transcript, or summary file is available, draft first:

        ```bash
        {command_prefix} handoff draft --from-file "<path-to-session-notes>"
        ```

        After the user accepts the draft, save it:

        ```bash
        {command_prefix} handoff draft --from-file "<path-to-session-notes>" --save
        ```

        If no source file is available, summarize the current thread into a
        short handoff, then run:

        ```bash
        {command_prefix} handoff save \\
          --topic "<short topic>" \\
          --done "<completed item>" \\
          --next-step "<recommended next step>" \\
          --open-question "<open question if any>" \\
          --memory-candidate "<possible durable lesson if any>" \\
          "<short handoff summary>"
        ```

        Use handoff for recent project state. Use `remember` only for durable
        lessons that should be reusable beyond the current continuation.

        ### Codex Transcript Ingest

        This is a review mode, not a normal daily interaction. Use it when the
        user wants to mine older Codex sessions for memory candidates:

        - `从旧 Codex 线程里找可沉淀经验`
        - `看看以前 Codex 会话有没有能做成 memory 的`
        - `从历史线程生成 memory candidates`
        - `ingest Codex sessions`

        Draft review-only memory candidates from recent local Codex sessions:

        ```bash
        {command_prefix} ingest codex --limit 5 --project-only
        ```

        This writes Markdown candidates under `local_memory_demo/ingest_codex`
        by default. Review and edit candidates before saving any durable memory
        with `remember`.

        ### Promote Handoff Candidates

        When the user says phrases like:

        - `把 handoff 里的候选记忆沉淀一下`
        - `promote handoff candidate`
        - `把这条 handoff candidate 变成长期 memory`

        Preview the promotion first:

        ```bash
        {command_prefix} handoff promote --index 1
        ```

        Only after the user accepts the preview, write the memory card:

        ```bash
        {command_prefix} handoff promote --index 1 --write
        ```

        ### Feedback From Ordinary Language

        When the user responds to a recalled memory with ordinary language like:

        - `这个有用`
        - `这条提醒是对的`
        - `刚刚那条没帮上忙`
        - `这个不相关`
        - `不是这个问题`

        Label the latest saved recall trace. Use `useful` when the memory helped,
        `not-useful` when it was wrong or stale, and `neutral` when the signal is
        inconclusive. Do not ask the user to say the word "trace".

        ```bash
        {command_prefix} trace label --rating useful --note "<short reason>"
        ```

        ### Developer Evaluation Mode

        Trace reports, eval, and replay are developer-facing quality tools.
        Do not run them during normal product work unless the user asks to
        evaluate MemAgent, prepare interview evidence, compare retrieval behavior,
        or inspect memory quality.

        To inspect recent feedback quickly, run:

        ```bash
        {command_prefix} trace report
        ```

        To write Markdown artifacts, prefer an explicit workspace path so reports
        do not scatter into the current service repo:

        ```bash
        {command_prefix} trace eval --workspace "<absolute-output-dir>/trace_eval"
        {command_prefix} trace replay --workspace "<absolute-output-dir>/trace_replay"
        ```

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
            lines.append(f"    - handoff command: {_yes_no(check.has_handoff_command)}")
            lines.append(f"    - trace command: {_yes_no(check.has_trace_command)}")
            lines.append(f"    - explainable recall: {_yes_no(check.has_explainable_recall)}")
            lines.append(f"    - BM25 strategy: {_yes_no(check.has_bm25_strategy)}")

    if ready:
        lines.extend(
            [
                "- Status: ready",
                (
                    '- Next step: in Codex, ask a normal project question like '
                    '"继续排查 audit_rule_lib 的 owner 问题" or "上次做到哪"; '
                    "MemAgent should stay in the background unless it helps."
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
        has_handoff_command="memagent.cli handoff" in raw,
        has_trace_command="memagent.cli trace" in raw,
        has_explainable_recall="--show-reasons" in raw,
        has_bm25_strategy="--strategy bm25" in raw,
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
