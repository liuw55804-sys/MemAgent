from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from memagent.activity import build_activity_report
from memagent.codex_skill import build_user_codex_skill_plan, write_user_codex_skill_plan
from memagent.context import detect_context
from memagent.handoff import HandoffStore
from memagent.interaction import process_interaction
from memagent.memory import MemoryStore


class ZeroIntrusionFlowTest(unittest.TestCase):
    def test_project_without_agents_md_keeps_git_clean_through_memory_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "audit_rule_lib"
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
                text="Check the live RDS schema before tracing an audit_rule_lib owner issue.",
                topic="audit_rule_lib live schema",
                domain="coding",
                kind="data_entrypoint",
                repo=context.repo_name,
                module=None,
                triggers=["audit_rule_lib", "owner", "schema"],
                exportable=False,
            )

            recalled = process_interaction(
                message="之前 audit_rule_lib owner 问题怎么查？先按靠谱路径来。",
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
                recent_text="audit_rule_lib owner 排查前先查 live RDS schema，再看 DAL 和调用链。",
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
