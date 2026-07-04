# MemAgent v0.22 MCP Demo Transcript Design

## 1. Goal

Generate a concrete MCP JSON-RPC transcript from local mock data.

New command:

```bash
memagent mcp-demo --reset
```

Default output:

```text
local_memory_demo/mcp_demo/mcp_transcript.md
```

`demo-bundle` also runs this command internally and links the transcript from
`interview_demo.md`.

## 2. Why This Matters

Before v0.22, MemAgent could show an MCP tool table. That proved the tools were
defined, but it did not prove a client could actually speak JSON-RPC to the
server.

`mcp-demo` captures a small protocol-level run:

- `initialize`
- `notifications/initialized`
- `tools/list`
- `tools/call memagent_agents_doctor`
- `tools/call memagent_remember`
- `tools/call memagent_recall`
- `tools/call memagent_handoff_save`
- `tools/call memagent_handoff_show`
- `tools/call memagent_trace_list`
- `tools/call memagent_trace_label`
- `tools/call memagent_trace_report`
- `tools/call memagent_trace_eval`
- `tools/call memagent_trace_replay`

This makes the MCP story inspectable instead of only conceptual.

## 3. Implementation Choice

The transcript is generated in-process by calling `McpServer.handle(...)` with
JSON-RPC request dictionaries. It does not start a background server or open a
network port.

That keeps the demo deterministic while still exercising the same MCP adapter
used by `mcp-stdio`.

## 4. Trace Setup

MCP recall is read-only, so it does not create traces by itself. The demo seeds
one recall trace from the same local memory store before calling trace tools.

That keeps `memagent_recall` correctly annotated as read-only while still letting
the transcript demonstrate trace labeling, reporting, eval, and replay.

## 5. Interview Angle

Use this when asked whether MCP is just a buzzword in the project:

> I can show the actual JSON-RPC transcript: initialize, tools/list, and
> tools/call for remember, recall, handoff, and trace feedback. The transcript is
> generated from the same adapter used by the stdio server, so the demo validates
> the protocol surface rather than only listing CLI commands.

## 6. Future Extension

- capture raw stdio bytes from `mcp-stdio`
- add negative/error tool-call examples
- compare CLI and MCP outputs side by side
- include MCP transcript snippets in a static HTML demo
