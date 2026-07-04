# MemAgent v0.19 Trace Feedback Integration Design

## 1. Goal

Expose trace feedback through the two agent-facing integration surfaces:

- `AGENTS.md` natural-language triggers for Codex
- MCP tools for MCP-capable coding agents

v0.18 added `trace label/report` as CLI commands. v0.19 makes those commands
discoverable and callable by agents.

## 2. AGENTS.md Trigger

The generated snippet now includes recall feedback phrases such as:

- `这次召回有用`
- `这次召回没用`
- `这个 memory 不相关`
- `标记这次 recall 有用`

Codex should translate those into:

```bash
memagent trace label --rating useful --note "<short reason>"
memagent trace report
```

This keeps the interaction natural: the user can give feedback in plain
language, while MemAgent keeps a structured label on the latest saved trace.

## 3. MCP Tools

New MCP tools:

| Tool | Type | Purpose |
|---|---|---|
| `memagent_trace_list` | read-only | List recent saved recall traces. |
| `memagent_trace_show` | read-only | Show one trace as text or JSON. |
| `memagent_trace_label` | write-capable | Label a trace as `useful`, `not-useful`, or `neutral`. |
| `memagent_trace_report` | read-only | Summarize labeled traces and useful rate. |

These tools reuse the same local JSON trace files and feedback fields as the CLI.

## 4. Interview Angle

This is the integration step that makes the feedback loop agentic:

> The system does not stop at recall. Codex can collect user feedback through
> natural language, and MCP clients can label/report recall traces through tools.
> That gives a path from local workflow memory to measurable, agent-driven RAG
> iteration.

## 5. Safety

Trace feedback remains local-first:

- traces are only saved when recall is run with `--trace`
- labels are written into local `~/.memagent/recall_traces/*.json`
- no external API, cloud sync, or hidden background recorder is introduced
