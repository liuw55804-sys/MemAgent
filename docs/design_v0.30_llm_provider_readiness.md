# MemAgent v0.30 LLM Provider Readiness

v0.27/v0.28/v0.29 already support `provider=openai-compatible` for routing,
memory drafting, and the combined `process` path. v0.30 adds the missing
readiness layer:

```bash
memagent llm doctor
```

The goal is simple: before a Codex thread relies on DeepSeek, Qwen, GLM, OpenAI,
or another compatible endpoint, MemAgent can tell whether the provider is
configured and, when explicitly requested, whether the API call works.

## Why

Without a doctor command, users see the provider only when something fails:

- missing env vars
- wrong base URL shape
- wrong model name
- network or gateway error
- provider returns non-OpenAI-compatible payload

That makes LLM-assisted routing feel fragile. A small readiness command gives a
clear first debug step without making ordinary memory workflows depend on an API.

## Commands

Config-only check, no network and no token spend:

```bash
memagent llm doctor
```

Live check, only when the user explicitly wants to verify the API:

```bash
memagent llm doctor --check-live
```

JSON output for Codex/MCP clients:

```bash
memagent llm doctor --json
```

Named local profile:

```bash
memagent llm doctor --profile deepseek
memagent llm doctor --profile deepseek --check-live
```

## Environment

The OpenAI-compatible provider uses:

```bash
MEMAGENT_LLM_BASE_URL
MEMAGENT_LLM_API_KEY
MEMAGENT_LLM_MODEL
```

`MEMAGENT_LLM_BASE_URL` can point to a `/v1` base URL or directly to
`/chat/completions`. MemAgent never prints the API key.

For multiple providers, use a local private profile file:

```json
{
  "profiles": {
    "aliyun": {
      "provider": "openai-compatible",
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "model": "qwen-plus",
      "api_key": "<local key>"
    },
    "deepseek": {
      "provider": "openai-compatible",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-v4-flash",
      "api_key": "<local key>"
    },
    "glm": {
      "provider": "openai-compatible",
      "base_url": "https://open.bigmodel.cn/api/paas/v4",
      "model": "glm-4.5-flash",
      "api_key": "<local key>"
    }
  }
}
```

Default path:

```text
~/.memagent/llm_providers.local.json
```

Keep the file private, for example with `chmod 600`.

## Schema

```json
{
  "schema_version": "memagent.llm_doctor.v1",
  "provider": "openai-compatible",
  "configured": true,
  "live_checked": false,
  "live_ok": null,
  "status": "configured",
  "base_url": "https://example.com/v1",
  "model": "example-model",
  "chat_completions_url": "https://example.com/v1/chat/completions",
  "missing_env": [],
  "error": null,
  "api_key_set": true,
  "profile": "deepseek",
  "config_path": "/Users/example/.memagent/llm_providers.local.json"
}
```

## Safety Boundary

- `llm doctor` does not write memory.
- Default mode does not call the provider.
- `--check-live` sends a tiny chat completion request and may incur provider
  cost.
- The API key is only read from the environment and is never printed.
- Local provider profile files should stay outside Git.

## Interview Point

> I made LLM-assisted behavior operationally debuggable. The project supports
> OpenAI-compatible providers, but instead of hiding that behind failures in the
> router, I added a provider doctor that checks env readiness, optional live API
> compatibility, and exposes the result through CLI and MCP.
