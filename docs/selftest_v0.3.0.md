# MemAgent v0.3.0 Product Self-test

Use a normal coding project with the user-level Codex Skill installed. Speak
normally; do not start with trace or eval commands.

## 1. Relevant task versus broad preference

Ask about a concrete workflow that has a saved task memory and also shares words
with a general project preference.

Expected: at most one concrete task memory is shown. The preference is omitted
unless the question explicitly asks about habits, constraints, or conventions.

## 2. Repeated recall

Ask two questions in the same Codex task that would return the same memory, then
open a new Codex task and ask again.

Expected: the first may show the memory; the second continues quietly even if
the wording adds another matching term. The new Codex task may show it again.
Running `memagent recall "<specific question>"` explicitly can always inspect
it.

## 3. Provider failure

In `hybrid` mode, temporarily use an unavailable test endpoint and ask an
ambiguous memory question twice.

Expected: the first attempt fails within about three seconds. After repeated
failure, later ambiguous checks skip the provider during cooldown and abstain
locally. No API key is printed.

## 4. Pending preview lifecycle

Let Codex suggest a reusable lesson, do not confirm it, then produce a different
reusable lesson.

Expected: a different agent suggestion may replace the previous one. A preview
you explicitly requested is not replaced. Unattended previews expire after 48
hours by default.

## 5. Worktree activity and adoption

Use MemAgent once in a repository and once in one of its Git worktrees. When a
recalled instruction materially changes the work, let Codex finish the action.

Expected:

- `memagent activity --cwd <main-or-worktree> --today` aggregates both paths;
- activity reports adoption only when the advice was applied, executed, or
  corrected, not merely displayed;
- neither checkout has MemAgent-created Git changes.

## Review

```bash
memagent activity --cwd <project> --since YYYY-MM-DD
memagent user-codex-doctor
```

Review emitted, abstained, cooldown-suppressed, LLM attempted/fallback/skipped,
draft statuses, and adoption separately. Treat counts as product evidence, not
accuracy, until recalls receive human relevance labels.
