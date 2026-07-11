# Changelog

All notable public changes are recorded here.

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
