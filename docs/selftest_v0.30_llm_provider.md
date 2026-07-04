# Self-Test v0.30: LLM Provider Readiness

目标：确认 MemAgent 的 OpenAI-compatible provider 可以被诊断，并且不会在普通检查时偷偷发 API 请求。

## Step 1: Config-Only Doctor

不配置任何 key 也可以跑：

```bash
PYTHONPATH=src python -m memagent.cli llm doctor
```

预期：

- 输出 `status: not_configured` 或 `status: configured`。
- 不打印 API key。
- 不发网络请求。

JSON 版本：

```bash
PYTHONPATH=src python -m memagent.cli llm doctor --json
```

## Step 2: Configure A Provider

示例，只展示变量形态，按你自己的 DeepSeek/Qwen/GLM/OpenAI-compatible endpoint 替换：

```bash
export MEMAGENT_LLM_BASE_URL="https://your-openai-compatible-endpoint/v1"
export MEMAGENT_LLM_API_KEY="your-api-key"
export MEMAGENT_LLM_MODEL="your-model-name"
```

然后再跑：

```bash
PYTHONPATH=src python -m memagent.cli llm doctor --json
```

预期：

- `configured: true`
- `status: configured`
- `chat_completions_url` 指向 `/chat/completions`
- 输出中不包含真实 API key

## Step 3: Optional Live Check

只有当你明确想验证 API 能不能打通时再跑：

```bash
PYTHONPATH=src python -m memagent.cli llm doctor --check-live
```

预期：

- 成功时 `status: live_ok`
- 失败时 `status: live_failed`，并展示可读错误

## Step 4: Optional Local Profiles

如果你有多个 provider，可以写本地私有 profile：

```text
~/.memagent/llm_providers.local.json
```

示例结构：

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

然后逐个检查：

```bash
PYTHONPATH=src python -m memagent.cli llm doctor --profile aliyun --check-live
PYTHONPATH=src python -m memagent.cli llm doctor --profile deepseek --check-live
PYTHONPATH=src python -m memagent.cli llm doctor --profile glm --check-live
```

## Step 5: Try LLM-Assisted Process

live check 成功后，再用同一个 provider 走自然交互入口：

```bash
PYTHONPATH=src python -m memagent.cli process \
  "这个入口下次别忘了" \
  --recent-text "bytedcli rds db table schema demo_db demo_table --region cn" \
  --provider openai-compatible \
  --llm-profile aliyun \
  --json
```

预期：

- `schema_version: memagent.process.v1`
- `route.provider: openai-compatible`
- 生成 memory draft preview
- `writes: []`，不会自动写长期 memory

## Product Check

这一版自测通过后，可以说明：

- LLM-assisted 不再只是代码里一个 provider 参数，而是有可诊断入口。
- 用户可以先确认 DeepSeek/Qwen/GLM/OpenAI-compatible 配置，再让 Codex 使用 `provider=openai-compatible`。
- 普通 MemAgent 工作流仍然可以完全离线跑 heuristic。
