from __future__ import annotations

from pathlib import Path
import textwrap


def default_memagent_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_agents_snippet(memagent_root: Path | None = None) -> str:
    root = (memagent_root or default_memagent_root()).expanduser().resolve()
    src_path = root / "src"
    command_prefix = f"PYTHONPATH={src_path} python -m memagent.cli"
    return textwrap.dedent(
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
        {command_prefix} recall "<user task>" --show-sources
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

