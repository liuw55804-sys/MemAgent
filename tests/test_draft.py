from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from memagent.draft import MEMORY_DRAFT_SCHEMA_VERSION, draft_memory, render_memory_draft


class MemoryDraftTest(unittest.TestCase):
    def test_draft_memory_keeps_tool_entrypoint(self) -> None:
        draft = draft_memory(
            "这个 bytedcli 查 live schema 的入口下次别忘了："
            "bytedcli rds db table schema governance_audit_rule t_governance_task --region cn。"
            "排查 audit_rule_lib 前先以 live schema 为准。"
        )

        self.assertEqual(draft.kind, "data_entrypoint")
        self.assertEqual(draft.quality_label, "keep")
        self.assertIn("bytedcli", draft.triggers)
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

    def test_openai_compatible_draft_uses_profile_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _profile_config(Path(tmp))
            with mock.patch("memagent.draft.chat_completion") as chat_completion:
                chat_completion.return_value = json.dumps(
                    {
                        "topic": "demo topic",
                        "kind": "tool_recipe",
                        "triggers": ["demo"],
                        "memory": "Use demo command before debugging.",
                        "quality_score": 0.8,
                        "quality_label": "keep",
                        "reasons": ["reusable"],
                        "warnings": [],
                    }
                )
                draft = draft_memory(
                    "这个 demo command 下次别忘了",
                    provider="openai-compatible",
                    llm_profile="demo",
                    llm_config_path=config_path,
                )

        config = chat_completion.call_args.kwargs["config"]
        self.assertEqual(config.base_url, "https://api.example.test/v1")
        self.assertEqual(config.model, "demo-model")
        self.assertEqual(draft.provider, "openai-compatible")
        self.assertEqual(draft.quality_label, "keep")


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
