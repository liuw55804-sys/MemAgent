from __future__ import annotations

import json
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
                text="Use live database schema before example_service maintainer debugging.",
                topic="example_service live schema",
                domain="coding",
                kind="data_entrypoint",
                repo=context.repo_name,
                module=None,
                triggers=["example_service", "maintainer", "database"],
                exportable=False,
            )

            result = process_interaction(
                message="帮我排查 example_service 的 maintainer 问题，先按你觉得最省时间的方式来。",
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

    def test_process_recalls_project_scoped_user_preference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")
            preference = "Only edit files needed for the request; do not add project documentation unless asked."
            store.remember(
                text=preference,
                topic="Project editing preference",
                domain="coding",
                kind="preference",
                repo=context.repo_name,
                module=None,
                triggers=["user preference", "documentation"],
                exportable=False,
            )

            result = process_interaction(
                message="你知道用户之前的开发习惯吗",
                recent_text="",
                context=context,
                store=store,
                handoff_store=HandoffStore(store.home),
            )

            self.assertEqual(result.route.action, "recall")
            self.assertTrue(result.executed)
            self.assertIn(preference, result.result_text)
            self.assertIn("recall_trace", result.writes)
            self.assertIn("preference", result.artifacts["retrieval_hints"])

    def test_process_draft_memory_does_not_write_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")

            result = process_interaction(
                message="这个入口下次别忘了",
                recent_text="git database db table schema demo_db demo_table --region cn",
                context=context,
                store=store,
                handoff_store=HandoffStore(store.home),
            )

            self.assertEqual(result.route.action, "draft_memory")
            self.assertTrue(result.executed)
            self.assertEqual(result.writes, ("pending_memory_draft", "process_trace"))
            self.assertEqual(result.artifacts["requires_confirmation"], True)
            self.assertTrue(store.has_pending_memory_draft(context=context))
            self.assertIn("process_trace_path", result.artifacts)
            self.assertEqual(store.count_memory_cards(), 0)
            trace_payload = store.load_process_trace(result.artifacts["process_trace_id"])
            traced_draft = trace_payload["process"]["payload"]
            self.assertNotIn("source_excerpt", traced_draft)
            self.assertIn("quality_gate", traced_draft)
            self.assertNotIn("suggested_rewrite", traced_draft["quality_gate"])
            pending_payload = json.loads(Path(result.artifacts["pending_draft_path"]).read_text(encoding="utf-8"))
            self.assertIn("quality_gate", pending_payload)
            self.assertNotIn("suggested_rewrite", pending_payload["quality_gate"] or {})

    def test_process_confirmation_saves_pending_memory_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")
            handoffs = HandoffStore(store.home)
            draft = process_interaction(
                message="这个入口下次别忘了",
                recent_text="Before maintainer diagnosis, check the live database schema first.",
                context=context,
                store=store,
                handoff_store=handoffs,
            )
            self.assertEqual(draft.route.action, "draft_memory")
            self.assertTrue(store.has_pending_memory_draft(context=context))

            saved = process_interaction(
                message="确认保存",
                recent_text="",
                context=context,
                store=store,
                handoff_store=handoffs,
            )

            self.assertEqual(saved.route.action, "save_memory")
            self.assertTrue(saved.executed)
            self.assertIn("memory", saved.writes)
            self.assertFalse(store.has_pending_memory_draft(context=context))
            self.assertEqual(store.count_memory_cards(), 1)

    def test_agent_suggestion_requires_confirmation_and_records_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")
            handoffs = HandoffStore(store.home)

            draft = process_interaction(
                message="The agent found a reusable lesson.",
                recent_text="When the generated client disagrees with old notes, verify the live interface definition first.",
                context=context,
                store=store,
                handoff_store=handoffs,
                agent_suggested=True,
                suggestion_evidence="correction",
            )

            self.assertEqual(draft.route.action, "draft_memory")
            self.assertTrue(store.has_pending_memory_draft(context=context))
            self.assertEqual(store.count_memory_cards(), 0)
            pending = store.load_pending_memory_draft(context=context)
            self.assertEqual(pending["pending"]["source"], "agent_suggested")
            self.assertEqual(pending["pending"]["evidence"], "correction")
            self.assertIn("process_trace", draft.writes)

            saved = process_interaction(
                message="确认保存",
                recent_text="",
                context=context,
                store=store,
                handoff_store=handoffs,
            )

            self.assertEqual(saved.artifacts["source"], "agent_suggested")
            self.assertTrue(saved.artifacts["user_confirmed"])
            self.assertEqual(store.count_memory_cards(), 1)

    def test_agent_suggestion_can_be_rejected_and_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")
            handoffs = HandoffStore(store.home)
            process_interaction(
                message="The agent found a reusable lesson.",
                recent_text="Inspect the live interface definition before changing the generated client.",
                context=context,
                store=store,
                handoff_store=handoffs,
                agent_suggested=True,
                suggestion_evidence="verified_entrypoint",
            )

            rejected = process_interaction(
                message="这条不用记了",
                recent_text="",
                context=context,
                store=store,
                handoff_store=handoffs,
            )

            self.assertEqual(rejected.route.action, "reject_memory")
            self.assertTrue(rejected.artifacts["user_rejected"])
            self.assertEqual(rejected.artifacts["source"], "agent_suggested")
            self.assertFalse(store.has_pending_memory_draft(context=context))
            self.assertEqual(store.count_memory_cards(), 0)

    def test_agent_suggestion_skips_when_preview_is_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")
            handoffs = HandoffStore(store.home)
            kwargs = {
                "message": "The agent found a reusable lesson.",
                "context": context,
                "store": store,
                "handoff_store": handoffs,
                "agent_suggested": True,
                "suggestion_evidence": "detour",
            }
            process_interaction(recent_text="Verify the live schema before debugging generated queries.", **kwargs)
            second = process_interaction(recent_text="Start from the interface definition before tracing the handler.", **kwargs)

            self.assertEqual(second.route.action, "none")
            self.assertEqual(second.artifacts["status"], "pending_exists")
            self.assertIn("process_trace", second.writes)

    def test_agent_suggestion_deduplicates_highly_similar_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")
            store.remember(
                text="Verify the live interface definition before changing the generated client.",
                topic="Generated client interface verification",
                domain="coding",
                kind="verification",
                repo=context.repo_name,
                module=None,
                triggers=["generated client", "interface definition"],
                exportable=False,
            )

            result = process_interaction(
                message="The agent found a reusable lesson.",
                recent_text="Verify the live interface definition before changing the generated client.",
                context=context,
                store=store,
                handoff_store=HandoffStore(store.home),
                agent_suggested=True,
                suggestion_evidence="verified_entrypoint",
            )

            self.assertEqual(result.route.action, "none")
            self.assertEqual(result.artifacts["status"], "duplicate")
            self.assertFalse(store.has_pending_memory_draft(context=context))
            self.assertEqual(store.count_memory_cards(), 1)

    def test_process_feedback_labels_latest_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")
            saved = store.save_recall_trace(
                {
                    "schema_version": "memagent.recall.v1",
                    "query": "maintainer",
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

    def test_process_none_does_not_save_trace_by_default(self) -> None:
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
            )

            self.assertEqual(result.route.action, "none")
            self.assertEqual(result.writes, ())
            self.assertFalse(store.process_traces_dir.exists())

    def test_process_trace_none_saves_noop_trace_for_debug(self) -> None:
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
                trace_none=True,
            )

            self.assertEqual(result.route.action, "none")
            self.assertEqual(result.writes, ("process_trace",))
            payload = store.load_process_trace(result.artifacts["process_trace_id"])
            self.assertEqual(payload["process"]["route"]["action"], "none")

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
                trace_none=True,
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
