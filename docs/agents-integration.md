# AGENTS.md Integration

MemAgent can be triggered from Codex through project or global `AGENTS.md` instructions.

The MVP integration uses the Python module path directly, so the `memagent` command does not need to be installed first:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli <command>
```

## Natural Language Triggers

Generate the current recommended snippet with:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli agents-snippet
```

Copy the output into a project or global `AGENTS.md`.

When the user says:

- `记住这个`
- `沉淀一下`
- `下次别再踩这个坑`
- `把这次排查做成 memory`

Codex should summarize the lesson and call:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli remember \
  --domain coding \
  --kind <kind> \
  --topic "short topic" \
  --trigger keyword \
  "short actionable memory"
```

When the user says:

- `先看看之前有没有相关经验`
- `召回一下相关记忆`
- `用 MemAgent 查一下`
- `有没有以前踩过类似坑`

Codex should call:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli recall "short query"
```

## Safety

- Treat recalled memories as hints, not source of truth.
- Always verify with live code, schemas, docs, and command output.
- For local private memory, keep exact tool recipes when they are the reusable lesson, including needed command syntax, database names, table names, API paths, headers, and environment names.
- Never store secrets such as tokens, passwords, cookies, private keys, or raw sensitive business samples.
- Avoid storing long raw query results or large request/response bodies; summarize them and keep only reusable command shape, field path, or diagnosis.
- Create a separate generalized version when exporting or demoing memories publicly.
- Keep stable repo rules in `AGENTS.md`; keep dynamic workflow lessons in MemAgent.

## Installed Workspace

The attribution workspace currently has MemAgent trigger rules in:

```text
/Users/bytedance/Desktop/work/attribution/AGENTS.md
```

New Codex threads opened in that workspace will load those rules at session start.
