# MemAgent v0.9 Recall Evaluation Design

v0.9 的目标是让 MemAgent 的 RAG recall 不只是“能召回”，还“能被评估”。

```text
mock memories
  -> mock queries with expected topics
  -> run bm25 and keyword
  -> compute hit@1 and MRR
  -> report.md
```

## 1. 背景

v0.8 引入 BM25-style recall。面试时只说“我用了 BM25”还不够，最好能补一句：

> 我用一个 export-safe mock benchmark 对 retriever 做了 hit@1 / MRR 评估，并保留 keyword baseline 作为对照。

这能把项目从“做了检索”推进到“有检索评估意识”。

## 2. 命令

```bash
memagent recall-eval
```

默认写入：

```text
local_memory_demo/recall_eval/
  project/
  memagent_home/
  report.md
```

它不会读取真实 `~/.memagent`，只使用 mock memories。

## 3. 指标

当前评估两个指标：

- **Hit@1**：期望 memory 是否排在第一。
- **MRR**：mean reciprocal rank，衡量期望 memory 的平均排名质量。

## 4. Benchmark 设计

mock memories 包含：

- attribution accuracy workflow
- repeated accuracy noise
- RDS JSON aggregation pitfall
- owner diagnosis skill route
- AGENTS install workflow

其中 `Repeated accuracy noise` 用来验证 BM25 比 keyword count 更不容易被单词重复刷分。

## 5. 面试讲法

可以这样讲：

> 我没有只停在“召回能跑”，而是加了一个小型 mock benchmark。它会构造几类 workflow memory，用 query 跑 bm25 和 keyword 两个 strategy，并输出 hit@1 / MRR。这个评估不代表真实线上指标，但它把 retriever 的质量验证变成了可重复的工程流程。

## 6. 后续扩展

后续可以增加：

- 从真实匿名化 memory 中抽样构建 eval set。
- 记录用户反馈，做 online hit rate。
- 增加 reranker 前后的对比。
- 增加 query rewrite / memory compression 对结果的影响评估。
