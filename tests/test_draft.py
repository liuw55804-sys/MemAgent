from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from memagent.draft import MEMORY_DRAFT_SCHEMA_VERSION, draft_memory, render_memory_draft


class MemoryDraftTest(unittest.TestCase):
    def test_draft_memory_keeps_tool_entrypoint(self) -> None:
        draft = draft_memory(
            "这个 git 查 live schema 的入口下次别忘了："
            "git database db table schema example_rule example_task --region cn。"
            "排查 example_service 前先以 live schema 为准。"
        )

        self.assertEqual(draft.kind, "data_entrypoint")
        self.assertEqual(draft.quality_label, "keep")
        self.assertIn("git", draft.triggers)
        self.assertIn("live schema", draft.memory)

        payload = draft.to_payload()
        self.assertEqual(payload["schema_version"], MEMORY_DRAFT_SCHEMA_VERSION)
        self.assertTrue(payload["requires_confirmation"])
        self.assertEqual(payload["suggested_remember"]["kind"], "data_entrypoint")

    def test_draft_memory_rejects_generic_note(self) -> None:
        draft = draft_memory("今天聊得不错。")

        self.assertEqual(draft.quality_label, "reject")
        self.assertIn("no strong reusable workflow signal detected", draft.warnings)

    def test_render_memory_draft_shows_command(self) -> None:
        draft = draft_memory("沉淀一下：go test ./... 可以验证这个改动。")
        rendered = render_memory_draft(draft)

        self.assertIn("[MemAgent memory draft]", rendered)
        self.assertIn("[Suggested remember command]", rendered)
        self.assertIn("memagent remember", rendered)

    def test_openai_compatible_quality_gate_corrects_preference_and_redacts_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _profile_config(Path(tmp))
            with mock.patch("memagent.draft.chat_completion") as chat_completion:
                chat_completion.return_value = json.dumps(
                    {
                        "kind": "preference",
                        "memory_rewrite": "Keep changes scoped to the current task and place optional notes outside service code.",
                        "quality_score": 0.86,
                        "quality_label": "keep",
                        "reasons": ["stable user working preference"],
                    }
                )
                draft = draft_memory(
                    "用户习惯：在 example_service 只修改当前需求相关代码，默认不新增 docs/tasks。"
                    "方案优先放 /tmp/example-project，token=example-secret-value，"
                    "表 example_task 的原始样本不发送。",
                    provider="openai-compatible",
                    llm_profile="demo",
                    llm_config_path=config_path,
                )

        config = chat_completion.call_args.kwargs["config"]
        self.assertEqual(config.base_url, "https://api.example.test/v1")
        self.assertEqual(config.model, "demo-model")
        self.assertEqual(draft.provider, "openai-compatible")
        self.assertEqual(draft.kind, "preference")
        self.assertEqual(draft.quality_label, "keep")
        self.assertEqual(draft.quality_gate.final_source, "llm_assisted")
        prompt = chat_completion.call_args.kwargs["messages"][1]["content"]
        self.assertNotIn("example-secret-value", prompt)
        self.assertNotIn("/tmp/example-project", prompt)
        self.assertNotIn("example_task", prompt)
        self.assertIn("<secret>", prompt)
        self.assertIn("<path>", prompt)
        self.assertIn("<identifier>", prompt)

    def test_openai_quality_gate_falls_back_on_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _profile_config(Path(tmp))
            with mock.patch("memagent.draft.chat_completion", return_value="not-json"):
                draft = draft_memory(
                    "用户习惯：默认只修改当前需求相关代码。",
                    provider="openai-compatible",
                    llm_profile="demo",
                    llm_config_path=config_path,
                )

        self.assertEqual(draft.kind, "preference")
        self.assertTrue(draft.quality_gate.fallback)
        self.assertEqual(draft.quality_gate.final_source, "heuristic_fallback")
        self.assertTrue(any("LLM quality gate unavailable" in warning for warning in draft.warnings))

    def test_openai_quality_gate_falls_back_when_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=True):
                draft = draft_memory(
                    "用户习惯：默认只修改当前需求相关代码。",
                    provider="openai-compatible",
                    llm_config_path=Path(tmp) / "missing.json",
                )

        self.assertEqual(draft.provider, "heuristic")
        self.assertTrue(draft.quality_gate.fallback)
        self.assertEqual(draft.quality_gate.final_source, "heuristic_fallback")

    def test_openai_quality_gate_skips_obvious_tool_recipe(self) -> None:
        with mock.patch("memagent.draft.chat_completion") as chat_completion:
            draft = draft_memory(
                "git database db table schema demo_db demo_table --region cn。"
                "排查前先执行这个命令，再看 live schema。",
                provider="openai-compatible",
            )

        self.assertEqual(draft.quality_gate.final_source, "heuristic_skipped")
        self.assertFalse(draft.quality_gate.attempted)
        chat_completion.assert_not_called()


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
