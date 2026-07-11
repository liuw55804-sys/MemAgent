---
name: memagent
description: Local-first workflow memory for coding-agent sessions. Use it for non-trivial work that may benefit from earlier project lessons, or when the user naturally asks to continue, remember a reusable lesson, react to recalled advice, or check memory activity. Skip tiny mechanical edits and generic questions.
---

# MemAgent

<!-- memagent:user-codex-skill -->

MemAgent is a quiet local memory layer. Keep the current repository, its
`AGENTS.md`, and its Git working tree untouched. Memory, pending drafts, and
activity evidence live under `~/.memagent/` unless `MEMAGENT_HOME` is set.

Run this command from the current project directory:

```bash
__MEMAGENT_COMMAND__ process "<latest user message>"
```

Follow the result without making MemAgent the focus of ordinary work:

- `recall`: use the short context as a hint, then verify against live code,
  tests, documentation, and command output.
- `draft_memory`: show the preview and wait for explicit confirmation.
- `label_feedback`: acknowledge the natural-language feedback.
- `handoff_show` / `handoff_save`: use the project continuation state.
- `none`: continue normally.

Natural requests are intent, not a rigid keyword list:

- “What did we learn last time?” or “continue from where we left off” may use
  recall or handoff.
- “Remember this workaround” or “save this lesson” drafts a memory preview.
- “Save it” saves only the already previewed draft.
- “That was helpful” or “not relevant” labels the latest recall when present.
- “How has MemAgent been doing?” shows local project activity.

Configuration can also start from natural language, but never ask the user to
paste a key into chat:

- “Switch MemAgent back to local mode” runs `__MEMAGENT_COMMAND__ configure --mode heuristic`.
- “Use my configured <profile> for hybrid memory decisions” first checks
  `__MEMAGENT_COMMAND__ llm doctor --profile "<profile>"`, then runs
  `__MEMAGENT_COMMAND__ configure --mode hybrid --profile "<profile>" --use-profile`
  only when the doctor reports the profile is in `~/.memagent/config.json`.
  A legacy inline-key profile must be migrated through an environment variable
  before it becomes the active profile.
- For a first provider setup, tell the user to set its API-key environment
  variable locally, then use `__MEMAGENT_COMMAND__ configure` with the provider's
  base URL, model, and environment-variable name. Do not write a key into a
  repository, `AGENTS.md`, or conversation transcript.

The default semantic mode is fully local heuristic routing. Optional LLM or
hybrid routing is configured explicitly with `memagent configure`. It only uses
short sanitized task summaries and draft candidates; never send a full
conversation, secrets, or raw request/response bodies.

Never save tokens, cookies, passwords, private keys, or raw sensitive samples.
Do not automatically create durable memories: a preview and explicit user
confirmation are always required.
