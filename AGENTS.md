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

## Chinese Feishu Documentation

After a user-visible MemAgent iteration, update the two Chinese source documents
under `docs/feishu/`: `技术实现说明.md` and `用户使用说明.md`. Then sync the
corresponding existing Feishu documents through `bytedcli feishu docs update-doc`.

- The local registry at `~/.memagent/feishu_docs.json` contains the private
  document IDs/URLs and whiteboard tokens. Do not commit it.
- Render changed Mermaid source under `docs/feishu/` locally and place the
  verified PNG at its corresponding section in the Feishu document. Use native
  whiteboards only when the full diagram, including connectors, can be written
  and verified; never leave a partial or blank whiteboard as the primary chart.
- The Feishu documents are the Chinese product-facing reading surface; the
  repository Markdown remains the source of truth. Do not store business data,
  credentials, or private URLs in either source document.
