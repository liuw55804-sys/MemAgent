# v0.13 Handoff Candidate Promotion 设计

## 1. 背景

v0.12 已经能从 session notes 生成 handoff draft，并把 `Memory Candidates` 留在 handoff 里。但候选经验如果永远停在 handoff 中，就不会进入长期 recall/eval 流程。

v0.13 增加 promotion：

```text
handoff latest
  -> Memory Candidates
  -> preview promotion
  -> --write
  -> durable memory card
```

这补上了 MemAgent memory lifecycle 的关键一环。

## 2. 命令

预览第一条候选：

```bash
memagent handoff promote --index 1
```

写入第一条候选：

```bash
memagent handoff promote --index 1 --write
```

写入全部候选：

```bash
memagent handoff promote --all --write
```

默认是 dry-run，因为 promotion 会污染长期 RAG 语料，必须显式 `--write`。

## 3. 设计边界

promotion 只从 latest handoff 的 `Memory Candidates` section 里取候选，不把 `Summary`、`Done` 或 `Next Steps` 自动写成 memory。

原因：

- `Summary` 是最近状态。
- `Done` 是历史进展。
- `Next Steps` 是一次性计划。
- `Memory Candidates` 才是可能跨任务复用的经验。

## 4. 生命周期图

```mermaid
flowchart LR
  A["Session Notes"] --> B["Handoff Draft"]
  B --> C["Latest Handoff"]
  C --> D["Memory Candidates"]
  D --> E["Promotion Preview"]
  E --> F["Durable Memory Card"]
  F --> G["Recall / Eval"]
```

## 5. 面试讲法

可以这样讲：

> 我把 memory capture 拆成三个阶段：handoff draft 用于恢复上下文，memory candidates 用于标记潜在长期经验，promotion 用于显式写入长期 RAG 语料。这样能避免 agent 把整段线程都自动塞进长期记忆，同时保留从短期上下文到长期经验的路径。

这个点能回应一个常见追问：

> 你的系统怎么避免长期记忆越来越脏？

答案是：默认只 preview，不 `--write`；只 promotion `Memory Candidates`，不 promotion 整个 handoff；后续还能加 feedback、过期和冲突检测。
