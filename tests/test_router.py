from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from memagent.llm import configure_semantic_mode
from memagent.router import ROUTE_SCHEMA_VERSION, route_interaction


class RouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.semantic_mode = mock.patch.dict(
            os.environ,
            {"MEMAGENT_SEMANTIC_MODE": "heuristic"},
        )
        self.semantic_mode.start()
        self.addCleanup(self.semantic_mode.stop)

    def test_routes_task_start_recall(self) -> None:
        decision = route_interaction("帮我排查 example_service 里 workflow task maintainer 相关问题，先按你觉得最省时间的方式来。")

        self.assertEqual(decision.action, "recall")
        self.assertGreaterEqual(decision.confidence, 0.7)
        self.assertIn("maintainer", decision.signals)
        self.assertIn("example_service", decision.query or "")

    def test_routes_question_about_prior_user_development_habits_to_recall(self) -> None:
        decision = route_interaction("你知道用户之前的开发习惯吗")

        self.assertEqual(decision.action, "recall")
        self.assertIn("user_preference", decision.signals)
        self.assertEqual(decision.query, "你知道用户之前的开发习惯吗")

    def test_routes_memory_draft_with_confirmation(self) -> None:
        decision = route_interaction(
            "这个 git 查 live schema 的入口下次别忘了。",
            recent_text="git database db table schema demo_db demo_table --region cn",
        )

        self.assertEqual(decision.action, "draft_memory")
        self.assertTrue(decision.requires_confirmation)
        self.assertTrue(decision.recent_text_used)
        self.assertIn("下次别忘", decision.signals)

    def test_explicit_memory_capture_outranks_recall_signals(self) -> None:
        decision = route_interaction(
            "请记住：以后排查接口问题先查 live schema。",
            recent_text="For interface debugging, inspect the live schema first.",
        )

        self.assertEqual(decision.action, "draft_memory")

    def test_natural_reusable_constraint_draft_routes_to_memory(self) -> None:
        decision = route_interaction("请生成一条可复用的协作约束草稿。")

        self.assertEqual(decision.action, "draft_memory")

    def test_routes_feedback_label(self) -> None:
        decision = route_interaction("刚刚那条没帮上忙。", has_recent_trace=True)

        self.assertEqual(decision.action, "label_feedback")
        self.assertEqual(decision.feedback_rating, "not-useful")
        self.assertTrue(decision.requires_recent_trace)

    def test_routes_short_positive_feedback_label(self) -> None:
        decision = route_interaction("刚刚那条有用。", has_recent_trace=True)

        self.assertEqual(decision.action, "label_feedback")
        self.assertEqual(decision.feedback_rating, "useful")

    def test_routes_confirmation_only_with_pending_draft(self) -> None:
        decision = route_interaction("确认保存", has_pending_draft=True)

        self.assertEqual(decision.action, "save_memory")
        self.assertTrue(decision.requires_pending_draft)
        self.assertEqual(route_interaction("确认保存", has_pending_draft=False).action, "none")

    def test_routes_memory_rejection_only_with_pending_draft(self) -> None:
        decision = route_interaction("这条不用记了", has_pending_draft=True)

        self.assertEqual(decision.action, "reject_memory")
        self.assertTrue(decision.requires_pending_draft)
        self.assertEqual(route_interaction("这条不用记了", has_pending_draft=False).action, "none")

    def test_routes_handoff_save(self) -> None:
        decision = route_interaction("先到这，下次继续时帮我接上。")

        self.assertEqual(decision.action, "handoff_save")
        self.assertIn("先到这", decision.signals)

    def test_routes_handoff_show(self) -> None:
        decision = route_interaction("上次做到哪？")

        self.assertEqual(decision.action, "handoff_show")

    def test_routes_developer_eval(self) -> None:
        decision = route_interaction("给我生成 MemAgent 这轮自测的质量报告，包含 trace eval 和 replay。")

        self.assertEqual(decision.action, "developer_eval")
        self.assertTrue(decision.developer_mode)

    def test_payload_schema(self) -> None:
        payload = route_interaction("改个 typo").to_payload()

        self.assertEqual(payload["schema_version"], ROUTE_SCHEMA_VERSION)
        self.assertEqual(payload["action"], "none")
        self.assertIn("confidence", payload)

    def test_openai_compatible_route_uses_profile_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _profile_config(Path(tmp))
            with mock.patch("memagent.router.chat_completion") as chat_completion:
                chat_completion.return_value = json.dumps(
                    {
                        "action": "none",
                        "confidence": 0.2,
                        "reason": "No memory action.",
                        "signals": [],
                        "query": None,
                        "feedback_rating": None,
                        "requires_confirmation": False,
                        "requires_recent_trace": False,
                        "developer_mode": False,
                        "suggested_next": "Continue.",
                        "recent_text_used": False,
                    }
                )
                decision = route_interaction(
                    "普通问题",
                    provider="openai-compatible",
                    llm_profile="demo",
                    llm_config_path=config_path,
                )

        config = chat_completion.call_args.kwargs["config"]
        self.assertEqual(config.base_url, "https://api.example.test/v1")
        self.assertEqual(config.model, "demo-model")
        self.assertEqual(decision.provider, "openai-compatible")

    def test_hybrid_falls_back_when_provider_is_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {}, clear=True):
                decision = route_interaction(
                    "Can you continue the investigation from last time?",
                    semantic_mode="hybrid",
                    llm_config_path=Path(tmp) / "missing.json",
                )

        self.assertEqual(decision.action, "none")
        self.assertEqual(decision.provider, "heuristic_fallback")

    def test_hybrid_uses_llm_recall_estimator_for_ambiguous_preference_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _profile_config(Path(tmp))
            with mock.patch("memagent.router.chat_completion") as chat_completion:
                chat_completion.return_value = json.dumps(
                    {
                        "recall_likelihood": 0.91,
                        "reason": "The question asks about a prior working preference.",
                        "signals": ["prior_preference"],
                    }
                )
                decision = route_interaction(
                    "Do you know the user's previous coding preferences for /tmp/private-project token=example-secret-value?",
                    semantic_mode="hybrid",
                    llm_profile="demo",
                    llm_config_path=config_path,
                )

        self.assertEqual(decision.action, "recall")
        self.assertEqual(decision.provider, "llm_recall_estimator")
        self.assertEqual(decision.recall_likelihood, 0.91)
        prompt = json.loads(chat_completion.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(set(prompt), {"user_message", "context"})
        self.assertNotIn("recent_text", prompt)
        self.assertNotIn("memory", json.dumps(prompt))
        self.assertNotIn("/tmp/private-project", prompt["user_message"])
        self.assertNotIn("example-secret-value", prompt["user_message"])
        self.assertIn("<path>", prompt["user_message"])
        self.assertIn("<secret>", prompt["user_message"])

    def test_hybrid_llm_recall_estimator_can_decline_recall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _profile_config(Path(tmp))
            with mock.patch("memagent.router.chat_completion") as chat_completion:
                chat_completion.return_value = json.dumps(
                    {
                        "recall_likelihood": 0.08,
                        "reason": "This is a self-contained request.",
                        "signals": ["self_contained"],
                    }
                )
                decision = route_interaction(
                    "Explain this function's return value.",
                    semantic_mode="hybrid",
                    llm_profile="demo",
                    llm_config_path=config_path,
                )

        self.assertEqual(decision.action, "none")
        self.assertEqual(decision.provider, "llm_recall_estimator")
        self.assertEqual(decision.recall_likelihood, 0.08)

    def test_hybrid_estimator_uses_configured_default_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            configure_semantic_mode(
                mode="hybrid",
                base_url="http://127.0.0.1:1234/v1",
                model="local-model",
                allow_no_key=True,
                config_path=config_path,
            )
            with mock.patch("memagent.router.chat_completion") as chat_completion:
                chat_completion.return_value = json.dumps(
                    {
                        "recall_likelihood": 0.75,
                        "reason": "Prior workflow context may help.",
                        "signals": ["prior_workflow"],
                    }
                )
                decision = route_interaction(
                    "Can you continue from the previous investigation?",
                    semantic_mode="hybrid",
                    llm_config_path=config_path,
                )

        self.assertEqual(decision.provider, "llm_recall_estimator")
        self.assertEqual(chat_completion.call_args.kwargs["config"].model, "local-model")

    def test_llm_router_payload_is_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _profile_config(Path(tmp))
            with mock.patch("memagent.router.chat_completion") as chat_completion:
                chat_completion.return_value = json.dumps(
                    {
                        "action": "none", "confidence": 0.2, "reason": "No memory action.",
                        "signals": [], "query": None, "feedback_rating": None,
                        "requires_confirmation": False, "requires_recent_trace": False,
                        "developer_mode": False, "suggested_next": "Continue.", "recent_text_used": False,
                    }
                )
                route_interaction(
                    "inspect /tmp/private-work token=example-secret-value for example_identifier_42",
                    recent_text="https://example.test/private payload",
                    provider="openai-compatible",
                    llm_profile="demo",
                    llm_config_path=config_path,
                )

        prompt = chat_completion.call_args.kwargs["messages"][1]["content"]
        self.assertNotIn("/tmp/private-work", prompt)
        self.assertNotIn("example-secret-value", prompt)
        self.assertNotIn("example_identifier_42", prompt)
        self.assertNotIn("https://example.test", prompt)
        self.assertIn("<secret>", prompt)
        self.assertIn("<path>", prompt)


def _profile_config(root: Path) -> Path:
    path = root / "llm_profiles.json"
    path.write_text(
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
    return path


if __name__ == "__main__":
    unittest.main()
