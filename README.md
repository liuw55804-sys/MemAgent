# MemAgent

MemAgent is a local workflow memory layer for Codex and other coding agents.

It stores small, explicit memory cards from past coding-agent sessions so a new
session can quickly recall proven commands, failed paths, and next-step hints.

## MVP Commands

```bash
python -m memagent.cli remember --domain coding --kind pitfall "RDS big-table JSON aggregation timed out; use id ranges first."
python -m memagent.cli recall "continue checking attribution accuracy" --show-sources --show-reasons --strategy bm25
python -m memagent.cli recall "continue checking attribution accuracy" --json
python -m memagent.cli recall "continue checking attribution accuracy" --trace
python -m memagent.cli trace list
python -m memagent.cli trace label --rating useful
python -m memagent.cli trace report
python -m memagent.cli trace eval
python -m memagent.cli trace replay
python -m memagent.cli agents-install
python -m memagent.cli agents-doctor
python -m memagent.cli ingest codex --limit 5 --project-only
python -m memagent.cli handoff show
python -m memagent.cli handoff draft --from-file ./session_notes.md
python -m memagent.cli handoff promote --index 1
python -m memagent.cli demo-run --reset
python -m memagent.cli demo-bundle --reset
python -m memagent.cli mcp-demo --reset
python -m memagent.cli mcp-stdio
python -m memagent.cli recall-eval
python -m memagent.cli codex --dry-run "continue checking attribution accuracy"
```

After installing the project in editable mode, the shorter form is available:

```bash
python -m pip install -e .
memagent remember --domain coding --kind pitfall "RDS big-table JSON aggregation timed out; use id ranges first."
memagent recall "continue checking attribution accuracy" --show-sources --show-reasons --strategy bm25
memagent recall "continue checking attribution accuracy" --json
memagent recall "continue checking attribution accuracy" --trace
memagent trace list
memagent trace label --rating useful
memagent trace report
memagent trace eval
memagent trace replay
memagent agents-install
memagent agents-doctor
memagent ingest codex --limit 5 --project-only
memagent handoff show
memagent handoff draft --from-file ./session_notes.md
memagent handoff promote --index 1
memagent demo-run --reset
memagent demo-bundle --reset
memagent mcp-demo --reset
memagent mcp-stdio
memagent recall-eval
memagent codex "continue checking attribution accuracy"
```

By default, memories are stored under:

```text
~/.memagent/memories/
```

Set `MEMAGENT_HOME` to use a different local store.

`remember` defaults to `--domain coding --kind note`. Use explicit types when a
memory has a clear shape, for example `tool_recipe`, `skill_route`, `pitfall`,
`verification`, `preference`, or `checklist`.

## Codex Wrapper

`memagent codex` recalls relevant memory cards, prepends a short context block,
and starts Codex with the augmented prompt.

Preview the prompt without launching Codex:

```bash
memagent codex --dry-run "continue checking attribution accuracy"
```

Pass extra Codex options after `--`:

```bash
memagent codex "continue checking attribution accuracy" -- --model gpt-5.4
```

Skip memory recall for one run:

```bash
memagent codex --no-memory "continue checking attribution accuracy"
```

## Product Plan

See [docs/product-plan.md](docs/product-plan.md).

## Competitive Scan

See [docs/competitive-scan.md](docs/competitive-scan.md) for similar projects and
MemAgent's current differentiation.

## Code Walkthrough

See [docs/technical-walkthrough.md](docs/technical-walkthrough.md) for a
module-by-module explanation of the current MVP code.

## Development Workflow

See [docs/development-workflow.md](docs/development-workflow.md) for the local
Git/versioning rhythm. Current baseline: `v0.1.0-mvp`.

## Self-Test Plan

For the current Codex-thread product self-test, use
[docs/selftest_v0.25_codex_thread.md](docs/selftest_v0.25_codex_thread.md).
The older [docs/self-test-plan.md](docs/self-test-plan.md) remains as the v0.1
manual `remember/recall` baseline.

## v2 Plan

See [docs/plan_v2.md](docs/plan_v2.md) for the stable v2 direction: coding-first
MemAgent with a generic memory substrate underneath.

## v0.2 Design

See [docs/design_v0.2_typed_memory.md](docs/design_v0.2_typed_memory.md) for the
implementation design for `domain` and `kind` typed memories.

## v0.3 Design

See [docs/design_v0.3_codex_integration.md](docs/design_v0.3_codex_integration.md)
for the Codex natural-language integration design.

Generate a copyable `AGENTS.md` snippet:

```bash
memagent agents-snippet
```

Preview installing the snippet into the current project's `AGENTS.md`:

```bash
memagent agents-install
```

Apply the planned change explicitly:

```bash
memagent agents-install --write
```

Check whether the current project has usable MemAgent AGENTS.md integration:

```bash
memagent agents-doctor
```

## v0.4 Design

See [docs/design_v0.4_agents_doctor.md](docs/design_v0.4_agents_doctor.md) for
the AGENTS.md integration self-check design.

## v0.5 Design

See [docs/design_v0.5_agents_install.md](docs/design_v0.5_agents_install.md) for
the safe AGENTS.md installer design.

## v0.6 Design

See [docs/design_v0.6_demo_run.md](docs/design_v0.6_demo_run.md) for the
reproducible demo transcript design.

## v0.7 Design

See [docs/design_v0.7_mcp_stdio.md](docs/design_v0.7_mcp_stdio.md) for the
minimal MCP stdio adapter design.

## v0.8 Design

See [docs/design_v0.8_rag_recall.md](docs/design_v0.8_rag_recall.md) for the
BM25-style RAG recall design.

## v0.9 Design

See [docs/design_v0.9_recall_eval.md](docs/design_v0.9_recall_eval.md) for the
mock recall evaluation design.

Generate a mock recall evaluation report:

```bash
memagent recall-eval
```

The report is written to:

```text
local_memory_demo/recall_eval/report.md
```

## v0.10 Design

See [docs/design_v0.10_competitive_positioning.md](docs/design_v0.10_competitive_positioning.md)
for the competitive-scan driven positioning update.

## v0.11 Design

See [docs/design_v0.11_handoff.md](docs/design_v0.11_handoff.md) for the
cross-session handoff and catch-up design.

Save a handoff for the current project:

```bash
memagent handoff save --topic "demo handoff" --done "wired AGENTS.md" --next-step "run demo" "short summary"
```

Show the latest handoff:

```bash
memagent handoff show
```

## v0.12 Design

See [docs/design_v0.12_handoff_draft.md](docs/design_v0.12_handoff_draft.md)
for the reviewable handoff draft design.

Draft a handoff from session notes:

```bash
memagent handoff draft --from-file ./session_notes.md
```

Save the accepted draft:

```bash
memagent handoff draft --from-file ./session_notes.md --save
```

## v0.13 Design

See [docs/design_v0.13_handoff_promotion.md](docs/design_v0.13_handoff_promotion.md)
for the handoff candidate promotion design.

Preview promoting the first handoff memory candidate:

```bash
memagent handoff promote --index 1
```

Save the selected candidate as a durable memory card:

```bash
memagent handoff promote --index 1 --write
```

## v0.14 Design

See [docs/design_v0.14_mcp_annotations.md](docs/design_v0.14_mcp_annotations.md)
for the MCP tool annotation design. Every MCP tool now declares whether it is
read-only, write-capable, destructive, idempotent, and closed-world.

## v0.15 Design

See [docs/design_v0.15_context_packing.md](docs/design_v0.15_context_packing.md)
for the context-packing design. Recall output now includes a small pack summary
showing memory budget, dedupe count, and truncation status.

## v0.16 Design

See [docs/design_v0.16_structured_recall.md](docs/design_v0.16_structured_recall.md)
for the structured recall contract. `memagent recall --json` emits a versioned
payload for other agents, MCP clients, evaluations, or future UI surfaces.

## v0.17 Design

See [docs/design_v0.17_recall_traces.md](docs/design_v0.17_recall_traces.md)
for the opt-in recall trace design. `memagent recall --trace` saves a local
`memagent.recall.v1` payload for later review or evaluation.

## v0.18 Design

See [docs/design_v0.18_trace_feedback.md](docs/design_v0.18_trace_feedback.md)
for trace feedback. `memagent trace label` and `memagent trace report` turn
saved recall traces into a small real-use evaluation loop.

## v0.19 Design

See [docs/design_v0.19_trace_feedback_integration.md](docs/design_v0.19_trace_feedback_integration.md)
for AGENTS.md and MCP integration of trace feedback.

## v0.20 Design

See [docs/design_v0.20_trace_eval.md](docs/design_v0.20_trace_eval.md) for the
trace feedback evaluation report design. `memagent trace eval` writes a Markdown
report from real labeled recall traces, complementing the mock `recall-eval`
benchmark.

## v0.21 Design

See [docs/design_v0.21_demo_bundle.md](docs/design_v0.21_demo_bundle.md) for the
interview demo bundle design. `memagent demo-bundle --reset` generates one
shareable Markdown entrypoint that links the AGENTS.md flow transcript, mock RAG
benchmark, real trace-feedback report, and MCP tool surface.

## v0.22 Design

See [docs/design_v0.22_mcp_demo.md](docs/design_v0.22_mcp_demo.md) for the MCP
JSON-RPC transcript design. `memagent mcp-demo --reset` generates a concrete
protocol transcript covering initialize, tools/list, and tools/call flows.

## v0.23 Design

See [docs/design_v0.23_trace_replay.md](docs/design_v0.23_trace_replay.md) for
trace replay evaluation. `memagent trace replay` reruns saved trace queries
against current retrievers and writes a top-stability report.

## v0.24 Design

See [docs/design_v0.24_landscape_refresh.md](docs/design_v0.24_landscape_refresh.md)
for the refreshed GitHub landscape scan and the positioning update that led to
Codex transcript ingest.

## v0.25 Design

See [docs/design_v0.25_codex_ingest.md](docs/design_v0.25_codex_ingest.md) for
Codex transcript ingest. `memagent ingest codex` scans local Codex session JSONL
files and writes review-only memory candidate drafts. It does not write durable
memory cards until the user edits and saves a candidate with `remember`.

## Codex Natural Language Triggers

See [docs/agents-integration.md](docs/agents-integration.md) for the `AGENTS.md`
integration that lets Codex call MemAgent when the user says phrases like
`沉淀一下`, `召回一下相关记忆`, or `上次做到哪`.

## Demo

See [docs/demo_codex_agents_flow.md](docs/demo_codex_agents_flow.md) for a
reproducible local demo of the AGENTS.md recall/remember flow.

Generate a fresh mock transcript:

```bash
memagent demo-run --reset
```

The transcript is written to:

```text
local_memory_demo/demo_run/transcript.md
```

Generate a complete interview demo bundle:

```bash
memagent demo-bundle --reset
```

The entry report is written to:

```text
local_memory_demo/demo_bundle/interview_demo.md
```

Generate a standalone MCP JSON-RPC transcript:

```bash
memagent mcp-demo --reset
```

The transcript is written to:

```text
local_memory_demo/mcp_demo/mcp_transcript.md
```

## Development

```bash
PYTHONPATH=src python -m compileall src tests
PYTHONPATH=src python -m unittest discover -s tests
```
