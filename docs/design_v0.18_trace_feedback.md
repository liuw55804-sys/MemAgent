# MemAgent v0.18 Trace Feedback Design

## 1. Goal

Turn saved recall traces into a simple feedback loop.

New commands:

```bash
memagent trace label --rating useful
memagent trace label trace_... --rating not-useful --note "Wrong memory"
memagent trace report
```

## 2. Why This Matters

v0.17 made real recall runs observable, but observability alone does not measure
quality. v0.18 adds human feedback on top of traces:

```text
recall --trace
  -> trace JSON
  -> trace label useful / not_useful / neutral
  -> trace report
  -> real-use recall quality signal
```

This keeps the RAG story honest. Instead of only saying "BM25 works on a mock
benchmark", MemAgent can now collect real session feedback and summarize useful
rate.

## 3. Storage

Feedback is written back into the saved trace JSON:

```json
{
  "feedback": {
    "rating": "useful",
    "note": "Matched the intended workflow.",
    "labeled_at": "..."
  }
}
```

Allowed ratings:

- `useful`
- `not_useful` / `not-useful`
- `neutral`

## 4. CLI Behavior

Label latest trace:

```bash
memagent trace label --rating useful
```

Label a specific trace:

```bash
memagent trace label trace_20260704_104431_536549 --rating not-useful --note "Matched stale memory."
```

Summarize recent traces:

```text
[MemAgent recall trace report]
- traces inspected: 10
- labeled: 7
- useful: 5
- not_useful: 1
- neutral: 1
- unlabeled: 3
- useful_rate: 0.71
```

## 5. Interview Angle

This closes a small but meaningful evaluation loop:

> I added opt-in trace logging and feedback labels, so recall quality can be
> evaluated from real coding-agent sessions. The system can now report how many
> recalled contexts were actually useful, which is a path toward data-driven
> retriever and context-packing iteration.

## 6. Future Extension

Trace feedback can later support:

- replay-based regression tests
- stale memory detection when traces are repeatedly not useful
- automatic promotion when traces are repeatedly useful
- comparison between keyword, BM25, vector, and reranker strategies
- lightweight UI for trace review
