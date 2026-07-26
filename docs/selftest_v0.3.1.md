# MemAgent v0.3.1 Product Self-test

## Same Codex task

In a project with a relevant saved memory, ask a concrete question that recalls
it. Later in the same task, ask another matching question.

Expected: the memory appears at most once. Codex should use the copy already in
the task context instead of calling attention to it again.

## New Codex task

Open a new Codex task in the same project and ask the matching question again.

Expected: the memory is eligible immediately; there is no six-hour wait.

## Explicit inspection

From either task, explicitly run:

```bash
memagent recall "<specific question>"
```

Expected: explicit inspection still returns the matching memory when relevant.

## Evidence

```bash
memagent activity --cwd <project> --today
```

Expected: retrieval shows session-scoped cooldown checks and any suppressed
repeat. It never displays the Codex task identifier. The project Git status
remains unchanged.
