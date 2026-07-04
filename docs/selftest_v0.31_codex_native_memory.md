# MemAgent v0.31 Codex-Native Memory UX 自测

这份自测覆盖 v0.26 到 v0.31 的主线改动，但只按最新使用方式测：

> 用户自然说话，MemAgent 在后台判断是否需要召回、沉淀、反馈、handoff 或调用 LLM 辅助。

不再单独测旧的 `candidate`、`trace eval`、`trace replay`、`ingest` 全流程。那些属于开发者质量工具，日常使用不应该打扰用户。

本文分两层：

- `0-8` 是 RD smoke test：确认功能入口没有坏。
- `9-13` 是产品体验自测：用真实 Codex 对话发现触发、打扰、预览、handoff、恢复等体验问题。

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
- `writes` 包含 `recall_trace` 和 `process_trace`，后续既能记录“这次召回有没有用”，也能还原这次产品动作。

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
- `writes` 是空数组，因为这里显式用了 `--no-write` 做安全 dry run。
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
- `writes` 包含 `trace_feedback` 和 `process_trace`。
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

- 保存时 `route.action` 是 `handoff_save`，`writes` 包含 `handoff` 和 `process_trace`。
- 恢复时 `route.action` 是 `handoff_show`，`writes` 包含 `process_trace`。
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

## 9. 真实 Codex 产品自测

这一节才是本轮最重要的产品自测。目标不是证明命令能跑，而是观察：

- MemAgent 是否在该出现时出现；
- 是否在不该出现时保持安静；
- 召回内容是否真的减少试错；
- memory 预览是否短、准、可确认；
- handoff 是否能让新线程自然接上；
- 用户是否需要理解 `recall`、`trace`、`candidate`、`eval` 这些内部术语。

建议在 `/Users/bytedance/Desktop/work/attribution` 开一个真实 Codex 线程测试。不要主动说内部术语，也不要告诉 Codex“现在要测试 MemAgent”，否则会把产品体验测歪。

### 9.0 自动记录测试数据

产品自测不需要你手填记录表。每次 Codex 通过 `memagent process`、`memagent_process` 或 v0.31 wrapper 触发 MemAgent 时，MemAgent 会自动在本地写一条 process trace：

```text
<memory-home>/process_traces/process_trace_*.json
```

如果使用第 0 节的隔离 home，路径是：

```text
/Users/bytedance/Desktop/work/personal_agents/memagent/local_memory_demo/selftest_v0.31/home/process_traces/
```

真实 Codex 集成默认使用 `~/.memagent` 时，路径是：

```text
/Users/bytedance/.memagent/process_traces/
```

每条 process trace 会记录：

- 用户原话和当前 project context；
- route action、confidence、signals、reason；
- 是否执行、写了哪些本地 artifact；
- 召回 trace、memory draft、handoff、feedback 等动作的结果摘要；
- `none` 动作，也就是 MemAgent 判断“这次不该介入”的证据。

你在产品自测时只要正常对话。发现体验问题时，直接在当前会话里告诉我，例如：

```text
刚才场景 G 不对，它明明不该触发 MemAgent，但还是触发了。
```

测完后，把对应 memory home 路径发给我即可，例如：

```text
/Users/bytedance/Desktop/work/personal_agents/memagent/local_memory_demo/selftest_v0.31/home
```

我会读取 `process_traces/`、`recall_traces/`、`memories/`、handoff 文件，并结合你在对话框里的反馈，输出：

- v0.31 当前产品效果结论；
- 哪些场景已经可用，哪些只是功能可用但体验不顺；
- 失败样例归因：触发判断、召回排序、memory 质量、handoff 内容、AGENTS 提示还是 LLM provider；
- v0.32 的优先级建议。

### 9.1 场景 A：冷启动任务

用户输入：

```text
我刚接回 audit_rule_lib 这块，帮我排查 governance task owner 相关问题，先按你觉得最省时间的方式来。
```

观察点：

- Codex 是否自然想到先查相关经验，而不是直接从零开始乱翻。
- 如果召回到 memory，是否只用一两句话说明提醒点。
- Codex 是否继续读 live code、IDL、schema、命令输出，而不是把 memory 当成事实终点。
- 用户有没有被要求理解 `recall` 或 `trace`。

失败信号：

- 完全没有利用已有 memory，重复踩以前的坑。
- 一上来输出一大段 MemAgent 内部解释。
- 把旧 memory 当作当前真实 schema，不再验证 live code。

### 9.2 场景 B：任务推进中沉淀经验

当 Codex 或你发现一个可复用经验后，说：

```text
这个 bytedcli 查 live schema 的入口下次别忘了，后面排查类似 owner 问题可以先走这里。
```

观察点：

- Codex 是否先给 memory 预览，而不是直接写入长期记忆。
- 预览是否保留真正有用的操作入口，例如命令形态、库表范围、适用场景。
- 预览是否去掉 token、cookie、密码、长原始样本。
- Codex 是否问你确认保存。

失败信号：

- 过度泛化成“先查文档”，丢掉真正有价值的内部入口。
- 把整段聊天、长 SQL 结果、原始业务样本塞进 memory。
- 没确认就保存。

继续测试确认：

```text
确认保存。
```

观察点：

- Codex 是否调用 MemAgent 保存。
- 保存后的 topic/triggers 是否利于下次召回。

### 9.3 场景 C：召回反馈

在一次召回后，如果有帮助，说：

```text
刚刚那条提醒有用，少绕了一圈。
```

如果没帮助，说：

```text
刚刚那条没帮上，我真正需要的是 owner 刷新链路，不是 schema 入口。
```

观察点：

- Codex 是否能把普通中文反馈记录下来。
- Codex 是否保持简短，不生成 eval/replay 报告。
- 对负反馈，Codex 是否调整当前排查方向，而不是只是“记录一下”。

失败信号：

- 要求用户说 `trace label useful`。
- 反馈后突然进入开发者评估模式。
- 负反馈没有影响当前任务策略。

### 9.4 场景 D：中途不该保存的临时想法

用户输入：

```text
先记一下这个怀疑点，但不一定要长期保存：可能是 refresh owner 的逻辑漏了某类历史 case。
```

观察点：

- Codex 是否区分“临时上下文”和“长期 memory”。
- 如果需要保存，应更倾向 handoff 或 todo，而不是 durable memory。
- Codex 是否向用户确认边界。

失败信号：

- 把未经验证的猜测直接保存成长期经验。
- 没区分“当前排查上下文”和“跨会话复用知识”。

### 9.5 场景 E：长线程 handoff

在同一个真实 Codex 线程推进一段后，说：

```text
我准备开新线程继续，先到这，帮我把当前进度接力一下。
```

观察点：

- handoff 是否包含已完成、下一步、未验证风险。
- 是否只保存关键状态，而不是压缩整段聊天。
- 是否包含必要路径、文件、命令线索，方便新线程继续。
- 是否避免保存 token、cookie、密码、长原始样本。

失败信号：

- handoff 太空泛，新线程仍然不知道从哪里接。
- handoff 太长，像聊天记录压缩。
- 未验证猜测没有标风险。

### 9.6 场景 F：新线程恢复

另开一个 Codex 线程，仍在 `/Users/bytedance/Desktop/work/attribution`，输入：

```text
继续上个 audit_rule_lib owner 排查，先告诉我上次做到哪，然后继续推进。
```

观察点：

- Codex 是否能自然读取 handoff。
- 是否先用短摘要恢复状态，再继续真实排查。
- 是否不要求你手动贴上一轮上下文。
- 是否不会把 handoff 当成唯一事实，仍继续验证 live code。

失败信号：

- 新线程完全接不上。
- 需要你说 `handoff show`。
- 只复述 handoff，不继续推进任务。

### 9.7 场景 G：误触发和噪音控制

在真实线程里穿插一些不需要 MemAgent 的请求：

```text
解释一下这个函数现在的分支逻辑。
```

```text
帮我把这段回复写得更简洁一点。
```

```text
这个问题先别沉淀，只在当前线程里继续看。
```

观察点：

- Codex 是否能保持安静，不为了调用 MemAgent 而调用。
- 用户明确说“别沉淀”时，是否尊重。
- 没有相关 memory 时，是否简短说明或直接继续，而不是制造流程感。

失败信号：

- 每个问题都触发 MemAgent。
- 用户说别沉淀仍然生成 memory。
- “没找到记忆”占据太多对话空间。

### 9.8 场景 H：相似记忆冲突

当你已经有多条 bytedcli、RDS、owner、schema 相关 memory 后，输入：

```text
这次不是查 schema，我想排查 owner 为什么没有刷新成功，先看看有没有以前踩过类似坑。
```

观察点：

- Codex 是否能区分 schema 入口和 owner 刷新链路。
- 如果召回内容只部分相关，Codex 是否说清楚“只可作为提示”。
- 是否会继续查真实代码链路。

失败信号：

- 总是命中最常见的 RDS schema memory。
- 不说明相关性边界。
- 被错误 memory 带偏当前任务。

## 10. 反馈方式

产品自测者不需要写打分表或问题模板。问题发生时，直接在当前 Codex 会话里自然反馈即可：

```text
刚才这里误触发了。
```

```text
这条 memory 预览太泛了，没保留 bytedcli 入口。
```

```text
handoff 太空，新线程接不上。
```

```text
刚才那条召回把方向带偏了。
```

这些反馈本身会和本地 `process_traces/` 形成互补：trace 负责还原 MemAgent 当时做了什么，用户反馈负责说明产品感哪里不对。

## 11. 后续分析维度

后续由 Codex 读取 trace 后输出分析，不需要产品同学手填。分析维度包括：

| 维度 | 看什么证据 |
| --- | --- |
| 触发准确性 | `process_traces` 里的 action、confidence、signals，以及用户反馈 |
| 召回价值 | `recall_traces` 的 matches、feedback、后续任务是否少绕路 |
| 打扰成本 | action 频率、`none` 比例、MemAgent 输出长度 |
| memory 预览质量 | draft payload 的 topic、kind、triggers、memory、warnings |
| 确认安全感 | durable memory 是否只在用户确认后写入 |
| handoff 可接力性 | handoff 内容和新线程恢复效果 |
| 隐私边界 | 是否保存 secrets、长原始样本或不该持久化的临时猜测 |
| 用户心智负担 | 用户是否需要说内部术语才能触发能力 |

## 12. 当前版本通过标准

v0.31 不要求做到“完全自动、完全正确”。这一版通过标准是：

- 用户能用自然语言触发 4 条主链路：召回、沉淀预览、反馈、handoff。
- 真实 Codex 对话里，MemAgent 更像后台助手，而不是新命令行工具。
- 至少 3 个产品场景没有明显摩擦。
- 出现失败时，能被记录成明确的下一版产品问题。

## 13. 清理

如果还没有让我分析 `home/process_traces/`，先不要清理。

确认已经复盘完后，如果想清掉本轮自测产物：

```bash
rm -rf /Users/bytedance/Desktop/work/personal_agents/memagent/local_memory_demo/selftest_v0.31
```

不要清理 `~/.memagent/llm_providers.local.json`，除非你想删除本地 provider 配置。
