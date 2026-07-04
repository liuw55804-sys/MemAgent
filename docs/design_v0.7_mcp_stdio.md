# MemAgent v0.7 MCP Stdio Design

v0.7 的目标是给 MemAgent 增加一个最小 MCP adapter，让项目能覆盖：

```text
AGENTS.md natural-language trigger
  + RAG-style recall
  + MCP tools
  + prompt patch
```

## 1. 官方协议依据

MCP 最新规范 `2025-11-25` 中：

- Tools 是模型可发现和调用的能力，客户端通过 `tools/list` 发现工具，通过 `tools/call` 调用工具。
- 支持 tools 的 server 要在 initialize 阶段声明 `tools` capability。
- stdio transport 中，client 作为子进程启动 server；server 从 stdin 读取逐行 JSON-RPC 消息，并只向 stdout 写合法 MCP 消息。

参考：

- [MCP Tools 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [MCP Lifecycle 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- [MCP Transports 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)

## 2. 命令

```bash
memagent mcp-stdio
```

开发阶段：

```bash
PYTHONPATH=src python -m memagent.cli mcp-stdio
```

它是一个本地 stdio server，不启动 HTTP 端口，也不绑定网络地址。

## 3. 暴露的 tools

### `memagent_recall`

根据 query 召回本地 workflow memory。

参数：

- `query`
- `cwd`
- `limit`
- `max_lines`
- `show_sources`
- `show_reasons`
- `strategy`

### `memagent_remember`

写入一条短 memory。

参数：

- `text`
- `topic`
- `domain`
- `kind`
- `repo`
- `module`
- `triggers`
- `exportable`
- `cwd`

### `memagent_agents_doctor`

检查当前项目 AGENTS.md 是否已经接入 MemAgent。

参数：

- `cwd`

## 4. 为什么先做 stdio

MemAgent 是本地 coding-agent workflow memory。stdio 更适合当前阶段：

- 不需要端口和鉴权。
- 不引入服务端部署复杂度。
- 适合 IDE、CLI、Claude Code、Cursor 等本地 MCP client。
- 安全边界更清楚，memory 默认仍在本机。

HTTP / Streamable HTTP 可以作为后续扩展，但不是 v0.7 目标。

## 5. 与 AGENTS.md 的关系

二者不是互相替代：

```text
AGENTS.md integration:
  Codex 根据自然语言规则调用 MemAgent CLI

MCP integration:
  MCP client 通过 tools/list 发现 MemAgent tools，再通过 tools/call 调用
```

这让 MemAgent 有两种入口：

- Codex-first 的 AGENTS.md 入口。
- Vendor-neutral 的 MCP tools 入口。

## 6. 面试讲法

可以这样讲：

> MemAgent 的核心不是 MCP，而是 coding workflow memory。但为了让这层 memory 能被不同 coding agent 使用，我把 recall、remember 和 AGENTS.md doctor 包成了 MCP tools。这样 Codex 可以走 AGENTS.md，自带 MCP client 的 IDE 或 agent 可以走 MCP。两条入口共用同一套 memory store 和 recall logic。
