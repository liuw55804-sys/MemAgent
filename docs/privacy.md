# Privacy Model

MemAgent is local-first by default. It stores its state under `~/.memagent/`
and does not require a model provider or account.

When optional LLM semantics are enabled, MemAgent minimizes requests:

- short task summaries, draft candidates, and up to three candidate-memory
  summaries only;
- recall estimation receives no existing memory cards, full transcript, path,
  repository name, or raw project content;
- absolute paths, URLs, token-like values, compound identifiers, and long
  numbers are generalized before the request;
- candidate summaries are sanitized and sent only for ambiguous relevance
  decisions in `hybrid` or `llm` mode;
- no full conversation export, full memory library, API key, cookie,
  password, private key, or raw request/response body is intentionally sent.

`memagent configure` writes only endpoint metadata, model name, semantic mode,
and the **name** of an environment variable that holds a key. It does not write
the key itself. Local compatible services can be configured without a key.

Review any memory before confirmation. Do not store secrets or sensitive raw
samples in local memory.
