from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from memagent.context import ProjectContext
from memagent.handoff import HandoffStore
from memagent.interaction import PROCESS_SCHEMA_VERSION, process_interaction
from memagent.memory import MemoryStore


class InteractionProcessTest(unittest.TestCase):
    def test_process_recall_saves_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")
            store.remember(
                text="Use live RDS schema before audit_rule_lib owner debugging.",
                topic="audit_rule_lib live schema",
                domain="coding",
                kind="data_entrypoint",
                repo=context.repo_name,
                module=None,
                triggers=["audit_rule_lib", "owner", "RDS"],
                exportable=False,
            )

            result = process_interaction(
                message="帮我排查 audit_rule_lib 的 owner 问题，先按你觉得最省时间的方式来。",
                recent_text="",
                context=context,
                store=store,
                handoff_store=HandoffStore(store.home),
            )

            self.assertEqual(result.route.action, "recall")
            self.assertTrue(result.executed)
            self.assertIn("recall_trace", result.writes)
            self.assertIn("process_trace", result.writes)
            self.assertIn("trace_id", result.artifacts)
            self.assertIn("process_trace_id", result.artifacts)
            trace_payload = store.load_process_trace(result.artifacts["process_trace_id"])
            self.assertEqual(trace_payload["schema_version"], "memagent.process_trace.v1")
            self.assertEqual(trace_payload["process"]["route"]["action"], "recall")
            self.assertEqual(result.to_payload(context=context)["schema_version"], PROCESS_SCHEMA_VERSION)

    def test_process_draft_memory_does_not_write_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")

            result = process_interaction(
                message="这个入口下次别忘了",
                recent_text="bytedcli rds db table schema demo_db demo_table --region cn",
                context=context,
                store=store,
                handoff_store=HandoffStore(store.home),
            )

            self.assertEqual(result.route.action, "draft_memory")
            self.assertTrue(result.executed)
            self.assertEqual(result.writes, ("process_trace",))
            self.assertEqual(result.artifacts["requires_confirmation"], True)
            self.assertIn("process_trace_path", result.artifacts)
            self.assertEqual(store.count_memory_cards(), 0)

    def test_process_feedback_labels_latest_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")
            saved = store.save_recall_trace(
                {
                    "schema_version": "memagent.recall.v1",
                    "query": "owner",
                    "context": {"repo_name": context.repo_name},
                    "total_matches": 1,
                    "matches": [{"title": "Owner memory"}],
                    "text": "[MemAgent recalled context]",
                },
                source="test",
            )

            result = process_interaction(
                message="刚刚那条提醒有用。",
                recent_text="",
                context=context,
                store=store,
                handoff_store=HandoffStore(store.home),
            )

            self.assertEqual(result.route.action, "label_feedback")
            self.assertIn("trace_feedback", result.writes)
            self.assertIn("process_trace", result.writes)
            self.assertEqual(result.artifacts["trace_id"], saved.identifier)
            payload = store.load_recall_trace(saved.identifier)
            self.assertEqual(payload["feedback"]["rating"], "useful")

    def test_process_handoff_save_writes_latest_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")

            result = process_interaction(
                message="先到这，下次继续时接上。",
                recent_text="\n".join(
                    [
                        "## Summary",
                        "MemAgent wrapper now runs process-first preflight.",
                        "## Done",
                        "- Added LLM profile support.",
                        "## Next Steps",
                        "- Run completion audit.",
                    ]
                ),
                context=context,
                store=store,
                handoff_store=HandoffStore(store.home),
            )

            self.assertEqual(result.route.action, "handoff_save")
            self.assertTrue(result.executed)
            self.assertIn("handoff", result.writes)
            self.assertIn("process_trace", result.writes)
            self.assertIn("latest_path", result.artifacts)
            self.assertTrue(Path(result.artifacts["latest_path"]).exists())

    def test_process_handoff_show_reads_latest_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")
            handoff_store = HandoffStore(store.home)
            handoff_store.save(
                context=context,
                topic="Process handoff",
                summary="MemAgent natural interaction processor is ready.",
                done=["Added recall, draft memory, and feedback process actions."],
                next_steps=["Verify handoff process actions."],
                open_questions=[],
                memory_candidates=[],
            )

            result = process_interaction(
                message="继续上次做到哪了？",
                recent_text="",
                context=context,
                store=store,
                handoff_store=handoff_store,
            )

            self.assertEqual(result.route.action, "handoff_show")
            self.assertTrue(result.executed)
            self.assertEqual(result.writes, ("process_trace",))
            self.assertIn("Process handoff", result.result_text)
            self.assertIn("Verify handoff process actions.", result.result_text)

    def test_process_no_write_disables_process_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")

            result = process_interaction(
                message="解释一下这个函数现在的分支逻辑。",
                recent_text="",
                context=context,
                store=store,
                handoff_store=HandoffStore(store.home),
                allow_writes=False,
            )

            self.assertEqual(result.route.action, "none")
            self.assertEqual(result.writes, ())
            self.assertFalse(store.process_traces_dir.exists())


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
