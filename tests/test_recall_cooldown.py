from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from memagent.context import ProjectContext
from memagent.recall_cooldown import RecallCooldownStore


class RecallCooldownStoreTest(unittest.TestCase):
    def test_same_session_suppresses_even_when_task_adds_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RecallCooldownStore(Path(tmp))
            context = _context(Path(tmp) / "project")

            store.record(
                context=context,
                memory_id="mem_workflow",
                discriminative_terms=("merge", "conflict"),
                session_id="session-a",
            )

            same_session = store.check(
                context=context,
                memory_id="mem_workflow",
                discriminative_terms=("merge", "conflict", "rollback"),
                session_id="session-a",
            )
            new_session = store.check(
                context=context,
                memory_id="mem_workflow",
                discriminative_terms=("merge", "conflict", "rollback"),
                session_id="session-b",
            )

            self.assertTrue(same_session.suppressed)
            self.assertEqual(same_session.scope, "session")
            self.assertFalse(new_session.suppressed)
            raw = store.path.read_text(encoding="utf-8")
            self.assertNotIn("session-a", raw)

    def test_time_fallback_keeps_new_signal_behavior(self) -> None:
        now = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            store = RecallCooldownStore(Path(tmp), now=lambda: now)
            context = _context(Path(tmp) / "project")
            store.record(
                context=context,
                memory_id="mem_workflow",
                discriminative_terms=("merge", "conflict"),
            )

            repeated = store.check(
                context=context,
                memory_id="mem_workflow",
                discriminative_terms=("merge", "conflict"),
            )
            new_signal = store.check(
                context=context,
                memory_id="mem_workflow",
                discriminative_terms=("merge", "conflict", "rollback"),
            )

            self.assertTrue(repeated.suppressed)
            self.assertFalse(new_signal.suppressed)
            self.assertEqual(new_signal.scope, "time")


def _context(project: Path) -> ProjectContext:
    project.mkdir(parents=True, exist_ok=True)
    return ProjectContext(
        cwd=project,
        git_root=project,
        branch="main",
        repo_name=project.name,
        recent_files=(),
        agents_files=(),
    )


if __name__ == "__main__":
    unittest.main()
