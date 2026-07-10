from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from memagent.router import ROUTE_SCHEMA_VERSION, route_interaction


class RouterTest(unittest.TestCase):
    def test_routes_task_start_recall(self) -> None:
        decision = route_interaction("帮我排查 audit_rule_lib 里 governance task owner 相关问题，先按你觉得最省时间的方式来。")

        self.assertEqual(decision.action, "recall")
        self.assertGreaterEqual(decision.confidence, 0.7)
        self.assertIn("audit_rule_lib", decision.signals)
        self.assertIn("owner", decision.signals)
        self.assertIn("audit_rule_lib", decision.query or "")

    def test_routes_memory_draft_with_confirmation(self) -> None:
        decision = route_interaction(
            "这个 bytedcli 查 live schema 的入口下次别忘了。",
            recent_text="bytedcli rds db table schema demo_db demo_table --region cn",
        )

        self.assertEqual(decision.action, "draft_memory")
        self.assertTrue(decision.requires_confirmation)
        self.assertTrue(decision.recent_text_used)
        self.assertIn("下次别忘", decision.signals)

    def test_routes_feedback_label(self) -> None:
        decision = route_interaction("刚刚那条没帮上忙。", has_recent_trace=True)

        self.assertEqual(decision.action, "label_feedback")
        self.assertEqual(decision.feedback_rating, "not-useful")
        self.assertTrue(decision.requires_recent_trace)

    def test_routes_short_positive_feedback_label(self) -> None:
        decision = route_interaction("刚刚那条有用。", has_recent_trace=True)

        self.assertEqual(decision.action, "label_feedback")
        self.assertEqual(decision.feedback_rating, "useful")

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
