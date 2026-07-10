# v0.33 Product Self-Test: Lifecycle Report

Use this during normal work. There is no test fixture to create and no trace
file to inspect manually.

1. In a new Codex task in a real project, ask a repeated-work question such as
   `之前这个怎么查？`

2. If a recalled hint helps, reply naturally: `刚刚那条有用。`

3. After a real reusable lesson, say: `记住这次踩坑，先给我看预览。`

4. Either say `确认保存` or leave the draft alone while continuing work. A later
   draft in the same project intentionally supersedes the previous pending one.

5. Ask Codex: `MemAgent 最近做得怎么样？`

The report should be short and say how many recalls received feedback, how many
drafts are pending or confirmed, and whether any saved memory was recalled
again. Report product feeling in the conversation; do not copy trace IDs.

For a non-intrusion check, `git status --short` in the service repository must
remain unchanged. MemAgent data belongs only in `~/.memagent/`.
