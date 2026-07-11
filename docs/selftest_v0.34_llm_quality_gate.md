# v0.34 Product Self-Test: LLM Quality Gate

Use this in an ordinary Codex task after a genuine coding preference, decision,
or workflow lesson appears. The result is visible in the normal conversation;
MemAgent's local activity remains the evidence, so no manual trace log is
needed.

## One-Time Local Opt-In

First check that a named local profile is configured. This does not call the
provider:

```bash
PYTHONPATH=src python -m memagent.cli llm doctor --profile <local-profile-name>
```

For the current shell, opt in only for memory-draft quality:

```bash
export MEMAGENT_DRAFT_PROVIDER=openai-compatible
export MEMAGENT_DRAFT_LLM_PROFILE=<local-profile-name>
```

Do not put credentials in a service repository or its `AGENTS.md`.

## Real Conversation Path

1. During a real task, establish a reusable preference or workflow. For
   example: `在这个仓库默认只改当前需求相关代码，方案写到个人笔记目录。`

2. Ask naturally: `把这个习惯记住，先给我预览。`

3. Inspect the preview, not a trace file. It should state:
   - `kind: preference` for the example;
   - a quality label and short reason;
   - `quality_gate: llm_assisted` when the configured profile responds, or
     `heuristic_fallback` with a short provider-safe reason when it cannot.

4. Confirm only if the actual local draft is right: `确认保存`.
   Otherwise, state the correction in normal language and ask for a new
   preview. A preview alone must not create a long-term memory.

5. In the service repository run `git status --short`. It must be unchanged.
   The pending draft, process evidence, and saved card belong under
   `~/.memagent/`.

## What To Notice

This version is successful when the model improves classification of a
preference-like lesson without becoming a hidden writer or a full-context
upload path. A failed API should feel boring: the same preview still appears,
clearly marked as heuristic fallback.

After a few real uses, ask `MemAgent 最近做得怎么样？` in Codex. v0.33 activity
can show the resulting draft/save lifecycle; v0.34 adds the compact quality
gate evidence behind those events.
