# Architecture

MemAgent is a local workflow-memory layer, not an autonomous coding agent.

```mermaid
flowchart LR
  U["Coding agent task"] --> R["Local semantic router"]
  R -->|"recall"| S["Local memory store"]
  R -->|"draft"| D["Preview + confirmation"]
  D --> S
  R -->|"handoff / feedback"| S
  R -. "optional, sanitized only" .-> L["OpenAI-compatible endpoint"]
```

The default router is heuristic and never makes a network request. `llm` and
`hybrid` modes are explicit opt-ins. They can send only a short sanitized task
summary or candidate draft, plus minimal project-state booleans.

`~/.memagent/` contains memory cards, pending previews, local traces, and
handoffs. Durable cards are written only after explicit confirmation.
