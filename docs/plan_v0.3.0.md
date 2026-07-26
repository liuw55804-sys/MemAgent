# MemAgent v0.3.0 Plan

## Product goal

Make hybrid recall reliable during daily coding: fewer irrelevant preferences,
no repeated LLM waiting, and lifecycle evidence that reflects actual use.

## Scope

1. Fail fast when the optional LLM relevance gate is unhealthy, then cool down
   repeated attempts locally.
2. Rank concrete task memory ahead of broad project preferences and constraints.
3. Suppress repeated implicit recall of the same memory within one Codex task.
   Without a session identity, use the six-hour new-signal-aware fallback.
4. Expire or replace unattended agent-suggested drafts without overwriting a
   user-requested preview.
5. Aggregate activity across Git worktrees with one canonical local identity.
6. Record adoption only when recalled advice changes or is corrected during
   work; display alone is not usefulness.

## Local state

All new state remains under `~/.memagent/`:

- `runtime/llm_gate_health.json`: provider failure count and cooldown only.
- `runtime/recall_cooldown.json`: hashed project/session identity, memory ID,
  terms, and last emission.
- `pending_memory_drafts/archive/`: expired, replaced, confirmed, and rejected
  preview outcomes.
- `recall_traces/*.json`: optional explicit feedback and lightweight adoption.

No full conversation, API key, remote URL, or business repository file is
written by these features.

## Acceptance

- A failed LLM gate does not delay each following interaction.
- Generic project preference does not displace a concrete task memory.
- Repeated implicit recall can abstain, while explicit CLI recall still works.
- Old pending suggestions stop blocking new useful suggestions.
- Main checkout and worktree activity are reported together.
- Tests run offline regardless of the developer's active MemAgent profile.

## Non-goals

- Embeddings or a vector database.
- Automatic durable memory writes.
- Background daemon or repository-level integration.
- Claiming retrieval accuracy without human relevance labels.
