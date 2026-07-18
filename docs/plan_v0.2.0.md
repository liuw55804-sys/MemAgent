# MemAgent v0.2.0 Plan

## Product goal

Reduce distracting recall and help Codex notice reusable lessons without asking
the user to remember MemAgent during every task.

## Recall

1. Route natural interaction to recall only when prior workflow memory may help.
2. Use local BM25 to generate project-scoped candidates.
3. Apply a local relevance policy that ignores generic words and unstable IDs.
4. Emit at most one high-confidence memory or abstain.
5. In `hybrid` or `llm` mode, send only ambiguous sanitized summaries to an
   optional LLM relevance gate.

## Capture

At a meaningful task boundary, the Codex Skill may suggest one short memory for
a detour, correction, verified entrypoint, costly investigation, workflow, or
project boundary. MemAgent suppresses duplicates and concurrent previews. The
user must confirm before durable saving and may reject in ordinary language.

## Evidence

- Public sanitized recall fixtures and end-to-end temporary Git tests.
- Local activity counts for considered, emitted, abstained, LLM-gated, suggested,
  accepted, rejected, duplicate, and pending events.
- Private historical trace replay stays under `~/.memagent/`, outside Git.

## Non-goals

- Vector database or embedding service.
- Automatic durable memory writes.
- Full transcript upload.
- Business-repository modification or repository-level `AGENTS.md` integration.
