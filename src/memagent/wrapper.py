from __future__ import annotations


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

