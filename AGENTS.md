# MemAgent Development Notes

- Keep default behavior local-first and usable without accounts, API keys, or
  network services.
- Never add proprietary examples, private transcripts, secrets, absolute user
  paths, or organization-specific workflows to public code or documentation.
- Optional LLM features must use the smallest sanitized payload possible and
  must fall back to local behavior when configuration or connectivity fails.
- The normal integration is the user-level Codex Skill. Do not modify a target
  repository as part of ordinary MemAgent use.
- Run `python -m unittest discover -s tests` and `python -m compileall src tests`
  after Python changes. Run an isolated install smoke test before release.
