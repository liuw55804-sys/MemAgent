# MemAgent v0.1.0 最小自测指南

> 当前推荐自测入口已更新到 [selftest_v0.25_codex_thread.md](selftest_v0.25_codex_thread.md)。
> 本文保留为 v0.1 手动 `remember/recall` 基线，用来对比早期闭环。

这份文档只回答一个问题：

> 我现在只有 Codex 的会话，怎么手动造出第一批 memory，并验证它有没有用？

先不要想“自动读取所有 Codex 线程”。当前版本没有这个能力。现在的做法是：**从已有 Codex 会话里人工挑一句有复用价值的结论，复制成 `memagent remember` 的输入。**

## 1. 什么算一条 memory

不是整段聊天记录，也不是完整总结。

一条 memory 应该像这样：

```text
当我下次遇到类似任务时，Codex 需要提前知道的一个事实、坑、命令入口或决策。
```

合适的例子：

- “MemAgent 当前是 v0.1.0-mvp，还没接 AI API，下一步先做自测再决定方向。”
- “大表 JSON 字段不要直接全表 group，先 limit 或按 id 范围分段。”
- “某类排查优先用某个 bytedcli 命令确认入口，不要先猜库表。”
- “某个统计口径要先确认人工标签来源，不要混用两个来源。”

不合适的例子：

- 整个 Codex 会话全文。
- 大段日志。
- 大段 SQL 结果。
- 没有复用价值的临时聊天。

## 2. 第一次自测用 MemAgent 自己做样本

先用项目内的本地 demo 目录，方便你直接在文件树里点开看：

```bash
cd /Users/bytedance/Desktop/work/personal_agents/memagent
rm -rf local_memory_demo
```

`local_memory_demo/` 已经写进 `.gitignore`，用于本地自测，不提交到 Git。

写入第一条 memory：

```bash
PYTHONPATH=src python -m memagent.cli --home ./local_memory_demo remember \
  --domain coding \
  --kind note \
  --topic "MemAgent baseline status" \
  --trigger "MemAgent" \
  --trigger "v0.1.0" \
  --trigger "AI" \
  "MemAgent 当前是 v0.1.0-mvp baseline：已经有 remember/recall/codex 三条命令，但还没有接任何大模型 API。下一步先做真实自测，再决定做 ingest、召回改进还是 AI provider。"
```

这条 memory 的来源就是当前 Codex 会话里的结论。

## 3. 看看 memory 文件长什么样

```bash
find ./local_memory_demo -type f -maxdepth 3 -print
```

你会看到类似：

```text
./local_memory_demo/memories/mem_20260623_xxxxxx.memory.yaml
```

打开它，会看到大概这样的结构：

```yaml
topic: "MemAgent baseline status"
scope:
  repo: "memagent"
triggers:
  - "MemAgent"
  - "v0.1.0"
  - "AI"
pitfalls:
  - "MemAgent 当前是 v0.1.0-mvp baseline..."
next_time_prompt:
  - "Before continuing, recall this lesson: ..."
```

这就是当前版本最朴素的 memory card。

## 4. 测 recall

现在假装你开启了一个新线程，又问：

```text
我现在要继续开发 MemAgent，要不要先接 AI API？
```

运行：

```bash
PYTHONPATH=src python -m memagent.cli --home ./local_memory_demo recall \
  "我现在要继续开发 MemAgent，要不要先接 AI API" \
  --show-sources
```

如果正常，会看到类似：

```text
[MemAgent recalled context]
- Task: 我现在要继续开发 MemAgent，要不要先接 AI API
- Context: cwd: .../memagent; repo: memagent; branch: main
- Memory: MemAgent baseline status (...)
  - MemAgent 当前是 v0.1.0-mvp baseline：已经有 remember/recall/codex 三条命令，但还没有接任何大模型 API。下一步先做真实自测，再决定做 ingest、召回改进还是 AI provider。
```

这就说明：你手动从旧会话里沉淀的一句话，被新任务召回了。

## 5. 测 codex prompt 注入

不真的启动 Codex，先 dry-run：

```bash
PYTHONPATH=src python -m memagent.cli --home ./local_memory_demo codex --dry-run \
  "我现在要继续开发 MemAgent，要不要先接 AI API"
```

你会看到最终传给 Codex 的 prompt：

```text
[MemAgent recalled context]
...

[User task]
我现在要继续开发 MemAgent，要不要先接 AI API
```

这就是 `memagent codex` 当前做的事情：**把召回上下文拼到用户任务前面。**

## 6. 用你自己的 Codex 会话造 3 条 memory

现在回到你自己的真实会话，不要追求自动化。先人工挑 3 句。

### Memory 1：项目状态

来自当前 MemAgent 会话：

```bash
PYTHONPATH=src python -m memagent.cli --home ./local_memory_demo remember \
  --domain coding \
  --kind note \
  --topic "MemAgent baseline status" \
  --trigger "MemAgent" \
  --trigger "AI" \
  "MemAgent 当前是 v0.1.0-mvp baseline，还没有接 AI API；先做自测，再决定下一步是 ingest、召回改进、prompt composition 还是 provider。"
```

### Memory 2：一个工具入口

来自你之前跑通 bytedcli / RDS / BAM 的 Codex 会话。

把里面最有用的一句复制出来，比如：

```bash
PYTHONPATH=src python -m memagent.cli --home ./local_memory_demo remember \
  --domain coding \
  --kind tool_recipe \
  --topic "某类排查的 bytedcli 入口" \
  --trigger "bytedcli" \
  --trigger "RDS" \
  "这里换成你真实会话里跑通的命令入口、库表定位方式、注意事项。"
```

这条可以保留真实内部入口，但只存在本机 `local_memory_demo/` 或 `~/.memagent`，不要提交进 Git。

### Memory 3：一个失败路径

来自你之前踩坑的会话。

比如：

```bash
PYTHONPATH=src python -m memagent.cli --home ./local_memory_demo remember \
  --domain coding \
  --kind pitfall \
  --topic "大表统计失败路径" \
  --trigger "大表" \
  --trigger "JSON" \
  --trigger "统计" \
  "大表 JSON 字段不要直接全表 group，先 limit 或按 id 范围分段验证。"
```

## 7. 这轮到底测什么

不要测“AI 是否聪明”，因为现在没有 AI。

只测三件事：

```text
1. 我能不能从旧 Codex 会话里挑出一句有复用价值的话？
2. 这句话能不能被 recall 找回来？
3. 拼到 Codex prompt 前后，我会不会觉得它真的有帮助？
```

如果第 1 步很痛苦，说明下一步该做 `ingest` / LLM extraction。

如果第 2 步经常失败，说明下一步该做召回算法。

如果第 3 步觉得废话多，说明下一步该做 prompt compression / memory schema。

## 8. 最小通过标准

这轮只要做到：

- 人工写入 3 条 memory。
- 其中 2 条能被相关 prompt 召回。
- 其中 1 条让你觉得“新线程确实少解释了一遍”。

就说明 v0.1.0 有继续迭代的价值。
