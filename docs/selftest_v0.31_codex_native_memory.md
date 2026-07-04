# MemAgent v0.31 Codex-Native Memory UX 自测

这份自测覆盖 v0.26 到 v0.31 的主线改动，但只按最新使用方式测：

> 用户自然说话，MemAgent 在后台判断是否需要召回、沉淀、反馈、handoff 或调用 LLM 辅助。

不再单独测旧的 `candidate`、`trace eval`、`trace replay`、`ingest` 全流程。那些属于开发者质量工具，日常使用不应该打扰用户。

## 覆盖范围

| 版本 | 能力 | 本文怎么测 |
| --- | --- | --- |
| v0.26 | AGENTS.md 自然语言触发 | `agents-doctor` + 真实 Codex 对话 |
| v0.27 | LLM-assisted route | 用 `--provider openai-compatible --llm-profile ...` 识别自然语言意图 |
| v0.28 | memory draft | 用户说“下次别忘了”时只产出预览，不自动写长期 memory |
| v0.29 | `process` 一站式入口 | 召回、draft、feedback、handoff 都走 `process` |
| v0.30 | LLM provider doctor/profile | 用本地 profile 检查 aliyun/deepseek/glm |
| v0.31 | Codex wrapper process-first | `memagent codex --dry-run` 不再硬编码 recall-first |

## 0. 准备隔离自测目录

在 MemAgent 仓库里执行：

```bash
cd /Users/bytedance/Desktop/work/personal_agents/memagent

export MEMAGENT_ROOT="$PWD"
export SELFTEST_DIR="$PWD/local_memory_demo/selftest_v0.31"
export SELFTEST_HOME="$SELFTEST_DIR/home"
export SELFTEST_PROJECT="$SELFTEST_DIR/project"

rm -rf "$SELFTEST_DIR"
mkdir -p "$SELFTEST_HOME" "$SELFTEST_PROJECT"
```

预期：

- 所有自测产物都在 `local_memory_demo/selftest_v0.31/`。
- 不污染真实 `~/.memagent` memory。
- 不会提交 Git。

## 1. 快速健康检查

只跑和最新主线有关的测试，不跑全量：

```bash
PYTHONPATH=src python -m unittest \
  tests.test_interaction \
  tests.test_router \
  tests.test_draft \
  tests.test_llm \
  tests.test_wrapper
```

检查当前业务 workspace 的 AGENTS 集成：

```bash
PYTHONPATH=src python -m memagent.cli agents-doctor \
  --cwd /Users/bytedance/Desktop/work/attribution \
  --memagent-root "$MEMAGENT_ROOT"
```

通过标准：

- focused tests 全部 OK。
- `agents-doctor` 显示 `Status: ready`。

## 2. 检查 LLM Profile

快速测一个 provider 即可：

```bash
PYTHONPATH=src python -m memagent.cli llm doctor \
  --profile deepseek \
  --check-live \
  --json
```

如果想顺手确认三家都可用：

```bash
for p in aliyun deepseek glm; do
  PYTHONPATH=src python -m memagent.cli llm doctor \
    --profile "$p" \
    --check-live \
    --json
done
```

通过标准：

- `status` 是 `live_ok`。
- 输出里不出现真实 API key。
- 如果某一家失败，不影响离线 heuristic 流程；只说明该 profile 当前不可用。

## 3. 准备一条可召回的测试 Memory

写入隔离 home：

```bash
PYTHONPATH=src python -m memagent.cli --home "$SELFTEST_HOME" remember \
  --topic "audit_rule_lib live schema first" \
  --trigger audit_rule_lib \
  --trigger owner \
  --trigger bytedcli \
  "排查 audit_rule_lib owner 或 governance task 相关问题前，先用 bytedcli 查 live RDS schema，再看 DAL、模型和调用链，避免依赖旧文档。"
```

通过标准：

- 输出 saved memory 路径在 `local_memory_demo/selftest_v0.31/home/memories/`。

## 4. 自然任务开始：自动召回

模拟用户正常发起任务，不说 `recall`：

```bash
PYTHONPATH=src python -m memagent.cli --home "$SELFTEST_HOME" process \
  --cwd "$SELFTEST_PROJECT" \
  --json \
  "帮我排查 audit_rule_lib owner 问题，先按你觉得最省时间的方式来。"
```

通过标准：

- `route.action` 是 `recall`。
- `executed` 是 `true`。
- `result_text` 里能看到刚才的 live schema 提醒。
- `writes` 包含 `recall_trace`，后续才能记录“这次召回有没有用”。

## 5. 对话中沉淀经验：只预览，不自动保存

模拟用户自然说“下次别忘了”：

```bash
PYTHONPATH=src python -m memagent.cli --home "$SELFTEST_HOME" process \
  --cwd "$SELFTEST_PROJECT" \
  --recent-text "bytedcli rds db table schema demo_db demo_table --region cn" \
  --provider openai-compatible \
  --llm-profile deepseek \
  --no-write \
  --json \
  "这个入口下次别忘了。"
```

如果不想消耗 LLM，也可以去掉 provider 参数，走 heuristic：

```bash
PYTHONPATH=src python -m memagent.cli --home "$SELFTEST_HOME" process \
  --cwd "$SELFTEST_PROJECT" \
  --recent-text "bytedcli rds db table schema demo_db demo_table --region cn" \
  --no-write \
  --json \
  "这个入口下次别忘了。"
```

通过标准：

- `route.action` 是 `draft_memory`。
- `artifacts.requires_confirmation` 是 `true`。
- `writes` 是空数组。
- 这一步只生成可审核 memory draft，不写长期 memory。

真实 Codex 使用时，正确体验是：

1. Codex 先给你预览短 memory。
2. 你说“确认保存”。
3. Codex 再调用 `memagent remember`。

## 6. 普通反馈：记录召回是否有用

基于 Step 4 留下的 recall trace，直接说普通反馈：

```bash
PYTHONPATH=src python -m memagent.cli --home "$SELFTEST_HOME" process \
  --cwd "$SELFTEST_PROJECT" \
  --json \
  "刚刚那条提醒有用。"
```

通过标准：

- `route.action` 是 `label_feedback`。
- `writes` 包含 `trace_feedback`。
- `artifacts.rating` 是 `useful`。

这一步验证的是产品体验：用户不需要说 `trace label`。

## 7. 长线程交接：保存和恢复 Handoff

保存当前进度：

```bash
PYTHONPATH=src python -m memagent.cli --home "$SELFTEST_HOME" process \
  --cwd "$SELFTEST_PROJECT" \
  --recent-text "## Summary
MemAgent v0.31 正在验证 Codex-native memory UX。

## Done
- 已验证 task start recall。
- 已验证 memory draft preview。

## Next Steps
- 验证 wrapper dry-run。
- 在真实 Codex 线程里走一遍自然语言触发。" \
  --json \
  "先到这，下次继续时接上。"
```

恢复最近进度：

```bash
PYTHONPATH=src python -m memagent.cli --home "$SELFTEST_HOME" process \
  --cwd "$SELFTEST_PROJECT" \
  --json \
  "继续上次做到哪了？"
```

通过标准：

- 保存时 `route.action` 是 `handoff_save`，`writes` 包含 `handoff`。
- 恢复时 `route.action` 是 `handoff_show`。
- 恢复输出包含 Summary / Done / Next Steps。

## 8. Codex Wrapper：process-first Dry Run

`memagent codex` 会读取当前 shell 的工作目录，所以先进入模拟 project：

```bash
cd "$SELFTEST_PROJECT"

PYTHONPATH="$MEMAGENT_ROOT/src" python -m memagent.cli --home "$SELFTEST_HOME" codex \
  --dry-run \
  --no-write \
  "帮我排查 audit_rule_lib owner 问题。"
```

通过标准：

- 输出最终会传给 Codex 的 prompt。
- prompt 前部包含 `[MemAgent recalled context]`。
- 用户 prompt 被保留在 `[User task]` 后。
- 这说明 wrapper 已经走 v0.31 的 `process` preflight，而不是旧的硬编码 recall-first。

跑完后回到仓库根目录：

```bash
cd "$MEMAGENT_ROOT"
```

## 9. 真实 Codex 对话自测

在 `/Users/bytedance/Desktop/work/attribution` 开一个 Codex 线程，不要说内部术语。

依次尝试这些自然语言：

```text
帮我排查 audit_rule_lib owner 问题，先按你觉得最省时间的方式来。
```

```text
这个 bytedcli 查 live schema 的入口下次别忘了。
```

```text
刚刚那条提醒有用。
```

```text
先到这，下次继续时帮我接上。
```

```text
继续上次做到哪了？
```

通过标准：

- Codex 可以在合适时机调用 MemAgent，但不要要求你说 `recall`、`trace`、`candidate`。
- 沉淀 memory 前要先给你预览。
- 反馈和 handoff 可以用普通中文触发。
- MemAgent 只提供短上下文，Codex 仍然要读 live code、IDL、schema、命令输出。

## 10. 验收表

| 场景 | 通过标准 | 你的结论 |
| --- | --- | --- |
| AGENTS 集成 | `agents-doctor` ready | 待填 |
| LLM profile | 至少一个 profile `live_ok` | 待填 |
| 任务开始召回 | 自然任务触发 `recall` | 待填 |
| 经验沉淀 | 只预览 memory draft，不自动写 | 待填 |
| 反馈闭环 | “有用/没用”触发 feedback | 待填 |
| 长线程 handoff | “先到这/继续上次”能保存和恢复 | 待填 |
| Codex wrapper | dry-run prompt 包含 MemAgent preflight context | 待填 |
| 产品体感 | 用户不需要理解 trace/eval/replay/candidate | 待填 |

## 11. 清理

如果想清掉本轮自测产物：

```bash
rm -rf /Users/bytedance/Desktop/work/personal_agents/memagent/local_memory_demo/selftest_v0.31
```

不要清理 `~/.memagent/llm_providers.local.json`，除非你想删除本地 provider 配置。
