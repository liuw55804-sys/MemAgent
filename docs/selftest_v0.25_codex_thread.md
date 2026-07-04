# MemAgent v0.25 Codex Thread 自测 Playbook

这份文档面向产品自测，不是开发者测试。目标是回答：

> MemAgent 现在是否已经能在真实 Codex 线程里减少重复摸索，并形成可讲的 agent memory 闭环？

建议先跑这一版自测，再决定 v0.26 做 LLM 抽取、MCP ingest tool、候选接受/拒绝记录，还是做 UI。

## 1. 这轮测什么

这轮只测五条主线：

| 主线 | 用户体感问题 | MemAgent 能力 |
|---|---|---|
| AGENTS.md 触发 | 我能不能用自然语言叫它？ | `agents-doctor` + AGENTS.md trigger |
| 旧线程候选抽取 | 以前 Codex 线程里有没有可沉淀经验？ | `ingest codex` |
| 长期记忆召回 | 新线程能不能少解释一遍？ | `remember` + `recall --trace` |
| 反馈闭环 | 召回有没有真的帮到我？ | `trace label/report/eval/replay` |
| 面试演示 | 能不能讲清楚 RAG/MCP/agent memory？ | `demo-bundle` + `mcp-demo` |

不要在这一轮重点测“AI 自动总结得聪不聪明”。v0.25 的 ingest 还是规则版候选生成，设计上就是让用户先审阅。

## 2. 自测前置检查

在 MemAgent 仓库里确认代码和 demo 能跑：

```bash
cd /Users/bytedance/Desktop/work/personal_agents/memagent
PYTHONPATH=src python -m unittest discover -s tests
PYTHONPATH=src python -m memagent.cli demo-bundle --reset
```

预期：

- 单测通过。
- `demo-bundle` 输出 `ingest candidates`、`trace eval`、`trace replay`、`mcp transcript`。
- 可打开 `local_memory_demo/demo_bundle/interview_demo.md`。

确认目标 Codex 工作区已接入：

```bash
PYTHONPATH=src python -m memagent.cli agents-doctor --cwd /Users/bytedance/Desktop/work/attribution
```

预期看到：

```text
Status: ready
```

## 3. 建议开一个新 Codex 线程

工作目录使用：

```text
/Users/bytedance/Desktop/work/attribution
```

这个目录的 `AGENTS.md` 已经包含 MemAgent 自然语言触发规则。自测时尽量不要直接敲命令，先用自然语言问 Codex，看它会不会按 AGENTS.md 调用 MemAgent。

## 4. 自测脚本

### Step 1：测试旧线程候选抽取

对 Codex 说：

```text
从旧 Codex 线程里找可沉淀经验，先不要保存为长期 memory。
输出到 /Users/bytedance/Desktop/work/personal_agents/memagent/local_memory_demo/selftest_ingest
```

期望 Codex 做的事：

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli ingest codex \
  --limit 5 \
  --project-only \
  --workspace /Users/bytedance/Desktop/work/personal_agents/memagent/local_memory_demo/selftest_ingest
```

通过标准：

- 输出 `[MemAgent codex ingest]`。
- `candidates` 大于 0；如果为 0，可以让 Codex 提高 `--limit` 或先去掉 `--project-only`。
- 生成 `report.md` 和 `candidates/candidate_*.md`。

### Step 2：让 Codex 帮你读候选

对 Codex 说：

```text
打开刚刚生成的 ingest report，挑 1-2 条你觉得最像可复用工程经验的 candidate 给我解释一下，先不要保存。
```

通过标准：

- Codex 能指出 candidate 的来源和大意。
- 你能判断它是“下次有用的经验”，而不是普通聊天摘要。
- 如果 candidate 有敏感 raw output 或太长，Codex 应该建议编辑后再保存。

### Step 3：保存一条你认可的 memory

对 Codex 说：

```text
把 candidate 1 改写成一条短的 MemAgent memory，先给我预览，确认后再保存。
```

你确认后再说：

```text
确认保存。
```

期望 Codex 做的事：

- 先给出短 topic、kind、trigger、memory text。
- 再调用 `memagent remember`。
- 不要把整段 candidate 原文直接塞进 memory。

通过标准：

- 输出 `Saved memory: .../*.memory.yaml`。
- 这条 memory 是 1-3 句话的可复用经验。

### Step 4：测试召回和 trace

对 Codex 说：

```text
这是 MemAgent demo。召回一下相关记忆：bytedcli / RDS / owner 排查有没有以前踩过类似坑，需要留 trace。
```

期望 Codex 做的事：

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src python -m memagent.cli recall "<query>" \
  --show-sources \
  --show-reasons \
  --strategy bm25 \
  --trace
```

通过标准：

- 输出 `[MemAgent recalled context]`。
- 输出 sources / reasons / BM25 score。
- 如果召回到了刚保存的 memory，你主观上觉得它对当前任务有帮助。
- 输出 `[MemAgent recall trace saved]`。

### Step 5：测试反馈闭环

如果召回有用，对 Codex 说：

```text
这次召回有用，标记一下。然后生成 trace eval 和 trace replay 报告。
```

期望 Codex 做的事：

```bash
memagent trace label --rating useful --note "<short reason>"
memagent trace eval
memagent trace replay
```

通过标准：

- `trace label` 成功。
- `trace eval` 生成 Markdown report。
- `trace replay` 生成 top-stability report。

### Step 6：测试 handoff

对 Codex 说：

```text
记录当前进展，生成一个 handoff。把刚刚保存 memory、跑过 ingest、trace eval/replay 的状态写进去。
```

通过标准：

- Codex 先总结本轮状态。
- 写入 `handoff save` 或从 notes 生成 `handoff draft`。
- 再说 `上次做到哪` 时，能用 `handoff show` 取回最近状态。

## 5. 产品验收表

| 验收项 | 通过标准 | 你的结论 |
|---|---|---|
| 自然语言触发 | 不需要你手敲命令，Codex 能按 AGENTS.md 调用 MemAgent | 待填 |
| ingest 候选质量 | 至少 1 条 candidate 像真实可复用经验 | 待填 |
| memory 保存质量 | 保存的是短经验，不是整段 transcript | 待填 |
| recall 有用性 | 相关 query 能召回刚保存或历史 memory | 待填 |
| trace 闭环 | 能 label、eval、replay | 待填 |
| handoff 有用性 | 新线程可通过 handoff 了解上次进展 | 待填 |
| 面试可讲性 | 你能用 demo-bundle 讲清 AGENTS.md / RAG / MCP / eval | 待填 |

## 6. 结果怎么判断

如果这轮自测通过：

- v0.26 可以做 candidate accept/reject 状态和 promote 命令。
- v0.27 可以接 DeepSeek/Qwen/GLM 做 LLM-assisted extraction。
- v0.28 可以把 ingest 暴露成 MCP tool。

如果主要问题是 candidate 太噪：

- 下一步先做过滤、去重、按项目/关键词筛选。

如果主要问题是 recall 不准：

- 下一步先做 retriever/reranker，而不是继续扩功能。

如果主要问题是 Codex 不按 AGENTS.md 触发：

- 下一步优化 AGENTS.md trigger 文案和 `agents-doctor` 检查项。

## 7. 一句话结论模板

自测结束后，可以用这个格式反馈：

```text
v0.25 自测结论：
- 自然语言触发：通过/不通过，原因是...
- ingest 候选：有用/偏噪，最有用的一条是...
- recall：能/不能召回，query 是...
- trace eval/replay：跑通/没跑通，卡在...
- 下一版我希望优先做：候选确认流 / LLM 抽取 / recall 改进 / MCP ingest / UI
```
