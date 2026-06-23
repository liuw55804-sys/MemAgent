# MemAgent

MemAgent is a local workflow memory layer for Codex and other coding agents.

It stores small, explicit memory cards from past coding-agent sessions so a new
session can quickly recall proven commands, failed paths, and next-step hints.

## MVP Commands

```bash
python -m memagent.cli remember --domain coding --kind pitfall "RDS big-table JSON aggregation timed out; use id ranges first."
python -m memagent.cli recall "continue checking attribution accuracy"
python -m memagent.cli codex --dry-run "continue checking attribution accuracy"
```

After installing the project in editable mode, the shorter form is available:

```bash
python -m pip install -e .
memagent remember --domain coding --kind pitfall "RDS big-table JSON aggregation timed out; use id ranges first."
memagent recall "continue checking attribution accuracy"
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

## Typed Memory Templates

See [templates/README.md](templates/README.md) for copy-and-fill YAML templates
for `skill_route`, `tool_recipe`, `data_entrypoint`, `pitfall`, `verification`,
and a few generic non-coding memory types.

## Codex Natural Language Triggers

See [docs/agents-integration.md](docs/agents-integration.md) for the `AGENTS.md`
integration that lets Codex call MemAgent when the user says phrases like
`沉淀一下` or `召回一下相关记忆`.

## Development

```bash
PYTHONPATH=src python -m compileall src tests
PYTHONPATH=src python -m unittest discover -s tests
```
