from __future__ import annotations

import unittest

from memagent.cli import normalize_remainder
from memagent.wrapper import build_augmented_prompt


class WrapperTest(unittest.TestCase):
    def test_build_augmented_prompt(self) -> None:
        prompt = build_augmented_prompt("continue debugging", "[MemAgent recalled context]\n- use id ranges")
        self.assertIn("[MemAgent recalled context]", prompt)
        self.assertIn("[User task]\ncontinue debugging", prompt)

    def test_build_augmented_prompt_without_memory(self) -> None:
        self.assertEqual(build_augmented_prompt("continue debugging", ""), "continue debugging")

    def test_build_augmented_prompt_ignores_blank_memory(self) -> None:
        self.assertEqual(build_augmented_prompt("continue debugging", "   \n"), "continue debugging")

    def test_normalize_remainder(self) -> None:
        self.assertEqual(normalize_remainder(["--", "--model", "gpt-5.4"]), ["--model", "gpt-5.4"])
        self.assertEqual(normalize_remainder(["--model", "gpt-5.4"]), ["--model", "gpt-5.4"])


if __name__ == "__main__":
    unittest.main()
