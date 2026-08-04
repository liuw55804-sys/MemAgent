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

from memagent.activity import build_activity_report
from memagent.codex_skill import build_user_codex_skill_plan, write_user_codex_skill_plan
from memagent.cli import main
from memagent.context import detect_context
from memagent.handoff import HandoffStore
from memagent.interaction import process_interaction, reflect_on_task
from memagent.memory import MemoryStore


class ZeroIntrusionFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.semantic_mode = mock.patch.dict(
            os.environ,
            {"MEMAGENT_SEMANTIC_MODE": "heuristic"},
        )
        self.semantic_mode.start()
        self.addCleanup(self.semantic_mode.stop)

    def test_project_without_agents_md_keeps_git_clean_through_memory_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "example_service"
            project.mkdir()
            _git(project, "init")
            _git(project, "config", "user.email", "memagent@example.test")
            _git(project, "config", "user.name", "MemAgent Test")
            (project / "README.md").write_text("# demo\n", encoding="utf-8")
            _git(project, "add", "README.md")
            _git(project, "commit", "-m", "initial")
            context = detect_context(project)
            home = root / "memagent-home"
            store = MemoryStore(home)
            handoffs = HandoffStore(home)

            skill_target = root / "codex-home" / "skills" / "memagent" / "SKILL.md"
            install = build_user_codex_skill_plan(target=skill_target)
            write_user_codex_skill_plan(install)
            self.assertTrue(skill_target.exists())
            self.assertFalse((project / "AGENTS.md").exists())

            store.remember(
                text="Check the live database schema before tracing an example_service maintainer issue.",
                topic="example_service live schema",
                domain="coding",
                kind="data_entrypoint",
                repo=context.repo_name,
                module=None,
                triggers=["example_service", "maintainer", "schema"],
                exportable=False,
            )

            recalled = process_interaction(
                message="之前 example_service maintainer 问题怎么查？先按靠谱路径来。",
                recent_text="",
                context=context,
                store=store,
                handoff_store=handoffs,
            )
            self.assertEqual(recalled.route.action, "recall")
            self.assertIn("recall_trace", recalled.writes)

            feedback = process_interaction(
                message="刚刚那条有用。",
                recent_text="",
                context=context,
                store=store,
                handoff_store=handoffs,
            )
            self.assertEqual(feedback.route.action, "label_feedback")
            self.assertIn("trace_feedback", feedback.writes)

            draft = process_interaction(
                message="记住这次踩坑，先给我看预览。",
                recent_text="example_service maintainer 排查前先查 live database schema，再看 DAL 和调用链。",
                context=context,
                store=store,
                handoff_store=handoffs,
            )
            self.assertEqual(draft.route.action, "draft_memory")
            self.assertTrue(draft.artifacts["requires_confirmation"])
            self.assertEqual(store.count_memory_cards(), 1)

            confirmed = process_interaction(
                message="确认保存",
                recent_text="",
                context=context,
                store=store,
                handoff_store=handoffs,
            )
            self.assertEqual(confirmed.route.action, "save_memory")
            self.assertIn("memory", confirmed.writes)
            self.assertEqual(
                confirmed.artifacts["pending_draft_id"],
                draft.artifacts["pending_draft_id"],
            )

            activity = build_activity_report(
                store=store,
                handoff_store=handoffs,
                context=context,
            )
            self.assertEqual(activity.action_counts["recall"], 1)
            self.assertEqual(activity.action_counts["draft_memory"], 1)
            self.assertEqual(activity.action_counts["save_memory"], 1)
            self.assertEqual(activity.feedback_counts["useful"], 1)
            self.assertEqual(activity.memory_count, 2)
            self.assertEqual(activity.lifecycle.draft_total, 1)
            self.assertEqual(activity.lifecycle.draft_confirmed, 1)
            self.assertEqual(len(activity.lifecycle.draft_pending), 0)
            self.assertEqual(activity.lifecycle.draft_unconfirmed, 0)
            self.assertEqual(activity.lifecycle.memory_recalled_again, 1)
            self.assertEqual(activity.lifecycle.later_recall_count, 1)
            stdout = StringIO()
            with redirect_stdout(stdout):
                activity_code = main(
                    [
                        "--home",
                        str(home),
                        "activity",
                        "--cwd",
                        str(project),
                        "--json",
                    ]
                )
            activity_payload = json.loads(stdout.getvalue())
            self.assertEqual(activity_code, 0)
            self.assertEqual(activity_payload["lifecycle"]["draft"]["confirmed"], 1)
            self.assertEqual(activity_payload["lifecycle"]["memory_reuse"]["recalled_again"], 1)
            self.assertEqual(_git(project, "status", "--porcelain"), "")

    def test_llm_quality_draft_in_temporary_git_project_keeps_project_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "example_service"
            project.mkdir()
            _git(project, "init")
            _git(project, "config", "user.email", "memagent@example.test")
            _git(project, "config", "user.name", "MemAgent Test")
            (project / "README.md").write_text("# demo\n", encoding="utf-8")
            _git(project, "add", "README.md")
            _git(project, "commit", "-m", "initial")

            home = root / "memagent-home"
            context = detect_context(project)
            store = MemoryStore(home)
            handoffs = HandoffStore(home)
            profile = root / "llm_profiles.json"
            profile.write_text(
                json.dumps(
                    {
                        "profiles": {
                            "demo": {
                                "provider": "openai-compatible",
                                "base_url": "https://api.example.test/v1",
                                "api_key": "test-key",
                                "model": "demo-model",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch("memagent.draft.chat_completion") as chat_completion:
                chat_completion.return_value = json.dumps(
                    {
                        "kind": "preference",
                        "memory_rewrite": "Keep changes scoped to the current task and put optional plans outside service code.",
                        "quality_score": 0.87,
                        "quality_label": "keep",
                        "reasons": ["specific stable preference"],
                    }
                )
                draft = process_interaction(
                    message="记住这个用户习惯，先给我预览。",
                    recent_text="用户习惯：在 example_service 只改当前需求相关代码；默认不新增 docs 或 tasks；方案放到个人笔记目录。",
                    context=context,
                    store=store,
                    handoff_store=handoffs,
                    draft_provider="openai-compatible",
                    draft_llm_profile="demo",
                    draft_llm_config_path=profile,
                )

            self.assertEqual(draft.route.provider, "heuristic")
            self.assertEqual(draft.payload["quality_gate"]["final_source"], "llm_assisted")
            self.assertTrue(draft.artifacts["requires_confirmation"])
            self.assertEqual(store.count_memory_cards(), 0)
            pending = json.loads(Path(draft.artifacts["pending_draft_path"]).read_text(encoding="utf-8"))
            self.assertNotIn("suggested_rewrite", pending["quality_gate"])

            confirmed = process_interaction(
                message="确认保存",
                recent_text="",
                context=context,
                store=store,
                handoff_store=handoffs,
            )
            self.assertEqual(confirmed.route.action, "save_memory")
            self.assertEqual(store.count_memory_cards(), 1)
            self.assertEqual(_git(project, "status", "--porcelain"), "")

    def test_agent_suggestion_in_temporary_git_project_keeps_project_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "example_service"
            project.mkdir()
            _git(project, "init")
            _git(project, "config", "user.email", "memagent@example.test")
            _git(project, "config", "user.name", "MemAgent Test")
            (project / "README.md").write_text("# demo\n", encoding="utf-8")
            _git(project, "add", "README.md")
            _git(project, "commit", "-m", "initial")
            home = root / "memagent-home"
            context = detect_context(project)
            store = MemoryStore(home)
            handoffs = HandoffStore(home)

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
            self.assertEqual(store.count_memory_cards(), 0)
            self.assertEqual(_git(project, "status", "--porcelain"), "")

    def test_automatic_reflection_in_temporary_git_project_keeps_project_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "example_service"
            project.mkdir()
            _git(project, "init")
            _git(project, "config", "user.email", "memagent@example.test")
            _git(project, "config", "user.name", "MemAgent Test")
            (project / "README.md").write_text("# demo\n", encoding="utf-8")
            _git(project, "add", "README.md")
            _git(project, "commit", "-m", "initial")
            store = MemoryStore(root / "memagent-home")
            context = detect_context(project)
            handoffs = HandoffStore(store.home)

            reflected = reflect_on_task(
                summary=(
                    "Two failed attempts relied on a stale generated client. "
                    "Next time verify the live interface before changing the caller."
                ),
                signals=("detour", "correction", "verified_outcome"),
                context=context,
                store=store,
                semantic_mode="heuristic",
            )

            self.assertEqual(reflected.route.action, "draft_memory")
            self.assertTrue(store.has_pending_memory_draft(context=context))
            self.assertEqual(store.count_memory_cards(), 0)
            self.assertEqual(_git(project, "status", "--porcelain"), "")

            rejected = process_interaction(
                message="Don't save this one.",
                recent_text="",
                context=context,
                store=store,
                handoff_store=handoffs,
            )
            self.assertEqual(rejected.route.action, "reject_memory")
            self.assertFalse(store.has_pending_memory_draft(context=context))
            self.assertEqual(_git(project, "status", "--porcelain"), "")


def _git(project: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=project,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    unittest.main()
