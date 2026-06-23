from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from memagent.context import ProjectContext
from memagent.memory import MemoryStore


class MemoryStoreTest(unittest.TestCase):
    def test_remember_and_recall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            saved = store.remember(
                text="RDS JSON aggregation timed out; split by id ranges before grouping.",
                topic="RDS query pitfall",
                repo="walle",
                module="machine_attribution",
                triggers=["RDS", "JSON", "accuracy"],
                exportable=False,
            )
            self.assertTrue(saved.path.exists())

            context = ProjectContext(
                cwd=Path("/tmp/walle"),
                git_root=Path("/tmp/walle"),
                branch="main",
                repo_name="walle",
                recent_files=(),
                agents_files=(),
            )
            matches = store.recall("how to avoid RDS JSON timeout", context=context, limit=3)
            self.assertEqual(len(matches), 1)
            rendered = store.compose_context(
                query="how to avoid RDS JSON timeout",
                context=context,
                matches=matches,
                max_lines=8,
                show_sources=True,
            )
            self.assertIn("RDS query pitfall", rendered)
            self.assertIn("split by id ranges", rendered)


if __name__ == "__main__":
    unittest.main()

