# Changelog

All notable MemAgent changes should be recorded here.

## Unreleased

Added:

- `remember --domain` and `remember --kind` for typed memory cards.
- `domain` and `kind` fields in newly written memory cards.
- Recall output now labels matches as `[domain/kind]`.
- Backward-compatible recall for old cards without `domain` or `kind`.
- `agents-snippet` command to generate AGENTS.md natural-language trigger rules.
- `agents-install` command to preview or write the MemAgent AGENTS.md block with managed markers.
- `recall --show-reasons` and `codex --show-reasons` to display simple recall scores and matched query terms.
- `agents-doctor` command to inspect whether the current project AGENTS.md has MemAgent recall/remember integration.
- `demo-run` command to create an isolated mock project and write a shareable AGENTS.md integration transcript.
- `mcp-stdio` command exposing MemAgent recall, remember, and AGENTS.md doctor as MCP tools over stdio.
- BM25-style recall scoring as the default strategy, with `--strategy keyword` retained as a baseline.
- `recall-eval` command to run a mock retrieval benchmark and write a Markdown report.
- `handoff save/show` commands for per-project cross-session catch-up.
- `handoff draft --from-file` to generate a reviewable handoff draft from session notes before saving.
- `handoff promote` command to preview or write handoff memory candidates as durable memory cards.
- MCP tools for saving and showing project handoffs.
- MCP tool for drafting and optionally saving handoffs from session text.
- MCP tool for promoting handoff memory candidates.
- MCP tool annotations for read-only/write-capable, destructive, idempotent, and open-world behavior hints.
- Context packing in recall output, including memory budget, dedupe count, and truncation status.
- `recall --json` structured recall output with the `memagent.recall.v1` schema.
- MCP `memagent_recall` `format=json` output for agent-consumable recall payloads.
- `recall --trace` and `trace list/show` for opt-in local recall telemetry.
- `trace label` and `trace report` for real-use recall feedback summaries.
- `trace eval` command to write a Markdown evaluation report from real labeled recall traces.
- AGENTS.md natural-language trigger rules for recall trace feedback.
- MCP trace tools for list/show/label/report/eval over saved recall traces.
- Expanded competitive scan documentation for positioning MemAgent against related coding-agent memory projects.
- v0.10 competitive-positioning design note for avoiding an agentmemory-lite roadmap.
- v0.11 handoff design note for separating recent continuation state from durable workflow memory.
- v0.12 handoff draft design note for draft-review-save capture.
- v0.13 handoff promotion design note for memory lifecycle promotion.
- v0.14 MCP annotations design note for protocol-aware tool safety hints.
- v0.15 context packing design note for budgeted prompt patches.
- v0.16 structured recall design note for stable agent-consumable output.
- v0.17 recall traces design note for real-use recall telemetry.
- v0.18 trace feedback design note for closing the recall evaluation loop.
- v0.19 trace feedback integration design note for AGENTS.md and MCP surfaces.
- v0.20 trace feedback eval design note for generating reviewable real-use eval artifacts.
- Reproducible Codex AGENTS.md integration demo using an isolated local memory home.

Changed:

- Recall now requires user-query matches before applying repo-scope bonus, reducing unrelated same-repo matches.
- Chinese query tokenization now includes lightweight 2-4 character n-grams for partial phrase matching.
- v0.3 design now focuses on Codex natural-language integration through AGENTS.md snippets.
- Generated AGENTS.md recall commands now include `--show-sources --show-reasons` for more transparent demos and debugging.
- Generated AGENTS.md snippets now include managed Markdown markers for safe replacement by `agents-install`.
- Demo documentation now points to the generated transcript flow as the fastest presentation path.
- Generated AGENTS.md recall commands now explicitly use `--strategy bm25`.
- Generated AGENTS.md snippets now include handoff/catch-up natural-language triggers.
- Generated AGENTS.md snippets now recommend draft-first handoff capture when a session note file is available.
- Generated AGENTS.md snippets now include handoff candidate promotion triggers.

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
- Vector retrieval and rerank are not implemented yet.
- Memory cards are written as YAML text but not parsed structurally during recall.
- LLM-assisted extraction, compression, conflict detection, and lifecycle evaluation are future work.
