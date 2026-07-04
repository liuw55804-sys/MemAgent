from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import re
import textwrap

from memagent.context import ProjectContext


@dataclass(frozen=True)
class SavedHandoff:
    latest_path: Path
    history_path: Path
    project_key: str


@dataclass(frozen=True)
class HandoffMatch:
    path: Path
    project_key: str
    text: str


class HandoffStore:
    def __init__(self, home: Path) -> None:
        self.home = home.expanduser().resolve()
        self.handoffs_dir = self.home / "handoffs"
        self.handoffs_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        context: ProjectContext,
        summary: str,
        topic: str | None,
        done: list[str],
        next_steps: list[str],
        open_questions: list[str],
        memory_candidates: list[str],
    ) -> SavedHandoff:
        cleaned_summary = _clean(summary)
        if not cleaned_summary:
            raise ValueError("handoff summary cannot be empty")

        now = datetime.now(timezone.utc)
        project_key = project_handoff_key(context)
        project_dir = self.handoffs_dir / project_key
        history_dir = project_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)

        topic_value = _clean(topic or "") or f"{context.repo_name or 'project'} handoff"
        body = render_handoff_markdown(
            context=context,
            created_at=now.isoformat(),
            topic=topic_value,
            summary=cleaned_summary,
            done=done,
            next_steps=next_steps,
            open_questions=open_questions,
            memory_candidates=memory_candidates,
        )
        latest_path = project_dir / "latest.md"
        history_path = history_dir / f"handoff_{now.strftime('%Y%m%d_%H%M%S_%f')}.md"
        latest_path.write_text(body, encoding="utf-8")
        history_path.write_text(body, encoding="utf-8")
        return SavedHandoff(latest_path=latest_path, history_path=history_path, project_key=project_key)

    def latest(self, *, context: ProjectContext) -> HandoffMatch | None:
        project_key = project_handoff_key(context)
        path = self.handoffs_dir / project_key / "latest.md"
        if not path.exists():
            return None
        return HandoffMatch(
            path=path,
            project_key=project_key,
            text=path.read_text(encoding="utf-8", errors="replace"),
        )

    def compose_latest(
        self,
        *,
        context: ProjectContext,
        max_lines: int = 40,
        show_source: bool = True,
    ) -> str:
        latest = self.latest(context=context)
        lines = [
            "[MemAgent handoff]",
            f"- Project: {context.repo_name or 'unknown'}",
            f"- CWD: {context.cwd}",
        ]
        if latest is None:
            lines.append("- No handoff found for this project.")
            return "\n".join(lines)
        if show_source:
            lines.append(f"- Source: {latest.path}")
        lines.append("")
        remaining = max(max_lines - len(lines), 1)
        lines.extend(_trim_lines(_content_lines(latest.text), remaining))
        return "\n".join(lines)


def project_handoff_key(context: ProjectContext) -> str:
    root = context.git_root or context.cwd
    name = context.repo_name or root.name or "project"
    slug = _slugify(name)
    digest = hashlib.sha1(str(root.resolve()).encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}"


def render_handoff_markdown(
    *,
    context: ProjectContext,
    created_at: str,
    topic: str,
    summary: str,
    done: list[str],
    next_steps: list[str],
    open_questions: list[str],
    memory_candidates: list[str],
) -> str:
    lines = [
        f"# MemAgent Handoff: {topic}",
        "",
        "## Metadata",
        "",
        f"- created_at: `{created_at}`",
        f"- repo: `{context.repo_name or 'unknown'}`",
        f"- git_root: `{context.git_root or 'unknown'}`",
        f"- branch: `{context.branch or 'unknown'}`",
        f"- cwd: `{context.cwd}`",
        "",
        "## Summary",
        "",
        *_wrapped_paragraph(summary),
        "",
        "## Done",
        "",
        *_bullet_lines(done, fallback="No completed work recorded."),
        "",
        "## Next Steps",
        "",
        *_bullet_lines(next_steps, fallback="No next step recorded."),
        "",
        "## Open Questions",
        "",
        *_bullet_lines(open_questions, fallback="No open question recorded."),
        "",
        "## Memory Candidates",
        "",
        *_bullet_lines(memory_candidates, fallback="No long-term memory candidate recorded."),
        "",
    ]
    return "\n".join(lines)


def _wrapped_paragraph(text: str) -> list[str]:
    wrapped = textwrap.wrap(_clean(text), width=88)
    return wrapped or ["No summary recorded."]


def _bullet_lines(items: list[str], *, fallback: str) -> list[str]:
    cleaned = [_clean(item) for item in items if _clean(item)]
    if not cleaned:
        return [f"- {fallback}"]
    return [f"- {item}" for item in cleaned]


def _trim_lines(lines: list[str], max_lines: int) -> list[str]:
    if max_lines <= 0:
        return []
    if len(lines) <= max_lines:
        return lines
    return [*lines[: max_lines - 1], "..."]


def _content_lines(text: str) -> list[str]:
    lines = text.splitlines()
    result: list[str] = []
    skip_metadata = False
    for line in lines:
        if line == "## Metadata":
            skip_metadata = True
            continue
        if skip_metadata and line.startswith("## "):
            skip_metadata = False
        if not skip_metadata:
            result.append(line)
    return result


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower()).strip("-")
    return slug or "project"


def _clean(value: str | None) -> str:
    return " ".join((value or "").strip().split())
