# MemAgent v0.2.0 Product Self-test

Run this from a normal project after installing the user-level Codex Skill. Use
ordinary language in a new Codex task; do not invoke internal trace commands.

## 1. Precision recall

Ask a specific question that matches a saved workflow, then ask an unrelated
question containing only generic words or a long task ID.

Expected:

- the specific task receives at most one short memory;
- the generic task continues without memory and without delay becoming the
  center of the conversation;
- `memagent activity --cwd <project> --today` shows both considered events,
  with one emitted and one abstained.

## 2. Project preference versus task memory

Ask about a concrete merge conflict when both a merge workflow and a general
project preference exist.

Expected: the merge workflow wins. A same-project preference must not be
returned merely because feature names overlap.

## 3. Proactive suggestion acceptance

Complete a task that includes a real detour or user correction. Do not ask
MemAgent to remember it.

Expected: Codex offers at most one concise optional preview. Say “save it” and
verify that the next similar task can recall it. No project file changes.

## 4. Proactive suggestion rejection

When Codex offers a preview, say “don't save this one.”

Expected: the preview is discarded, no durable card is created, and activity
shows a rejected agent suggestion.

## 5. Quiet routine work

Perform several tiny edits or explanations.

Expected: no repeated memory prompts and no no-op trace noise by default.

## Review

After normal use, run:

```bash
memagent activity --cwd <project> --since YYYY-MM-DD
```

Review emitted versus abstained recall, local/LLM latency, and suggestion
accepted/rejected/pending counts. Product feedback can remain in the Codex task;
the activity report supplies the local evidence needed for later analysis.
