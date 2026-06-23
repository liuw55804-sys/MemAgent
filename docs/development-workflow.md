# MemAgent Development Workflow

This project should move in small, understandable steps. The goal is not just to make MemAgent work, but to make every layer easy to explain later.

## Version Names

Current baseline:

```text
v0.1.0-mvp
```

Use `v0.x` while the product shape is still changing. Reserve `v1.0.0` for a version that has a stable user flow, stable memory schema, and a clear integration story.

## Git Habits

Recommended rhythm:

```text
1. Read or update docs first.
2. Make one small code change.
3. Add or update focused tests.
4. Run the narrowest useful verification.
5. Commit with a clear message.
```

Good commit examples:

```text
docs: explain memory store flow
feat: add markdown ingest command
test: cover recall scoring by repo scope
refactor: split memory card rendering
```

Avoid giant commits that mix product design, code changes, test rewrites, and formatting.

## Branching

Keep `main` as the stable local baseline.

For new work, create a branch:

```bash
git switch -c codex/ingest-markdown
```

Merge or fast-forward back to `main` only after the feature is understood, documented, and tested.

## What To Update With Each Change

Use this checklist:

```text
- Product behavior changed? Update README or product-plan.
- Code structure changed? Update technical-walkthrough.
- User workflow changed? Update README examples.
- New version-worthy milestone? Update CHANGELOG.
- Python logic changed? Run compileall and unittest.
```

## Version Plan Documents

Keep version direction documents stable. If the product direction changes
substantially, create a new plan file instead of rewriting the old one:

```text
docs/plan_v2.md
docs/plan_v3.md
docs/plan_v4.md
```

Small clarifications are fine, but do not use a version plan as a scratchpad.

## Verification

For Python logic changes:

```bash
PYTHONPATH=src python -m compileall src tests
PYTHONPATH=src python -m unittest discover -s tests
```

For docs-only changes, a quick Markdown/readability scan is enough.

## Development Principle

Before adding a feature, answer:

```text
Which layer owns this?
  cli.py, context.py, memory.py, wrapper.py, or a new module?

Does this change the memory card schema?

Can the current user explain the feature after reading the docs?

What is the smallest test that protects the behavior?
```
