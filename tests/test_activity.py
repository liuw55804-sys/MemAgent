from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from memagent.activity import build_activity_report, render_activity_report
from memagent.cli import main
from memagent.context import ProjectContext
from memagent.handoff import HandoffStore
from memagent.memory import MemoryStore


class ActivityTest(unittest.TestCase):
    def test_project_activity_uses_local_records_without_project_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            context = _context(project)
            store = MemoryStore(root / "home")
            handoffs = HandoffStore(store.home)

            saved_recall = store.save_recall_trace(
                {
                    "context": {
                        "cwd": str(context.cwd),
                        "git_root": str(context.git_root),
                        "repo_name": context.repo_name,
                    },
                    "matches": [{"title": "Live schema entrypoint"}],
                },
                source="test",
            )
            store.label_recall_trace(saved_recall.identifier, rating="useful", note="helped")
            store.save_process_trace(
                {
                    "context": {
                        "cwd": str(context.cwd),
                        "git_root": str(context.git_root),
                        "repo_name": context.repo_name,
                    },
                    "route": {"action": "recall"},
                    "artifacts": {"matches": 1, "trace_id": saved_recall.identifier},
                },
                source="test",
            )
            store.remember(
                text="Check the live schema before tracing an owner issue.",
                topic="Live schema entrypoint",
                domain="coding",
                kind="data_entrypoint",
                repo=context.repo_name,
                module=None,
                triggers=["schema"],
                exportable=False,
            )
            handoffs.save(
                context=context,
                topic="Owner diagnosis",
                summary="Recorded the current owner-diagnosis state.",
                done=["Checked the live schema."],
                next_steps=["Trace the call path."],
                open_questions=[],
                memory_candidates=[],
            )

            report = build_activity_report(
                store=store,
                handoff_store=handoffs,
                context=context,
            )

            self.assertEqual(report.action_counts, {"recall": 1})
            self.assertEqual(report.recall_total, 1)
            self.assertEqual(report.feedback_counts, {"useful": 1})
            self.assertEqual(report.memory_count, 1)
            self.assertEqual(report.handoff_count, 1)
            self.assertIn("Live schema entrypoint", render_activity_report(report))
            self.assertFalse((project / "AGENTS.md").exists())

    def test_activity_cli_json_filters_to_current_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            project = root / "project"
            other = root / "other"
            project.mkdir()
            other.mkdir()
            context = _context(project)
            other_context = _context(other)
            store = MemoryStore(home)
            for item in (context, other_context):
                store.save_process_trace(
                    {
                        "context": {
                            "cwd": str(item.cwd),
                            "git_root": str(item.git_root),
                            "repo_name": item.repo_name,
                        },
                        "route": {"action": "draft_memory"},
                        "artifacts": {},
                    },
                    source="test",
                )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--home",
                        str(home),
                        "activity",
                        "--cwd",
                        str(project),
                        "--today",
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["schema_version"], "memagent.activity.v1")
            self.assertEqual(payload["summary"]["actions"], {"draft_memory": 1})


def _context(project: Path) -> ProjectContext:
    return ProjectContext(
        cwd=project.resolve(),
        git_root=project.resolve(),
        branch="main",
        repo_name=project.name,
        recent_files=(),
        agents_files=(),
    )


if __name__ == "__main__":
    unittest.main()
