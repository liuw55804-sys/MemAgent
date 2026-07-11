# Release Readiness

This repository is prepared for a first public release without performing a
publication from this checkout.

## Local verification

Run before a release:

```bash
python -m unittest discover -s tests
python -m compileall src tests
python -m build
```

Then use temporary environments to verify both supported installation paths:

```bash
python -m venv /tmp/memagent-verify
/tmp/memagent-verify/bin/python -m pip install .
/tmp/memagent-verify/bin/memagent --help

pipx install .
memagent install-user-codex --write
memagent user-codex-doctor
```

The repository CI repeats tests, compilation, wheel/sdist build, and pipx
smoke checks on supported Python versions.

## Public-content scan

Before publishing, scan for organization-specific references and common secret
shapes. Investigate every match; examples that intentionally test redaction
should use clearly fake values and must never be credentials.

```bash
rg -n -i "private platform|organization domain|personal machine path" .
rg -n "(sk|rk|pk)-[A-Za-z0-9_-]{8,}|BEGIN [A-Z ]*PRIVATE KEY" .
```

## First release recommendation

Use **v0.1.0** for the first public release. The package has a stable local
core and an intentionally opt-in LLM surface, while broader compatibility and
retrieval-quality evidence can mature in later minor releases.
