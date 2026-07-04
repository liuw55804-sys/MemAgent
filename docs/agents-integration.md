# AGENTS.md Integration

MemAgent can be triggered from Codex through project or global `AGENTS.md` instructions.

The MVP integration uses the Python module path directly, so the `memagent` command does not need to be installed first:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli <command>
```

## Natural Language Triggers

Generate the current recommended snippet with:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli agents-snippet
```

Copy the output into a project or global `AGENTS.md`, or use the safe installer:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli agents-install
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli agents-install --write
```

`agents-install` is dry-run by default. It writes only when `--write` is present.
It uses Markdown markers around the MemAgent block so future installs can safely
replace MemAgent's own section without touching unrelated project rules.

After copying the snippet, check the integration with:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli agents-doctor
```

The doctor report checks whether an `AGENTS.md` file is visible from the current
directory, whether it contains MemAgent recall/remember/handoff/trace commands, and
whether recall uses `--show-reasons --strategy bm25` for explainable BM25-style
demos.

For a full mock demo transcript, run:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli demo-run --reset
```

For a mock retriever evaluation report, run:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli recall-eval
```

For MCP clients, MemAgent also exposes the same memory operations through a
local stdio server:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli mcp-stdio
```

When the user says:

- `记住这个`
- `沉淀一下`
- `下次别再踩这个坑`
- `把这次排查做成 memory`

Codex should summarize the lesson and call:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli remember \
  --domain coding \
  --kind <kind> \
  --topic "short topic" \
  --trigger keyword \
  "short actionable memory"
```

When the user says:

- `先看看之前有没有相关经验`
- `召回一下相关记忆`
- `用 MemAgent 查一下`
- `有没有以前踩过类似坑`

Codex should call:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli recall "short query" --show-sources --show-reasons --strategy bm25
```

`--show-sources` shows which memory card was used. `--show-reasons` shows the
simple score and matched query terms, which makes the recall result easier to
debug and demo. `--strategy bm25` uses the default BM25-style retriever
explicitly, so the AGENTS.md rule documents the RAG scoring strategy.

When the user says:

- `上次做到哪`
- `接着上次继续`
- `catch me up`
- `where did we leave off`

Codex should call:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli handoff show
```

When the user says:

- `交接一下`
- `记录当前进展`
- `下次接着做`
- `保存一个 handoff`
- `生成 handoff draft`

If a session note, transcript, or summary file is available, Codex should draft
first:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli handoff draft --from-file "path/to/session_notes.md"
```

After the user accepts the draft, Codex can save it:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli handoff draft --from-file "path/to/session_notes.md" --save
```

If no source file is available, Codex should summarize the current thread and
call:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli handoff save \
  --topic "short topic" \
  --done "completed item" \
  --next-step "recommended next step" \
  --open-question "open question if any" \
  --memory-candidate "possible durable lesson if any" \
  "short handoff summary"
```

Use `handoff` for recent continuation state. Use `remember` only for durable
workflow lessons that should be reusable beyond this one continuation.

When the user says:

- `把 handoff 里的候选记忆沉淀一下`
- `promote handoff candidate`
- `把这条 handoff candidate 变成长期 memory`

Codex should preview first:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli handoff promote --index 1
```

Only after the user accepts the preview, Codex should write:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli handoff promote --index 1 --write
```

Promotion writes durable memory cards, so do not skip the preview step.

When the user says:

- `这次召回有用`
- `这次召回没用`
- `这个 memory 不相关`
- `标记这次 recall 有用`
- `给这次召回打个标签`

Codex should label the latest saved recall trace:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli trace label --rating useful --note "short reason"
```

Use `useful` when the recalled memory helped, `not-useful` when it was wrong or
stale, and `neutral` when the result was inconclusive. To summarize recent trace
feedback, call:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli trace report
```

## Safety

- Treat recalled memories as hints, not source of truth.
- Always verify with live code, schemas, docs, and command output.
- For local private memory, keep exact tool recipes when they are the reusable lesson, including needed command syntax, database names, table names, API paths, headers, and environment names.
- Never store secrets such as tokens, passwords, cookies, private keys, or raw sensitive business samples.
- Avoid storing long raw query results or large request/response bodies; summarize them and keep only reusable command shape, field path, or diagnosis.
- Create a separate generalized version when exporting or demoing memories publicly.
- Keep stable repo rules in `AGENTS.md`; keep dynamic workflow lessons in MemAgent.

## Installed Workspace

The attribution workspace currently has MemAgent trigger rules in:

```text
/Users/bytedance/Desktop/work/attribution/AGENTS.md
```

New Codex threads opened in that workspace will load those rules at session start.
