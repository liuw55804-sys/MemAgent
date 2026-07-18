# Changelog

All notable public changes are recorded here.

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
