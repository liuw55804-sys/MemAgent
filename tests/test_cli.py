from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import os
import tempfile
import unittest

from memagent.cli import main


class CliTest(unittest.TestCase):
    def test_recall_json_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            project = root / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(project)
                remember_stdout = StringIO()
                with redirect_stdout(remember_stdout):
                    remember_code = main(
                        [
                            "--home",
                            str(home),
                            "remember",
                            "--topic",
                            "RDS timeout pitfall",
                            "--kind",
                            "pitfall",
                            "--trigger",
                            "RDS",
                            "Use id ranges before RDS JSON grouping.",
                        ]
                    )
                self.assertEqual(remember_code, 0)

                recall_stdout = StringIO()
                with redirect_stdout(recall_stdout):
                    recall_code = main(
                        [
                            "--home",
                            str(home),
                            "recall",
                            "RDS JSON timeout",
                            "--show-sources",
                            "--show-reasons",
                            "--json",
                        ]
                    )
                self.assertEqual(recall_code, 0)
            finally:
                os.chdir(previous_cwd)

            payload = json.loads(recall_stdout.getvalue())
            self.assertEqual(payload["schema_version"], "memagent.recall.v1")
            self.assertEqual(payload["query"], "RDS JSON timeout")
            self.assertEqual(payload["context"]["repo_name"], "project")
            self.assertEqual(payload["matches"][0]["title"], "RDS timeout pitfall")
            self.assertEqual(payload["matches"][0]["kind"], "pitfall")
            self.assertIn("Pack:", payload["text"])
            self.assertFalse(payload["pack"]["truncated"])


if __name__ == "__main__":
    unittest.main()
