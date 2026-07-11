# Contributing

Thanks for improving MemAgent. Please keep changes local-first, small, and
reviewable.

1. Open or update an issue before large behavior changes.
2. Keep default behavior free of required network calls and API keys.
3. Do not add secrets, private transcripts, proprietary examples, or absolute
   machine paths to code, tests, fixtures, or documentation.
4. Add focused tests for user-visible behavior and run:

```bash
python -m unittest discover -s tests
python -m compileall src tests
```

By contributing, you agree that your contribution may be distributed under the
Apache-2.0 license.
