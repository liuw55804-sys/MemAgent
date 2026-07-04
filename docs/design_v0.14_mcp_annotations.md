# MemAgent v0.14 MCP Tool Annotations Design

## 1. Goal

Give every MemAgent MCP tool explicit behavior hints:

- read-only or write-capable
- destructive or additive
- idempotent or not
- closed-world local memory or open-world external access

This does not change command behavior. It makes the MCP surface easier for
coding agents and MCP clients to reason about.

## 2. Why Now

The competitive scan found that mature local memory systems such as Basic
Memory expose MCP tools with behavior hints. The MCP 2025-11-25 schema also
defines `ToolAnnotations` for `readOnlyHint`, `destructiveHint`,
`idempotentHint`, and `openWorldHint`.

MemAgent's MCP server already had useful tools, but the tool list did not say
which tools only inspect memory and which tools may write local files. That is
fine for manual CLI use, but weak for agentic use because a client cannot make a
clean approval decision.

## 3. Classification

| Tool | Classification | Reason |
|---|---|---|
| `memagent_recall` | read-only, idempotent | Reads local memory and composes context. |
| `memagent_agents_doctor` | read-only, idempotent | Checks AGENTS.md integration and memory count. |
| `memagent_handoff_show` | read-only, idempotent | Reads the latest handoff. |
| `memagent_remember` | write-capable, non-idempotent | Creates a new memory card. |
| `memagent_handoff_save` | write-capable, non-idempotent | Saves latest/history handoff files. |
| `memagent_handoff_draft` | write-capable, non-idempotent | Can preview, but can also save with `save=true`. |
| `memagent_handoff_promote` | write-capable, non-idempotent | Can preview, but can also write memory cards. |

All current tools are marked `destructiveHint=false` because they do not delete
or intentionally destroy memory. The tools that write are additive or preserve
history.

All current tools are marked `openWorldHint=false` because they operate on local
memory/project files rather than external systems such as web search or remote
APIs.

## 4. Interview Angle

This is a small implementation detail, but it supports a bigger story:

> MemAgent is not just a CLI wrapper. It exposes a protocol-aware memory surface
> for coding agents. The MCP tool descriptions include safety and retry hints, so
> future clients can distinguish harmless recall from memory mutations.

That makes the MCP part more concrete than simply saying "I added an MCP
server".

## 5. Future Extension

Two tools currently mix preview and write behavior:

- `memagent_handoff_draft`
- `memagent_handoff_promote`

For v0.14, they are conservatively marked as write-capable. Later versions can
split them into separate preview/write tools if a client needs finer-grained
approval.

