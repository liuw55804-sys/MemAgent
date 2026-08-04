# Changelog

All notable public changes are recorded here.

## 0.4.0 - 2026-08-04

- `memagent reflect` lets a coding agent submit one short, sanitized task-boundary
  reflection and locally decides whether a reusable memory preview is warranted.
- Automatic discovery remains confirmation-first: reflection can create only a
  pending preview, never a durable memory card.
- Local reflection scoring uses explicit evidence signals, draft quality, duplicate
  checks, and a one-suggestion-per-Codex-task limit. Routine and transient mistakes
  abstain quietly.
- Optional `hybrid` and `llm` reflection gates receive only sanitized short summaries,
  reuse the existing three-second timeout and failure cooldown, and fall back locally.
- Reflection traces store decision metadata and a summary hash rather than the raw
  reflection. Activity reports expose the considered, emitted, abstained, duplicate,
  session-suppressed, latency, and LLM-fallback funnel.
- The user-level Codex Skill now performs task-boundary reflection before the final
  response after meaningful detours, corrections, verified entrypoints, or workflows.

## 0.3.1 - Unreleased

- Implicit recall cooldown is now Codex-session aware. The same memory is
  injected at most once per `CODEX_THREAD_ID`, while a new Codex task can
  receive it immediately.
- Session identifiers are hashed before local persistence and never appear in
  recall traces or activity output.
- Non-Codex integrations retain the existing six-hour time cooldown, including
  the new-discriminative-signal exception.
- Activity reports distinguish session-scoped and time-scoped cooldown checks.

## 0.3.0 - Unreleased

- Optional LLM relevance calls now use a three-second timeout and a local
  failure cooldown, preventing repeated provider delays after timeouts or rate
  limits.
- Local relevance separates task memories from project constraints. Concrete
  task evidence wins, while broad preferences require explicit constraint
  intent.
- Repeated implicit recall of the same memory is suppressed for six hours
  unless the new task adds discriminative evidence. Explicit `recall` remains
  available.
- Pending previews expire after 48 hours. A new agent suggestion may replace a
  different stale suggestion, while user-requested previews remain protected.
- Git worktrees share a canonical local project identity for activity,
  lifecycle, pending drafts, and recall cooldown without storing remote URLs.
- `trace adopt` records lightweight evidence that recalled advice was applied,
  executed, or corrected. Display alone is not counted as usefulness.
- Test suites explicitly isolate local semantic mode from developer-machine
  configuration and remain offline by default.

## 0.2.0 - Unreleased

- Precision-first recall now separates BM25 candidate generation from local
  relevance decisions, emits at most one memory, and abstains on weak evidence.
- Generic task words and unstable numeric identifiers no longer create recall
  relevance by themselves.
- Optional `hybrid` and `llm` modes can use a sanitized LLM relevance gate for
  ambiguous candidates, with local abstention on provider failure.
- The user-level Codex Skill can proactively suggest one memory preview after a
  meaningful detour, correction, verified entrypoint, or reusable workflow.
- Agent suggestions support confirmation, rejection, duplicate suppression,
  pending-preview limits, and local lifecycle metrics.
- `activity` distinguishes recall considered/emitted/abstained events and
  reports local/LLM latency plus proactive suggestion outcomes.

## 0.1.0 - Unreleased

First public-release candidate.

- Local-first memory cards, recall, preview-before-save, handoffs, and local
  activity evidence.
- Zero-intrusion user-level Codex Skill installed with
  `memagent install-user-codex --write`.
- Optional OpenAI-compatible semantic routing with `heuristic`, `llm`, and
  `hybrid` modes. Local heuristic routing remains the default.
- `memagent configure` and `memagent llm doctor` keep API keys in environment
  variables rather than configuration files.
- Build metadata, CI checks, contributor guidance, security policy, code of
  conduct, and Apache-2.0 licensing for public distribution.

Fixed:

- Questions about prior user coding preferences, habits, and project
  conventions now route to recall. Preference intent also adds local retrieval
  hints so a project-scoped preference can be found across common phrasing.
- Hybrid mode now uses an optional, sanitized LLM recall-likelihood estimate
  for low-confidence recall decisions before local retrieval.
