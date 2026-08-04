# MemAgent v0.4.0 Product Self-test

This self-test focuses on normal Codex use. The user should not need to ask
MemAgent to capture a lesson.

## 1. Install the current build

```bash
pipx install --force .
memagent install-user-codex --write
memagent user-codex-doctor
```

Expected: the doctor reports a callable installed `memagent` command and a
current managed user-level Skill. No project file changes.

## 2. Automatic candidate discovery

Open a new Codex task in a disposable Git project. Ask Codex to investigate a
small problem where the first plausible path is deliberately stale, but a live
contract or focused verification reveals the correct path. Do not mention
MemAgent or ask it to remember anything.

Expected: after completing and verifying the work, Codex asks one short natural
question about remembering the reusable lesson. It does not write a durable
memory yet. `git status --porcelain` remains empty unless the requested coding
task itself changed tracked files.

## 3. Confirmation lifecycle

Reply naturally with “save that lesson” or “确认保存”.

Expected: the pending preview becomes one memory card under `~/.memagent/`.
Repeat the scenario in a new Codex task with a clearly related question.

Expected: the confirmed lesson can be recalled. The original task does not show
more than one proactive suggestion.

## 4. Quiet abstention

Open another task and make a tiny mechanical edit, or fix a one-off spelling
mistake. Do not mention MemAgent.

Expected: Codex finishes normally without a memory question.

## 5. Rejection and duplication

When Codex offers a candidate, reply “don't save this”. Later reproduce the
same lesson after one copy has already been confirmed.

Expected: rejection creates no memory. A duplicate lesson is suppressed rather
than shown again.

## 6. Local evidence

```bash
memagent activity --cwd <project> --today
```

Expected: `Task reflections` reports considered, emitted, abstained, duplicate
or session suppression, average decision latency, and optional LLM fallback.
Reflection traces contain a summary length and hash, not the raw task reflection
or Codex session identifier.

## 7. Optional hybrid failure

With hybrid mode configured, temporarily make the provider unavailable and run
a meaningful task-boundary reflection.

Expected: MemAgent returns within the configured short timeout, records a local
fallback, and never writes durable memory without confirmation. A second failure
enters local cooldown so later task endings do not repeatedly wait.
