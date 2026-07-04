from __future__ import annotations

import unittest

from memagent.cli import normalize_remainder
from memagent.interaction import ProcessResult
from memagent.router import RouteDecision
from memagent.wrapper import build_augmented_prompt
from memagent.wrapper import process_result_context_for_prompt


class WrapperTest(unittest.TestCase):
    def test_build_augmented_prompt(self) -> None:
        prompt = build_augmented_prompt("continue debugging", "[MemAgent recalled context]\n- use id ranges")
        self.assertIn("[MemAgent recalled context]", prompt)
        self.assertIn("[User task]\ncontinue debugging", prompt)

    def test_build_augmented_prompt_without_memory(self) -> None:
        self.assertEqual(build_augmented_prompt("continue debugging", ""), "continue debugging")

    def test_build_augmented_prompt_ignores_blank_memory(self) -> None:
        self.assertEqual(build_augmented_prompt("continue debugging", "   \n"), "continue debugging")

    def test_process_result_context_for_recall_uses_payload_text(self) -> None:
        result = ProcessResult(
            route=RouteDecision(
                action="recall",
                confidence=0.9,
                reason="memory useful",
                signals=("owner",),
                user_message="debug owner",
            ),
            executed=True,
            result_text="[MemAgent recalled context]\n- memory\n\n[trace saved]\n- path: secret",
            artifacts={},
            writes=("recall_trace",),
            warnings=(),
            payload={"text": "[MemAgent recalled context]\n- memory"},
        )

        self.assertEqual(process_result_context_for_prompt(result), "[MemAgent recalled context]\n- memory")

    def test_process_result_context_for_none_is_blank(self) -> None:
        result = ProcessResult(
            route=RouteDecision(
                action="none",
                confidence=0.2,
                reason="no action",
                signals=(),
                user_message="hello",
            ),
            executed=False,
            result_text="ignored",
            artifacts={},
            writes=(),
            warnings=(),
        )

        self.assertEqual(process_result_context_for_prompt(result), "")

    def test_normalize_remainder(self) -> None:
        self.assertEqual(normalize_remainder(["--", "--model", "gpt-5.4"]), ["--model", "gpt-5.4"])
        self.assertEqual(normalize_remainder(["--model", "gpt-5.4"]), ["--model", "gpt-5.4"])


if __name__ == "__main__":
    unittest.main()
