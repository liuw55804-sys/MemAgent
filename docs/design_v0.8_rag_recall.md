# MemAgent v0.8 RAG Recall Design

v0.8 的目标是把 recall 从简单 keyword count 升级成更像 RAG retriever 的实现。

```text
query
  -> tokenize
  -> BM25-style scoring
  -> repo scope bonus
  -> explainable context
  -> context pack
  -> Codex prompt patch
```

## 1. 背景

早期 recall 使用：

```text
score = query term count in raw memory text
```

这个 baseline 好理解，但有明显问题：

- 某个词重复很多次会刷高分。
- 不考虑文档长度。
- 很难讲成一个完整 RAG retriever。

v0.8 引入轻量 BM25-style scoring，同时保留 keyword strategy 作为调试 baseline。

## 2. 命令

默认使用 BM25：

```bash
memagent recall "attribution accuracy" --show-sources --show-reasons
```

显式指定：

```bash
memagent recall "attribution accuracy" --strategy bm25
memagent recall "attribution accuracy" --strategy keyword
```

`codex` 同样支持：

```bash
memagent codex --dry-run --strategy bm25 "continue attribution accuracy debugging"
```

## 3. Explainable Output

`--show-reasons` 输出：

```text
- Pack: 1/3 memories; budget=8 memory lines/1200 chars; deduped=0; truncated=no
- Memory: ... | score=2.41; strategy=bm25; matched=attribution, accuracy
```

这让用户知道：

- 这条 memory 为什么被召回。
- 当前使用的是哪个 scoring strategy。
- 命中了哪些 query terms。
- 最终 prompt patch 是否经过预算截断或重复建议去重。

## 4. 为什么不是向量召回

v0.8 先做 BM25 而不是 embedding/vector：

- 不依赖外部模型 API。
- 能稳定本地自测。
- 对短 workflow memory 足够有效。
- 更容易解释和 debug。

后续可以做 hybrid recall：

```text
BM25 candidates
  + vector similarity
  + LLM rerank
  + lifecycle filters
```

## 5. 面试讲法

可以这样讲：

> MemAgent 的 memory card 是 RAG 语料，recall 是 retriever，prompt patch 是检索增强上下文。早期我用 keyword count 做 baseline，v0.8 加了 BM25-style scoring，解决词频刷分和长文档偏置问题，同时保留 matched terms 和 strategy 作为 explainability。
