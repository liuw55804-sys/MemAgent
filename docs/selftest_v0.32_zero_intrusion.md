# v0.32 Product Self-Test: Zero-Intrusion Codex

This is a short product check, not an RD test. Do it during normal work in
`audit_rule_lib`; there is no test data to prepare and no form to fill in.

## Before Starting

The user-level Skill has been installed once with:

```bash
cd /Users/bytedance/Desktop/work/personal_agents/memagent
PYTHONPATH=src python -m memagent.cli user-codex-doctor
```

It should report `status: current`. Open a new Codex task directly in
`/Users/bytedance/Desktop/work/attribution/audit_rule_lib` after installation.

## One Normal Development Flow

Use an actual task, then naturally say one of the following when appropriate:

1. At task start: `之前这个怎么查？先按上次靠谱的路径来。`

   Expected: Codex may use recalled guidance as a short hint, then still checks
   the live code and data path. If the recalled guidance helps, simply reply
   `刚刚那条有用`.

2. After finding a real reusable lesson: `这次踩坑记住，先给我看要保存的内容。`

   Expected: Codex shows a short preview. Reply `确认保存` only if the preview
   is correct. The reviewed preview becomes a durable local memory; Codex does
   not need to reconstruct its fields from the chat.

3. Before leaving the task: `先到这，下次从这里接。`

   Expected: Codex stores a compact handoff with the current progress, not a
   full transcript.

4. Later, in any Codex task: `MemAgent 今天干了什么？`

   Expected: Codex summarizes the current project's local MemAgent activity.

## What To Tell Me Here

Only report the product feeling in this conversation: whether the timing felt
natural, whether a recalled item was relevant, and whether a preview was too
long or wrong. Do not manually inspect or copy traces unless we are debugging.

I can inspect the local evidence afterward with:

```bash
PYTHONPATH=/Users/bytedance/Desktop/work/personal_agents/memagent/src \
python -m memagent.cli activity \
  --cwd /Users/bytedance/Desktop/work/attribution/audit_rule_lib \
  --today
```

## Non-Intrusion Check

At the end, run this inside `audit_rule_lib`:

```bash
git status --short
```

MemAgent must not add files or modify `AGENTS.md` there. Its state belongs in
`~/.memagent/` and its Codex Skill belongs in `~/.codex/skills/memagent/`.
