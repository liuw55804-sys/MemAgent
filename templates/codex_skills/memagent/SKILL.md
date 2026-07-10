---
name: memagent
description: Local-first workflow memory for coding-agent sessions. Use proactively for a non-trivial coding, debugging, data, or tool-heavy task that may repeat prior work, and when the user naturally asks to continue previous work, preserve a reusable lesson, react to recalled advice, or ask what MemAgent has done. Do not use for tiny mechanical edits or generic questions with no plausible benefit from prior project memory.
---

# MemAgent

<!-- memagent:user-codex-skill -->

Use MemAgent as a quiet local memory layer. Keep business repositories, their
`AGENTS.md` files, and their Git working trees untouched. All MemAgent state
lives under `~/.memagent/` unless the user explicitly changes `MEMAGENT_HOME`.

Run commands from the current project directory so MemAgent can infer `cwd`,
Git root, branch, and repository scope. The installed command is:

```bash
__MEMAGENT_COMMAND__
```

## Interaction Flow

For a likely memory-relevant task, run one process call before beginning work:

```bash
__MEMAGENT_COMMAND__ process "<latest user message>"
```

Follow its result:

- `recall`: use the short recalled context only as a hint, then verify with live
  code, schemas, docs, and command output.
- `draft_memory`: show the draft preview. Do not write a durable memory card
  until the user explicitly confirms it.
- `label_feedback`: acknowledge the ordinary-language feedback; the local trace
  has already been labeled.
- `handoff_show` / `handoff_save`: use the returned project continuation state.
- `none`: continue normally. Do not mention MemAgent merely because it checked.

Use `--provider openai-compatible --llm-profile <profile>` only when the user
asks to use or evaluate the configured LLM-assisted router. The default route
remains local heuristic routing.

When a user asks to preserve a lesson, include a short, verified description of
the lesson from the current conversation as `--recent-text`; do not pass a full
transcript. For a handoff save, use `--recent-text` for a compact summary of
done work, next step, and open question.

When the user confirms a previously shown memory preview, save exactly that
reviewed content with `remember`. Preserve its `topic`, `kind`, and triggers;
do not silently rewrite it or add unrelated context:

```bash
__MEMAGENT_COMMAND__ remember \
  --domain coding \
  --kind "<preview kind>" \
  --topic "<preview topic>" \
  --trigger "<preview trigger>" \
  "<approved memory text>"
```

## Natural Requests

Treat natural language such as the following as intent, not a rigid trigger list:

- "之前这个怎么查" / "按上次的思路继续" -> allow a recall or handoff.
- "记住这次踩坑" / "这个入口下次别忘了" -> draft a memory, preview it,
  then wait for confirmation before saving.
- "确认保存" -> save the already reviewed memory preview; do not ask the user
  to repeat its content.
- "刚刚那条有用" / "不是这个问题" -> allow trace feedback when a recent
  recall exists.
- "MemAgent 今天干了什么" -> run:

```bash
__MEMAGENT_COMMAND__ activity --today
```

Use an explicit project path only when the current shell directory differs from
the task directory:

```bash
__MEMAGENT_COMMAND__ activity --cwd "<project directory>" --today
```

## Safety

- Keep exact reusable engineering entrypoints in local private memory when they
  are the lesson, but never retain tokens, cookies, passwords, private keys, or
  raw sensitive request/response samples.
- Never make business-repository files or Git changes solely for MemAgent.
- Keep `AGENTS.md` for stable repository policy. Keep dynamic, user-private
  workflow lessons in MemAgent.
- Do not run trace eval or replay during normal coding work. Those are
  developer-quality tools, used only when the user asks to assess MemAgent.
