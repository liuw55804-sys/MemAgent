# MemAgent Development Notes

## Scope

This repository contains MemAgent, a local workflow memory layer for Codex and other coding agents.

## Working Rules

- Keep the core CLI usable without external services.
- Do not store real company data, tokens, task IDs, case IDs, table names, or private URLs in examples.
- Prefer local-first storage under `~/.memagent`.
- Treat OpenAI/DeepSeek/Qwen/GLM calls as optional provider adapters, not required for the core MVP.
- Keep examples generic and export-safe.

## Verification

- Run `PYTHONPATH=src python -m unittest discover -s tests` after changing Python logic.
- Run `python -m compileall src tests` for syntax checks.
