# MemAgent

MemAgent is a local workflow memory layer for Codex and other coding agents.

It stores small, explicit memory cards from past coding-agent sessions so a new
session can quickly recall proven commands, failed paths, and next-step hints.

## MVP Commands

```bash
python -m memagent.cli remember --domain coding --kind pitfall "RDS big-table JSON aggregation timed out; use id ranges first."
python -m memagent.cli recall "continue checking attribution accuracy" --show-sources --show-reasons --strategy bm25
python -m memagent.cli agents-install
python -m memagent.cli agents-doctor
python -m memagent.cli demo-run --reset
python -m memagent.cli mcp-stdio
python -m memagent.cli recall-eval
python -m memagent.cli codex --dry-run "continue checking attribution accuracy"
```

After installing the project in editable mode, the shorter form is available:

```bash
python -m pip install -e .
memagent remember --domain coding --kind pitfall "RDS big-table JSON aggregation timed out; use id ranges first."
memagent recall "continue checking attribution accuracy" --show-sources --show-reasons --strategy bm25
memagent agents-install
memagent agents-doctor
memagent demo-run --reset
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

See [docs/self-test-plan.md](docs/self-test-plan.md) before adding AI/provider
integrations. It helps decide whether the next step should be ingest, recall,
prompt composition, or natural-language triggering.

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

## Codex Natural Language Triggers

See [docs/agents-integration.md](docs/agents-integration.md) for the `AGENTS.md`
integration that lets Codex call MemAgent when the user says phrases like
`沉淀一下` or `召回一下相关记忆`.

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

## Development

```bash
PYTHONPATH=src python -m compileall src tests
PYTHONPATH=src python -m unittest discover -s tests
```
