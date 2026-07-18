# MemAgent

MemAgent is a local-first workflow memory layer for Codex and other coding
agents. It keeps small, explicit lessons on your machine so a new task can
recall a proven workflow, a pitfall, or a useful handoff without uploading your
history to a service.

**No model, API key, or account is required.** The default route is local
heuristics and all state lives under `~/.memagent/`.

## Quick Start (5 minutes)

Install with pipx:

```bash
pipx install memagent
```

Install the zero-intrusion Codex skill. It writes only to your user-level Codex
directory, never to the current repository:

```bash
memagent install-user-codex --write
memagent user-codex-doctor
```

Start a new Codex task and use normal language such as “remember this
workaround” or “what did we learn last time?” The Skill invokes MemAgent from
the project directory, so memories are scoped to the current project.

You can also use the CLI directly:

```bash
memagent remember --kind pitfall --topic "test isolation" \
  "Run the focused test before the full suite to isolate failures."
memagent recall "how should I validate this change?"
memagent handoff save --topic "parser cleanup" --done "Added tests" \
  --next-step "Run the package smoke test" "Parser cleanup is ready for verification."
```

## How It Works

```text
natural-language task
        |
        v
local router -> recall candidates | draft preview | feedback | handoff | none
        |
        v
BM25 candidates -> local relevance -> one memory or abstain
        |
        v
~/.memagent/ (memory cards, pending drafts, local traces)
```

- **Recall** uses BM25 to generate local candidates, then applies a precision
  relevance policy. It returns at most one project-scoped hint and otherwise
  abstains. Verify any hint against live sources before acting.
- **Drafts** are previewed first. Durable memory requires explicit confirmation.
- **Proactive capture** lets the Codex Skill suggest one preview after a
  meaningful detour, correction, verified entrypoint, or reusable workflow.
  Routine work is skipped, duplicates are suppressed, and nothing is saved
  durably without confirmation.
- **Feedback** from ordinary language helps evaluate whether a recalled hint was
  useful.
- **Handoffs** keep recent project state separate from durable lessons.

## Optional LLM Semantics

Local heuristics remain the default. To configure optional OpenAI-compatible
semantic routing, run:

```bash
memagent configure
memagent llm doctor
```

For a non-interactive setup, keep the key in your shell and store only its
environment-variable name in MemAgent's local configuration:

```bash
export MEMAGENT_LLM_API_KEY="..."
memagent configure --mode hybrid --profile default \
  --base-url https://api.example.com/v1 --model example-model
```

Choose one of three modes:

- `heuristic`: fully local, default.
- `llm`: use the optional provider for semantic routing and draft quality;
  ambiguous recall candidates may also use the relevance gate. Failures fall
  back to local behavior.
- `hybrid`: keep confident routing and relevance decisions local. Use a short
  recall-likelihood estimate for uncertain recall intent and an LLM relevance
  gate only when BM25 candidates remain ambiguous.

`configure` stores an endpoint, model, and API-key **environment variable
name** in `~/.memagent/config.json`; it never writes the API key itself. A
local OpenAI-compatible server can be configured with `--no-api-key`.

Only short, sanitized task summaries, draft candidates, and up to three
sanitized candidate-memory summaries are eligible for an LLM request. MemAgent
never intentionally sends full conversations, the full memory library,
passwords, cookies, private keys, or raw request/response bodies.

## Commands

```bash
memagent process "remember this workaround and show me a preview"
memagent suggest "Verify the live schema before editing generated queries." --evidence correction
memagent activity --today
memagent llm doctor --check-live
memagent uninstall-user-codex --write
```

Run `memagent --help` for the complete command reference.

## Privacy and Scope

- Local state defaults to `~/.memagent/`; set `MEMAGENT_HOME` to use another
  directory.
- The user-level Codex Skill is installed under `~/.codex/skills/memagent/`.
- MemAgent does not modify project code, project `AGENTS.md`, documentation, or
  Git state as part of normal use.
- Do not save secrets or raw sensitive samples in memory. Generalize examples
  before sharing them.

## Uninstall

```bash
memagent uninstall-user-codex --write
pipx uninstall memagent
```

This leaves `~/.memagent/` intact so you can decide whether to retain or remove
your local memories.

## FAQ

**Does it require an LLM?** No. The default behavior is fully local.

**Does it write memory automatically?** No. Long-term memory always requires a
preview and explicit confirmation.

**Will it recall something on every task?** No. Generic terms, business IDs,
and same-project overlap are insufficient. Precision-first recall returns one
memory or abstains.

**Does it change my repository?** No. The default integration is user-level
and does not touch the repository.

**Can I use a local model server?** Yes. Run `memagent configure --mode hybrid
--base-url http://localhost:1234/v1 --model <model> --no-api-key`.

## Development

```bash
python -m unittest discover -s tests
python -m compileall src tests
python -m build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

Licensed under the [Apache License 2.0](LICENSE).
