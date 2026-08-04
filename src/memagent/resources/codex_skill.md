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
- `reject_memory`: acknowledge that the pending preview was discarded.
- `label_feedback`: acknowledge the natural-language feedback.
- `handoff_show` / `handoff_save`: use the project continuation state.
- `none`: continue normally.

Natural requests are intent, not a rigid keyword list:

- “What did we learn last time?” or “continue from where we left off” may use
  recall or handoff.
- “Remember this workaround” or “save this lesson” drafts a memory preview.
- “Save it” saves only the already previewed draft.
- “Don't save this” discards only the pending preview.
- “That was helpful” or “not relevant” labels the latest recall when present.
- “How has MemAgent been doing?” shows local project activity.

After recalled advice materially changes the work, record one small adoption
signal:

```bash
__MEMAGENT_COMMAND__ trace adopt --signal <applied|executed|corrected> --note "<short evidence>"
```

Use `applied` when it changed the plan, `executed` after following the recalled
workflow, and `corrected` when live evidence proved it wrong. Do not record
adoption merely because a memory was displayed. Keep the note short and free of
raw business data.

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

Before the final reply for a non-trivial task, perform one quiet task-boundary
reflection when the work produced concrete evidence that may be reusable:

- a meaningful detour or repeated failed path;
- a user correction that changes the workflow;
- a verified entrypoint, command, schema, or validation step;
- a costly investigation with a shorter repeatable path;
- a stable project boundary or multi-step workflow.

Do not reflect on routine edits, generic questions, unverified guesses, or tiny
mechanical work. Pass a short sanitized account of what went wrong, what changed,
and how the outcome was verified. Do not pre-decide that it must become a memory,
and never pass the full transcript or raw command output:

```bash
__MEMAGENT_COMMAND__ reflect \
  --summary "<short sanitized task reflection>" \
  --signal <detour|correction|verified_entrypoint|costly_investigation|workflow|project_boundary|verified_outcome>
```

Repeat `--signal` only when multiple evidence types genuinely apply. MemAgent
decides whether to abstain or create one preview. For `action: none`, finish the
task normally without mentioning MemAgent. For `action: draft_memory`, show one
natural sentence describing the candidate and ask whether to remember it. A
duplicate, a second suggestion in the same Codex task, or weak evidence is
skipped automatically. A different agent suggestion may replace an older agent
suggestion, but never replaces a user-requested preview. Unattended previews
expire locally. The user can confirm in ordinary language or reject it; neither
path changes the project repository.

The lower-level `memagent suggest` command remains available when the coding
agent already has one exact reusable lesson, but normal automatic discovery
should use `reflect` so MemAgent, rather than the user, makes the interruption
decision.

Never save tokens, cookies, passwords, private keys, or raw sensitive samples.
Do not automatically create durable memories: a preview and explicit user
confirmation are always required.
