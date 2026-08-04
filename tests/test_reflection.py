from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from memagent.context import ProjectContext
from memagent.handoff import HandoffStore
from memagent.interaction import process_interaction, reflect_on_task
from memagent.llm import OpenAICompatibleConfig
from memagent.memory import MemoryStore
from memagent.reflection import assess_reflection, reflection_candidate


class ReflectionTest(unittest.TestCase):
    def test_chinese_reflection_selects_actionable_sentence_without_spaces(self) -> None:
        candidate = reflection_candidate(
            "第一次排查依赖了旧入口。下次先核对实时契约，再修改调用方。"
        )

        self.assertEqual(candidate, "下次先核对实时契约，再修改调用方。")

    def test_public_reflection_fixture(self) -> None:
        cases = json.loads(
            (Path(__file__).parent / "fixtures" / "reflection_cases.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as tmp:
            context = _context(Path(tmp) / "project")
            for case in cases:
                with self.subTest(case=case["name"]):
                    assessment = assess_reflection(
                        case["summary"],
                        signals=tuple(case["signals"]),
                        context=context,
                        semantic_mode="heuristic",
                    )
                    self.assertEqual(assessment.verdict, case["expected"])

    def test_local_reflection_creates_preview_but_not_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")

            result = reflect_on_task(
                summary=(
                    "The first two attempts used an obsolete interface and failed. "
                    "Checking the live contract exposed the correct entrypoint. "
                    "Next time verify the live contract before changing generated code."
                ),
                signals=("detour", "verified_entrypoint", "verified_outcome"),
                context=context,
                store=store,
                semantic_mode="heuristic",
            )

            self.assertEqual(result.route.action, "draft_memory")
            self.assertTrue(result.executed)
            self.assertIn("reflection_trace", result.writes)
            self.assertTrue(store.has_pending_memory_draft(context=context))
            self.assertEqual(store.count_memory_cards(), 0)
            trace = json.loads(Path(result.artifacts["reflection_trace_path"]).read_text(encoding="utf-8"))
            self.assertNotIn("obsolete interface", json.dumps(trace))
            self.assertIn("summary_hash", trace["input"])

            saved = process_interaction(
                message="确认保存",
                recent_text="",
                context=context,
                store=store,
                handoff_store=HandoffStore(store.home),
            )
            self.assertEqual(saved.route.action, "save_memory")
            self.assertEqual(store.count_memory_cards(), 1)

    def test_weak_reflection_abstains_quietly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            result = reflect_on_task(
                summary="A spelling error caused one compile failure, then the edit worked normally.",
                signals=("detour",),
                context=_context(root / "project"),
                store=store,
                semantic_mode="heuristic",
            )

            self.assertEqual(result.route.action, "none")
            self.assertFalse(result.executed)
            self.assertEqual(store.count_memory_cards(), 0)
            self.assertEqual(len(list(store.reflection_traces_dir.glob("*.json"))), 1)

    def test_same_session_allows_at_most_one_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"CODEX_THREAD_ID": "private-session-value"},
            clear=False,
        ):
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")
            first = reflect_on_task(
                summary="A costly detour ended after verifying the live schema. Next time inspect the live schema before changing the query.",
                signals=("detour", "costly_investigation", "verified_outcome"),
                context=context,
                store=store,
            )
            second = reflect_on_task(
                summary="A user correction showed the generated client was stale. Next time verify the interface before editing the caller.",
                signals=("correction", "verified_entrypoint", "verified_outcome"),
                context=context,
                store=store,
            )

            self.assertEqual(first.route.action, "draft_memory")
            self.assertEqual(second.route.action, "none")
            self.assertEqual(second.artifacts["status"], "session_limit")
            runtime = (store.home / "runtime" / "reflection_sessions.json").read_text(encoding="utf-8")
            self.assertNotIn("private-session-value", runtime)

    def test_duplicate_is_suppressed_before_optional_llm_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "memagent.reflection.chat_completion"
        ) as completion:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            context = _context(root / "project")
            store.remember(
                text="Verify the live interface before changing the generated client.",
                topic="Generated client interface verification",
                domain="coding",
                kind="verification",
                repo=context.repo_name,
                module=None,
                triggers=["live interface", "generated client"],
                exportable=False,
            )

            result = reflect_on_task(
                summary=(
                    "The first path failed and required a broader investigation. "
                    "Verify the live interface before changing the generated client."
                ),
                signals=("detour", "workflow"),
                context=context,
                store=store,
                semantic_mode="hybrid",
            )

        self.assertEqual(result.route.action, "none")
        self.assertEqual(result.artifacts["status"], "duplicate")
        completion.assert_not_called()

    def test_hybrid_uses_llm_only_for_ambiguous_reflection_and_sanitizes_input(self) -> None:
        captured: dict[str, object] = {}

        def fake_completion(*, config: OpenAICompatibleConfig, messages: list[dict[str, str]]) -> str:
            captured["messages"] = messages
            return json.dumps(
                {
                    "worth_remembering": True,
                    "score": 0.81,
                    "lesson": "Verify the live contract before relying on generated code.",
                    "reason": "The correction is reusable and verified.",
                }
            )

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "memagent.reflection.OpenAICompatibleConfig.from_default_profile",
            return_value=OpenAICompatibleConfig(
                base_url="https://example.test/v1",
                api_key="test-key",
                model="test-model",
                timeout_seconds=3,
            ),
        ), mock.patch("memagent.reflection.chat_completion", side_effect=fake_completion):
            root = Path(tmp)
            assessment = assess_reflection(
                "The failed query in /Users/demo/private_repo used customer_order_table_2026 and request 123456789. Verify the live contract next time.",
                signals=("detour", "workflow"),
                context=_context(root / "project"),
                semantic_mode="hybrid",
                state_home=root / "home",
            )

        self.assertTrue(assessment.should_suggest)
        self.assertEqual(assessment.provider, "llm_assisted")
        sent = json.dumps(captured["messages"], ensure_ascii=False)
        self.assertNotIn("/Users/demo/private_repo", sent)
        self.assertNotIn("customer_order_table_2026", sent)
        self.assertNotIn("123456789", sent)

    def test_llm_reflection_uses_one_call_then_builds_preview_locally(self) -> None:
        response = json.dumps(
            {
                "worth_remembering": True,
                "score": 0.84,
                "lesson": "Verify the live contract before changing generated code.",
                "reason": "The verified correction is reusable.",
            }
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "memagent.reflection.OpenAICompatibleConfig.from_default_profile",
            return_value=OpenAICompatibleConfig(
                base_url="https://example.test/v1",
                api_key="test-key",
                model="test-model",
                timeout_seconds=3,
            ),
        ), mock.patch("memagent.reflection.chat_completion", return_value=response) as completion:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            result = reflect_on_task(
                summary="A stale client caused a failed path. The live contract verified the correction.",
                signals=("correction", "verified_outcome"),
                context=_context(root / "project"),
                store=store,
                semantic_mode="llm",
            )

        self.assertEqual(result.route.action, "draft_memory")
        self.assertEqual(result.payload["provider"], "heuristic")
        self.assertEqual(completion.call_count, 1)

    def test_hybrid_provider_failure_abstains_for_ambiguous_reflection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "memagent.reflection.OpenAICompatibleConfig.from_default_profile",
            return_value=OpenAICompatibleConfig(
                base_url="https://example.test/v1",
                api_key="test-key",
                model="test-model",
                timeout_seconds=3,
            ),
        ), mock.patch("memagent.reflection.chat_completion", side_effect=ValueError("timed out")):
            root = Path(tmp)
            assessment = assess_reflection(
                "The first query failed, and checking the live contract fixed it. Verify that contract first next time.",
                signals=("detour", "workflow"),
                context=_context(root / "project"),
                semantic_mode="hybrid",
                state_home=root / "home",
            )

        self.assertFalse(assessment.should_suggest)
        self.assertTrue(assessment.gate.fallback)
        self.assertEqual(assessment.gate.failure_kind, "timeout")

    def test_two_reflection_failures_enter_shared_gate_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "memagent.reflection.OpenAICompatibleConfig.from_default_profile",
            return_value=OpenAICompatibleConfig(
                base_url="https://example.test/v1",
                api_key="test-key",
                model="test-model",
                timeout_seconds=3,
            ),
        ), mock.patch(
            "memagent.reflection.chat_completion",
            side_effect=ValueError("timed out"),
        ) as completion:
            root = Path(tmp)
            kwargs = {
                "summary": "A broad failed path might be replaced by a focused validation workflow next time.",
                "signals": ("detour", "workflow"),
                "context": _context(root / "project"),
                "semantic_mode": "hybrid",
                "state_home": root / "home",
            }
            first = assess_reflection(**kwargs)
            second = assess_reflection(**kwargs)
            third = assess_reflection(**kwargs)

        self.assertTrue(first.gate.attempted)
        self.assertTrue(second.gate.attempted)
        self.assertTrue(third.gate.skipped_due_to_cooldown)
        self.assertEqual(completion.call_count, 2)


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
