from __future__ import annotations

from memagent.interaction import ProcessResult


def build_augmented_prompt(user_prompt: str, recalled_context: str) -> str:
    if not recalled_context.strip():
        return user_prompt
    return "\n".join(
        [
            recalled_context.strip(),
            "",
            "[User task]",
            user_prompt.strip(),
        ]
    )


def process_result_context_for_prompt(result: ProcessResult) -> str:
    if result.route.action == "none":
        return ""
    if result.route.action == "recall" and isinstance(result.payload, dict):
        text = result.payload.get("text")
        if isinstance(text, str):
            return text
    return result.result_text
