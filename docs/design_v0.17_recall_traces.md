# MemAgent v0.17 Recall Traces Design

## 1. Goal

Add opt-in recall telemetry so real MemAgent usage can be inspected later.

New commands:

```bash
memagent recall "attribution accuracy" --trace
memagent recall "attribution accuracy" --json --trace
memagent trace list
memagent trace show
memagent trace show --json
```

## 2. Why This Matters

`recall-eval` already gives MemAgent a mock benchmark, but mock evaluation does
not tell us how recall behaves in real Codex sessions.

Recall traces bridge that gap:

```text
real query
  -> ranked matches
  -> packed context
  -> saved trace JSON
  -> later review / evaluation / UI
```

This is still local-first. MemAgent does not record recall by default. The user
or integration must explicitly pass `--trace`.

## 3. Storage

Traces are stored under:

```text
~/.memagent/recall_traces/
  trace_YYYYMMDD_HHMMSS_microseconds.json
```

Each file contains the same `memagent.recall.v1` payload from v0.16 plus:

```json
{
  "trace": {
    "id": "trace_...",
    "created_at": "...",
    "source": "cli",
    "path": "..."
  }
}
```

## 4. CLI Behavior

Text recall with trace:

```text
[MemAgent recalled context]
...

[MemAgent recall trace saved]
- id: trace_...
- path: ...
```

JSON recall with trace remains valid JSON. The saved trace metadata is embedded
under the `trace` field.

`trace list` prints compact summaries:

```text
[MemAgent recall traces]
- trace_... | query='...' | repo=project | matches=1 | top=...
```

`trace show --json` prints the full saved trace.

## 5. Interview Angle

This makes the evaluation story more credible:

> I started with a mock recall benchmark, then added opt-in recall traces so real
> agent sessions can produce evaluation data. Each trace includes query, project
> context, ranked matches, context pack metadata, and prompt text. That gives a
> path from demo RAG to measurable RAG quality.

## 6. Future Extension

Recall traces enable:

- feedback labels such as useful / not useful
- recall precision metrics from real usage
- stale or conflicting memory detection
- UI timeline for "why did the agent remember this?"
- replay-based regression tests for retriever changes
