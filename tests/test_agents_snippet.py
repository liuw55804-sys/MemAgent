from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import unittest

from memagent.agents import build_agents_snippet
from memagent.cli import main


class AgentsSnippetTest(unittest.TestCase):
    def test_build_agents_snippet(self) -> None:
        root = Path("/tmp/memagent").resolve()
        snippet = build_agents_snippet(root)
        self.assertIn("## MemAgent Natural Language Triggers", snippet)
        self.assertIn("召回一下相关记忆", snippet)
        self.assertIn("沉淀一下", snippet)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli recall", snippet)
        self.assertIn("--show-sources --show-reasons", snippet)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli remember", snippet)
        self.assertIn("Treat recalled memories as hints", snippet)
        self.assertIn("Never store tokens", snippet)

    def test_agents_snippet_cli(self) -> None:
        root = Path("/tmp/memagent").resolve()
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = main(["agents-snippet", "--memagent-root", "/tmp/memagent"])
        self.assertEqual(exit_code, 0)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
