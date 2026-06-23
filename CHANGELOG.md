# Changelog

All notable MemAgent changes should be recorded here.

## v0.1.0-mvp - 2026-06-23

MVP baseline for local Codex workflow memory.

Added:

- Local CLI commands: `remember`, `recall`, and `codex`.
- YAML memory cards stored under `~/.memagent/memories`.
- Project context detection for cwd, git root, branch, recent files, and AGENTS files.
- Keyword-based recall and short context composition.
- Codex wrapper that prepends recalled context to the user prompt.
- Product plan, AGENTS integration notes, and technical walkthrough docs.
- Unit tests for memory storage, prompt wrapping, and CLI remainder handling.

Known limitations:

- `ingest` is not implemented yet.
- Recall uses simple keyword scoring, not BM25/vector retrieval.
- Memory cards are written as YAML text but not parsed structurally during recall.
- LLM-assisted extraction, compression, conflict detection, and lifecycle evaluation are future work.

