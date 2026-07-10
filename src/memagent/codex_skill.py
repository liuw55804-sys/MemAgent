from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex


MANAGED_MARKER = "<!-- memagent:user-codex-skill -->"
_COMMAND_TOKEN = "__MEMAGENT_COMMAND__"


@dataclass(frozen=True)
class UserCodexSkillPlan:
    target: Path
    action: str
    changed: bool
    blocked: bool
    reason: str
    next_content: str


def default_memagent_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_user_skill_target() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    return (codex_home / "skills" / "memagent" / "SKILL.md").resolve()


def build_user_codex_skill_plan(
    *,
    target: Path | None = None,
    memagent_root: Path | None = None,
    command_prefix: str | None = None,
    force: bool = False,
) -> UserCodexSkillPlan:
    resolved_target = (target or default_user_skill_target()).expanduser().resolve()
    content = render_user_codex_skill(
        memagent_root=memagent_root,
        command_prefix=command_prefix,
    )
    if not resolved_target.exists():
        return UserCodexSkillPlan(
            target=resolved_target,
            action="create",
            changed=True,
            blocked=False,
            reason="No user-level MemAgent Codex skill exists yet.",
            next_content=content,
        )

    existing = resolved_target.read_text(encoding="utf-8", errors="replace")
    if existing == content:
        return UserCodexSkillPlan(
            target=resolved_target,
            action="unchanged",
            changed=False,
            blocked=False,
            reason="The user-level MemAgent Codex skill is already current.",
            next_content=content,
        )
    if MANAGED_MARKER in existing or force:
        return UserCodexSkillPlan(
            target=resolved_target,
            action="replace",
            changed=True,
            blocked=False,
            reason="Replacing the managed MemAgent user-level Codex skill.",
            next_content=content,
        )
    return UserCodexSkillPlan(
        target=resolved_target,
        action="blocked",
        changed=False,
        blocked=True,
        reason="Target exists but is not a managed MemAgent skill. Use --force only after reviewing it.",
        next_content=content,
    )


def write_user_codex_skill_plan(plan: UserCodexSkillPlan) -> None:
    if plan.blocked or not plan.changed:
        return
    plan.target.parent.mkdir(parents=True, exist_ok=True)
    plan.target.write_text(plan.next_content, encoding="utf-8")


def uninstall_user_codex_skill(*, target: Path | None = None, force: bool = False) -> UserCodexSkillPlan:
    resolved_target = (target or default_user_skill_target()).expanduser().resolve()
    if not resolved_target.exists():
        return UserCodexSkillPlan(
            target=resolved_target,
            action="absent",
            changed=False,
            blocked=False,
            reason="No user-level MemAgent Codex skill is installed.",
            next_content="",
        )
    existing = resolved_target.read_text(encoding="utf-8", errors="replace")
    if MANAGED_MARKER not in existing and not force:
        return UserCodexSkillPlan(
            target=resolved_target,
            action="blocked",
            changed=False,
            blocked=True,
            reason="Target is not a managed MemAgent skill. Use --force only after reviewing it.",
            next_content="",
        )
    return UserCodexSkillPlan(
        target=resolved_target,
        action="remove",
        changed=True,
        blocked=False,
        reason="Removing the managed MemAgent user-level Codex skill.",
        next_content="",
    )


def write_user_codex_skill_uninstall(plan: UserCodexSkillPlan) -> None:
    if plan.blocked or plan.action != "remove":
        return
    plan.target.unlink()


def render_user_codex_skill(
    *,
    memagent_root: Path | None = None,
    command_prefix: str | None = None,
) -> str:
    root = (memagent_root or default_memagent_root()).expanduser().resolve()
    prefix = command_prefix or _source_command_prefix(root)
    template_path = root / "templates" / "codex_skills" / "memagent" / "SKILL.md"
    template = template_path.read_text(encoding="utf-8")
    return template.replace(_COMMAND_TOKEN, prefix)


def render_user_codex_skill_report(plan: UserCodexSkillPlan, *, write: bool) -> str:
    status = "blocked" if plan.blocked else ("written" if write and plan.changed else "ready")
    if plan.action == "create" and not write:
        status = "setup needed"
    if plan.action == "replace" and not write:
        status = "update needed"
    if plan.action == "unchanged":
        status = "current"
    if plan.action == "absent":
        status = "absent"
    if plan.action == "remove" and write:
        status = "removed"
    lines = [
        "[MemAgent user-level Codex skill]",
        f"- status: {status}",
        f"- action: {plan.action}",
        f"- target: {plan.target}",
        f"- reason: {plan.reason}",
        "- business repo changes: none",
    ]
    if not write and plan.changed and not plan.blocked:
        lines.append("- mode: dry-run; add --write to apply this user-level change")
    return "\n".join(lines)


def _source_command_prefix(root: Path) -> str:
    src = shlex.quote(str(root / "src"))
    return f"PYTHONPATH={src} python -m memagent.cli"
