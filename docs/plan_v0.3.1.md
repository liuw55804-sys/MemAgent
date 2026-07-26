# MemAgent v0.3.1 Plan

## Product goal

Match recall suppression to how Codex context works: once a memory has been
shown in a task, Codex already has it; a new task starts clean and may need the
reminder again.

## Behavior

- Read `CODEX_THREAD_ID` from the process environment for normal Codex Skill
  calls.
- Inject each memory at most once per project and Codex task.
- Allow immediate recall in a different Codex task.
- Let `MEMAGENT_SESSION_ID` provide the same behavior for another integration.
- Fall back to the v0.3.0 six-hour, new-signal-aware policy when neither session
  variable exists.
- Keep explicit `memagent recall` outside implicit suppression.

## Privacy

The raw session identifier is used only in memory to derive a SHA-256 prefix.
Only that hash, project identity, memory ID, timestamp, and matched terms are
stored under `~/.memagent/runtime/recall_cooldown.json`. Session identifiers are
not written to recall or process traces.

## Acceptance

- Same memory, same task: first implicit recall may emit; later recalls abstain.
- Same memory, new task: eligible immediately.
- No session ID: existing time cooldown behavior remains.
- Activity exposes only `session` or `time`, never the identifier.
- Full tests, build, pipx install, Skill doctor, and temporary Git zero-intrusion
  verification pass.
