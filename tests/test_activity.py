from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from memagent.activity import build_activity_report, render_activity_report
from memagent.cli import main
from memagent.context import ProjectContext, context_payload, detect_context
from memagent.handoff import HandoffStore
from memagent.interaction import process_interaction, reflect_on_task
from memagent.memory import MemoryStore


class ActivityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.semantic_mode = mock.patch.dict(
            os.environ,
            {"MEMAGENT_SEMANTIC_MODE": "heuristic"},
        )
        self.semantic_mode.start()
        self.addCleanup(self.semantic_mode.stop)

    def test_activity_aggregates_main_checkout_and_git_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "service"
            worktree = root / "worktree"
            _init_repo(main)
            _git(main, "worktree", "add", "--detach", str(worktree))
            main_context = detect_context(main)
            worktree_context = detect_context(worktree)
            store = MemoryStore(root / "home")
            for item in (main_context, worktree_context):
                store.save_process_trace(
                    {
                        "context": context_payload(item),
                        "route": {"action": "none"},
                        "artifacts": {
                            "recall_considered": True,
                            "candidates": 1,
                            "emitted": 0,
                            "abstained": True,
                        },
                    },
                    source="test",
                )

            report = build_activity_report(
                store=store,
                handoff_store=HandoffStore(store.home),
                context=main_context,
            )

            self.assertEqual(report.retrieval["considered"], 2)
            self.assertEqual(report.retrieval["abstained"], 2)

    def test_empty_activity_report_is_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _context(root / "project")
            store = MemoryStore(root / "home")

            report = build_activity_report(
                store=store,
                handoff_store=HandoffStore(store.home),
                context=context,
            )

            rendered = render_activity_report(report)
            self.assertIn("No local MemAgent activity", rendered)
            self.assertNotIn("Draft lifecycle", rendered)
            self.assertNotIn("Memory reuse", rendered)

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
            store.mark_recall_adoption(saved_recall.identifier, signal="executed", note="used")
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
                text="Check the live schema before tracing an maintainer issue.",
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
                summary="Recorded the current maintainer-diagnosis state.",
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
            self.assertEqual(report.adoption_counts, {"executed": 1})
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
            self.assertEqual(payload["schema_version"], "memagent.activity.v2")
            self.assertEqual(payload["summary"]["actions"], {"draft_memory": 1})

    def test_activity_reports_precision_and_proactive_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _context(root / "project")
            store = MemoryStore(root / "home")
            handoffs = HandoffStore(store.home)
            store.save_process_trace(
                {
                    "context": {
                        "cwd": str(context.cwd),
                        "git_root": str(context.git_root),
                        "repo_name": context.repo_name,
                    },
                    "route": {"action": "none"},
                    "artifacts": {
                        "recall_considered": True,
                        "candidates": 3,
                        "emitted": 0,
                        "abstained": True,
                        "candidate_generation_ms": 2,
                        "local_relevance_ms": 1,
                        "relevance_gate_ms": 0,
                        "recall_cooldown_scope": "session",
                    },
                },
                source="test",
            )
            draft = process_interaction(
                message="The agent found a reusable lesson.",
                recent_text="Verify the live interface before changing a generated client.",
                context=context,
                store=store,
                handoff_store=handoffs,
                agent_suggested=True,
                suggestion_evidence="correction",
            )
            self.assertEqual(draft.route.action, "draft_memory")

            report = build_activity_report(store=store, handoff_store=handoffs, context=context)

            self.assertEqual(report.retrieval["considered"], 1)
            self.assertEqual(report.retrieval["abstained"], 1)
            self.assertEqual(report.retrieval["avg_candidate_generation_ms"], 2.0)
            self.assertEqual(report.retrieval["cooldown_scope_session"], 1)
            self.assertEqual(report.suggestions["suggested"], 1)
            self.assertEqual(report.suggestions["pending"], 1)
            rendered = render_activity_report(report)
            self.assertIn("Recall precision", rendered)
            self.assertIn("Proactive memory", rendered)

    def test_activity_links_agent_suggestion_acceptance_and_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _context(root / "project")
            store = MemoryStore(root / "home")
            handoffs = HandoffStore(store.home)
            process_interaction(
                message="The agent found a reusable lesson.",
                recent_text="Verify the live interface before changing generated code.",
                context=context,
                store=store,
                handoff_store=handoffs,
                agent_suggested=True,
                suggestion_evidence="correction",
            )
            process_interaction(
                message="确认保存",
                recent_text="",
                context=context,
                store=store,
                handoff_store=handoffs,
            )
            process_interaction(
                message="The agent found another reusable lesson.",
                recent_text="Run the focused parser test before the full test suite.",
                context=context,
                store=store,
                handoff_store=handoffs,
                agent_suggested=True,
                suggestion_evidence="workflow",
            )
            process_interaction(
                message="这条不用记了",
                recent_text="",
                context=context,
                store=store,
                handoff_store=handoffs,
            )

            report = build_activity_report(store=store, handoff_store=handoffs, context=context)

            self.assertEqual(report.suggestions["suggested"], 2)
            self.assertEqual(report.suggestions["accepted"], 1)
            self.assertEqual(report.suggestions["rejected"], 1)
            self.assertNotIn("pending", report.suggestions)

    def test_activity_distinguishes_pending_and_unconfirmed_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _context(root / "project")
            store = MemoryStore(root / "home")
            handoffs = HandoffStore(store.home)
            first = process_interaction(
                message="记住这次踩坑，先给预览。",
                recent_text="Before debugging maintainer assignment, inspect the live schema.",
                context=context,
                store=store,
                handoff_store=handoffs,
            )
            second = process_interaction(
                message="记住这个入口，先给预览。",
                recent_text="For audit errors, start from the live API entrypoint.",
                context=context,
                store=store,
                handoff_store=handoffs,
            )

            report = build_activity_report(store=store, handoff_store=handoffs, context=context)

            self.assertNotEqual(first.artifacts["pending_draft_id"], second.artifacts["pending_draft_id"])
            self.assertEqual(report.lifecycle.draft_total, 2)
            self.assertEqual(report.lifecycle.draft_confirmed, 0)
            self.assertEqual(len(report.lifecycle.draft_pending), 1)
            self.assertEqual(report.lifecycle.draft_unconfirmed, 1)
            self.assertIn("Pending draft", render_activity_report(report))

    def test_activity_reports_automatic_reflection_funnel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"CODEX_THREAD_ID": "activity-session"},
            clear=False,
        ):
            root = Path(tmp)
            context = _context(root / "project")
            store = MemoryStore(root / "home")
            handoffs = HandoffStore(store.home)
            reflect_on_task(
                summary=(
                    "Two attempts used a stale interface. Next time verify the live contract "
                    "before changing generated code."
                ),
                signals=("detour", "correction", "verified_outcome"),
                context=context,
                store=store,
            )
            reflect_on_task(
                summary=(
                    "A different investigation found a reusable validation step. "
                    "Next time run the focused validation before the full suite."
                ),
                signals=("workflow", "verified_outcome"),
                context=context,
                store=store,
            )
            process_interaction(
                message="确认保存",
                recent_text="",
                context=context,
                store=store,
                handoff_store=handoffs,
            )

            report = build_activity_report(store=store, handoff_store=handoffs, context=context)

            self.assertEqual(report.reflections["considered"], 2)
            self.assertEqual(report.reflections["emitted"], 1)
            self.assertEqual(report.reflections["abstained"], 1)
            self.assertEqual(report.reflections["session_suppressed"], 1)
            self.assertEqual(report.reflections["accepted"], 1)
            self.assertEqual(report.reflections["acceptance_rate"], 1.0)
            self.assertIn("Task reflections", render_activity_report(report))


def _context(project: Path) -> ProjectContext:
    return ProjectContext(
        cwd=project.resolve(),
        git_root=project.resolve(),
        branch="main",
        repo_name=project.name,
        recent_files=(),
        agents_files=(),
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init")
    _git(path, "config", "user.email", "memagent@example.test")
    _git(path, "config", "user.name", "MemAgent Test")
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial")


def _git(path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    unittest.main()
