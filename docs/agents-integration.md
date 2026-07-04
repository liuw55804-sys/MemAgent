# AGENTS.md Integration

MemAgent can be triggered from Codex through project or global `AGENTS.md` instructions.

The MVP integration uses the Python module path directly, so the `memagent` command does not need to be installed first:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli <command>
```

## Natural Language Signals

The examples in this document are semantic guidance for Codex or an
LLM-assisted router. They are not a hard trigger-word list, and users should not
need to phrase requests in a special way.

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

For a shareable interview demo entrypoint, run:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli demo-bundle --reset
```

For a standalone MCP JSON-RPC transcript, run:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli mcp-demo --reset
```

For a mock retriever evaluation report, run:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli recall-eval
```

For a real trace-feedback evaluation report, run after saving and labeling
recall traces. Prefer an explicit output workspace:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli trace eval --workspace /absolute/output/trace_eval
```

For MCP clients, MemAgent also exposes the same memory operations through a
local stdio server:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli mcp-stdio
```

## Codex-Native Interaction Policy

The user should not need to know `recall`, `trace`, `eval`, `replay`, or
`candidate`. Codex should map ordinary task language to MemAgent operations.
In the best path, an LLM provider judges these interaction nodes; the local
heuristic router is the offline fallback and test baseline.
For the normal path, Codex can call one route-and-handle entrypoint:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli process "latest user message"
```

`process` may save local process traces for actionable memory operations so
later analysis can reconstruct which memory action was triggered. It still must
not write durable long-term memory cards without explicit preview and user
confirmation. No-op process traces are debug/self-test only.

When the intent is unclear, Codex can ask the read-only router first:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli route "latest user message" --json
```

When the user asks whether DeepSeek, Qwen, GLM, OpenAI, or another
OpenAI-compatible endpoint is ready for MemAgent, Codex can check local config
without spending tokens:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli llm doctor
```

For named local profiles in `~/.memagent/llm_providers.local.json`:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli llm doctor --profile deepseek
```

Only run a live provider request when the user explicitly asks to verify the API
call:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli llm doctor --profile deepseek --check-live
```

### Task-Start Memory Check

Before a non-trivial coding, debugging, data, or tool-heavy task, Codex should
decide whether prior workflow memory may help. This is especially useful when
the prompt mentions repeated domains, tools, repos, data entrypoints, or past
failure signals:

- `有没有以前踩过类似坑`
- `之前是不是查过这个`
- `又要查 bytedcli / RDS / owner`
- `继续排查 audit_rule_lib`
- `类似上次那个问题`
- `先按你觉得最省时间的方式来`

In the normal path, Codex should call `process` first so MemAgent can decide
whether recall is actually useful. If Codex already knows this is a task-start
memory check and wants tighter control, it can call:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli recall "short user task" --show-sources --show-reasons --strategy bm25 --trace
```

`--show-sources` shows which memory card was used. `--show-reasons` shows the
simple score and matched query terms, which makes the recall result easier to
debug and demo. `--strategy bm25` uses the default BM25-style retriever
explicitly, so the AGENTS.md rule documents the RAG scoring strategy.

Use the recalled context as hints only. Summarize a useful memory in one short
sentence, then continue checking live code, schemas, docs, command output, and
tool results. If no memory is found, continue normally.

Skip MemAgent for tiny edits, purely mechanical refactors, generic questions,
or tasks where live code/docs are obviously sufficient.

### Opportunistic Memory Capture

When the user says phrases like these, or when the thread clearly produced a
reusable workflow lesson, Codex should draft a short memory preview first:

- `记住这个`
- `沉淀一下`
- `下次别再踩这个坑`
- `把这次排查做成 memory`
- `这个入口下次别忘了`
- `这个命令以后还会用`
- `刚刚绕路的原因记一下`

The preview should include `topic`, `kind`, `triggers`, and a 1-3 sentence
memory. Codex can generate the preview with:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli draft memory "recent lesson text"
```

Only after the user accepts the preview, Codex should call:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli remember \
  --domain coding \
  --kind <kind> \
  --topic "short topic" \
  --trigger keyword \
  "short actionable memory"
```

At the end of a task, if a durable lesson appeared but the user did not ask to
save it, Codex may suggest at most one memory candidate in plain language. It
must not save it until the user confirms.

### Handoff / Catch-up

When the user says:

- `上次做到哪`
- `接着上次继续`
- `catch me up`
- `where did we leave off`
- `继续刚才的`
- `我们上回到哪了`

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
- `先到这`
- `换个会话继续`

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

### Codex Transcript Ingest

This is a review mode, not a normal daily interaction. Use it when the user
wants to mine older Codex sessions for memory candidates:

- `从旧 Codex 线程里找可沉淀经验`
- `看看以前 Codex 会话有没有能做成 memory 的`
- `从历史线程生成 memory candidates`
- `ingest Codex sessions`

Codex should draft review-only memory candidates:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli ingest codex --limit 5 --project-only
```

This writes Markdown drafts under `local_memory_demo/ingest_codex` by default.
Review and edit candidates before saving any durable memory with `remember`.

### Promote Handoff Candidates

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

### Feedback From Ordinary Language

When the user responds to a recalled memory with ordinary language:

- `这个有用`
- `这条提醒是对的`
- `刚刚那条没帮上忙`
- `这个不相关`
- `不是这个问题`

Codex should label the latest saved recall trace. Use `useful` when the memory
helped, `not-useful` when it was wrong or stale, and `neutral` when the signal
is inconclusive:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli trace label --rating useful --note "short reason"
```

Do not ask the user to say the word `trace`.

### Developer Evaluation Mode

Trace reports, eval, and replay are developer-facing quality tools. Do not run
them during normal product work unless the user asks to evaluate MemAgent,
prepare interview evidence, compare retrieval behavior, or inspect memory
quality.

To summarize recent trace feedback, call:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli trace report
```

When writing Markdown artifacts, prefer an explicit workspace path so reports do
not scatter into the current service repo:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli trace eval --workspace /absolute/output/trace_eval
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli trace replay --workspace /absolute/output/trace_replay
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
