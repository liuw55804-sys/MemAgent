# Typed Memory Templates

These templates are copy-and-fill starting points for manually maintained memory cards.

They are intentionally not used by the current CLI. The v0.2 CLI still writes simple cards through `memagent remember`; these templates are for richer private memories such as bytedcli recipes, skill routes, data entrypoints, and verification flows.

## Available Templates

Coding-first templates:

```text
coding.skill_route.memory.yaml
coding.tool_recipe.memory.yaml
coding.data_entrypoint.memory.yaml
coding.pitfall.memory.yaml
coding.verification.memory.yaml
```

Generic extension templates:

```text
generic.note.memory.yaml
life.preference.memory.yaml
learning.checklist.memory.yaml
career.decision.memory.yaml
```

## How To Use

Copy a template into a local memory store:

```bash
mkdir -p ~/.memagent/memories
cp templates/coding.tool_recipe.memory.yaml ~/.memagent/memories/mem_manual_rds_recipe.memory.yaml
```

Or use the project-local demo store:

```bash
mkdir -p local_memory_demo/memories
cp templates/coding.tool_recipe.memory.yaml local_memory_demo/memories/mem_manual_rds_recipe.memory.yaml
```

Then edit the copied file. At minimum, replace:

```text
id
created_at
topic
scope.repo
triggers
applies_when
recommended_action
next_time_prompt
source_note
```

For coding memories, also replace the kind-specific fields:

```text
tool_recipes
entrypoints
pitfalls
verification
```

## Important Rules

- Do not commit filled private memory cards to Git.
- Keep real internal names only in local stores such as `~/.memagent` or `local_memory_demo`.
- Public examples should keep placeholders such as `<local-private-table-name>`.
- Keep `domain` and `kind` values within the allowed v0.2 values.
- Give each copied memory file a unique `id`.

## Recall Check

After editing a copied template, check recall:

```bash
PYTHONPATH=src python -m memagent.cli --home ./local_memory_demo recall "<related task>" --show-sources
```

The output should show the typed label:

```text
- Memory: <topic> [coding/tool_recipe]
```

