# MemAgent v0.31 Process-First Codex Wrapper

Before v0.31, `memagent codex` was recall-first:

```text
prompt -> recall -> prompt prefix -> codex
```

That helped task-start memory, but it did not match the newer Codex-native UX.
The wrapper still forced one internal concept: recall.

v0.31 makes the wrapper process-first:

```text
prompt -> process -> preflight context -> codex
```

`process` can classify the prompt as recall, memory draft, feedback label,
handoff, developer eval, or no-op. The wrapper then passes only the useful
preflight result into the Codex prompt.

## Behavior

- `recall`: prepend clean recalled context to the Codex prompt.
- `draft_memory`: prepend a reviewable memory draft; durable memory is not
  saved automatically.
- `label_feedback`: label trace when writes are allowed, then expose the result
  to Codex.
- `handoff_show`: prepend latest handoff context.
- `handoff_save`: save continuation state when writes are allowed.
- `none`: pass the original prompt unchanged.

`--no-memory` still bypasses MemAgent completely.

## LLM Profiles

The wrapper accepts the same provider controls as `process`:

```bash
memagent codex \
  --provider openai-compatible \
  --llm-profile deepseek \
  "继续排查 audit_rule_lib owner 问题"
```

Profiles are read from:

```text
~/.memagent/llm_providers.local.json
```

## Safety Boundary

- `memagent codex` may save operational state such as recall traces, feedback,
  or handoff state.
- It must not save durable long-term memory cards.
- `--no-write` disables operational writes.
- `--no-trace` disables recall trace writes while keeping other preflight
  behavior.

## Interview Point

> I unified the wrapper with the same policy layer used by AGENTS.md and MCP.
> Instead of hard-coding recall into the Codex wrapper, it now runs the natural
> interaction processor first and only turns the result into prompt context when
> it helps.
