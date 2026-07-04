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


@dataclass(frozen=True)
class HandoffDraft:
    topic: str
    summary: str
    done: tuple[str, ...]
    next_steps: tuple[str, ...]
    open_questions: tuple[str, ...]
    memory_candidates: tuple[str, ...]


@dataclass(frozen=True)
class HandoffPromotionSelection:
    source_path: Path
    candidates: tuple[str, ...]
    selected_indices: tuple[int, ...]
    selected_candidates: tuple[str, ...]


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

    def save_draft(self, *, context: ProjectContext, draft: HandoffDraft) -> SavedHandoff:
        return self.save(
            context=context,
            summary=draft.summary,
            topic=draft.topic,
            done=list(draft.done),
            next_steps=list(draft.next_steps),
            open_questions=list(draft.open_questions),
            memory_candidates=list(draft.memory_candidates),
        )

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

    def promotion_selection(
        self,
        *,
        context: ProjectContext,
        indices: list[int],
        select_all: bool,
    ) -> HandoffPromotionSelection:
        latest = self.latest(context=context)
        if latest is None:
            raise ValueError("no handoff found for this project")
        candidates = memory_candidates_from_handoff(latest.text)
        if not candidates:
            raise ValueError("latest handoff has no memory candidates to promote")
        selected_indices = _select_candidate_indices(
            candidate_count=len(candidates),
            indices=indices,
            select_all=select_all,
        )
        selected_candidates = tuple(candidates[index - 1] for index in selected_indices)
        return HandoffPromotionSelection(
            source_path=latest.path,
            candidates=tuple(candidates),
            selected_indices=tuple(selected_indices),
            selected_candidates=selected_candidates,
        )


def draft_handoff_from_text(
    text: str,
    *,
    topic: str | None = None,
    max_items: int = 5,
) -> HandoffDraft:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("handoff draft source cannot be empty")
    max_items = max(max_items, 1)
    sections = _extract_sections(cleaned)
    plain_lines = [_clean(_strip_markdown_prefix(line)) for line in cleaned.splitlines()]
    plain_lines = [line for line in plain_lines if line]

    summary = _first_section_text(sections, SUMMARY_HEADINGS) or _first_paragraph(cleaned)
    done = _items_from_sections(sections, DONE_HEADINGS, max_items=max_items)
    if not done:
        done = _keyword_items(plain_lines, DONE_KEYWORDS, max_items=max_items)
    next_steps = _items_from_sections(sections, NEXT_HEADINGS, max_items=max_items)
    if not next_steps:
        next_steps = _keyword_items(plain_lines, NEXT_KEYWORDS, max_items=max_items)
    open_questions = _items_from_sections(sections, OPEN_HEADINGS, max_items=max_items)
    if not open_questions:
        open_questions = _question_items(plain_lines, max_items=max_items)
    memory_candidates = _items_from_sections(sections, MEMORY_HEADINGS, max_items=max_items)
    if not memory_candidates:
        memory_candidates = _keyword_items(plain_lines, MEMORY_KEYWORDS, max_items=max_items)

    topic_value = _clean(topic or "") or _derive_draft_topic(summary, plain_lines)
    return HandoffDraft(
        topic=topic_value,
        summary=summary,
        done=tuple(done),
        next_steps=tuple(next_steps),
        open_questions=tuple(open_questions),
        memory_candidates=tuple(memory_candidates),
    )


def render_handoff_draft(draft: HandoffDraft, *, source: Path | None = None) -> str:
    lines = [
        "[MemAgent handoff draft]",
        f"- Topic: {draft.topic}",
    ]
    if source is not None:
        lines.append(f"- Source: {source}")
    lines.extend(
        [
            "",
            "## Summary",
            "",
            draft.summary,
            "",
            "## Done",
            "",
            *_bullet_lines(list(draft.done), fallback="No completed work detected."),
            "",
            "## Next Steps",
            "",
            *_bullet_lines(list(draft.next_steps), fallback="No next step detected."),
            "",
            "## Open Questions",
            "",
            *_bullet_lines(list(draft.open_questions), fallback="No open question detected."),
            "",
            "## Memory Candidates",
            "",
            *_bullet_lines(list(draft.memory_candidates), fallback="No durable memory candidate detected."),
        ]
    )
    return "\n".join(lines)


def memory_candidates_from_handoff(text: str) -> tuple[str, ...]:
    draft = draft_handoff_from_text(text)
    candidates = [
        candidate
        for candidate in draft.memory_candidates
        if candidate and not candidate.startswith("No long-term memory candidate")
    ]
    return tuple(candidates)


def render_promotion_preview(selection: HandoffPromotionSelection, *, write: bool) -> str:
    lines = [
        "[MemAgent handoff promote]",
        f"- source: {selection.source_path}",
        f"- mode: {'write' if write else 'dry-run'}",
        f"- candidates: {len(selection.candidates)}",
        f"- selected: {', '.join(str(index) for index in selection.selected_indices)}",
        "",
        "## Selected Candidates",
        "",
    ]
    for index, candidate in zip(selection.selected_indices, selection.selected_candidates):
        lines.append(f"- {index}. {candidate}")
    if not write:
        lines.extend(
            [
                "",
                "- Status: preview only; rerun with --write to save selected candidates as memory cards.",
            ]
        )
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


SUMMARY_HEADINGS = ("summary", "概要", "总结", "本轮总结", "session summary")
DONE_HEADINGS = ("done", "completed", "已完成", "完成", "本轮完成", "progress", "变更", "changes")
NEXT_HEADINGS = ("next", "next steps", "todo", "todos", "下一步", "后续", "待办")
OPEN_HEADINGS = ("open", "open questions", "questions", "问题", "开放问题")
MEMORY_HEADINGS = ("memory", "memory candidates", "lessons", "经验", "可沉淀", "候选记忆")

DONE_KEYWORDS = (
    "done",
    "completed",
    "implemented",
    "added",
    "verified",
    "passed",
    "已完成",
    "完成",
    "新增",
    "实现",
    "验证",
    "通过",
)
NEXT_KEYWORDS = (
    "next",
    "todo",
    "follow up",
    "should",
    "need to",
    "下一步",
    "后续",
    "待办",
    "需要",
    "可以继续",
)
MEMORY_KEYWORDS = (
    "memory",
    "remember",
    "lesson",
    "pitfall",
    "recipe",
    "handoff",
    "记忆",
    "沉淀",
    "经验",
    "下次",
    "坑",
)


def _extract_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "preamble"
    for raw_line in text.splitlines():
        heading = _heading_text(raw_line)
        if heading:
            current = heading
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(raw_line)
    return sections


def _heading_text(line: str) -> str | None:
    match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
    if not match:
        return None
    return _clean(match.group(1).strip("#")).lower()


def _first_section_text(sections: dict[str, list[str]], aliases: tuple[str, ...]) -> str | None:
    for lines in _matching_sections(sections, aliases):
        paragraph = _first_clean_paragraph(lines)
        if paragraph:
            return paragraph
    return None


def _items_from_sections(
    sections: dict[str, list[str]],
    aliases: tuple[str, ...],
    *,
    max_items: int,
) -> list[str]:
    items: list[str] = []
    for lines in _matching_sections(sections, aliases):
        for line in lines:
            item = _clean(_strip_markdown_prefix(line))
            if item:
                items.append(item)
            if len(items) >= max_items:
                return _dedupe(items)
    return _dedupe(items)[:max_items]


def _matching_sections(sections: dict[str, list[str]], aliases: tuple[str, ...]) -> list[list[str]]:
    matches: list[list[str]] = []
    for heading, lines in sections.items():
        if any(alias in heading for alias in aliases):
            matches.append(lines)
    return matches


def _first_paragraph(text: str) -> str:
    paragraph = _first_clean_paragraph(text.splitlines())
    return paragraph or "No summary detected."


def _first_clean_paragraph(lines: list[str]) -> str | None:
    collected: list[str] = []
    for raw_line in lines:
        line = _clean(_strip_markdown_prefix(raw_line))
        if not line:
            if collected:
                break
            continue
        if line.startswith("#"):
            continue
        collected.append(line)
        if len(" ".join(collected)) >= 160:
            break
    return " ".join(collected) if collected else None


def _keyword_items(lines: list[str], keywords: tuple[str, ...], *, max_items: int) -> list[str]:
    items = [line for line in lines if any(keyword.lower() in line.lower() for keyword in keywords)]
    return _dedupe(items)[:max_items]


def _question_items(lines: list[str], *, max_items: int) -> list[str]:
    items = [
        line
        for line in lines
        if "?" in line or "？" in line or "问题" in line or "是否" in line
    ]
    return _dedupe(items)[:max_items]


def _strip_markdown_prefix(line: str) -> str:
    stripped = line.strip()
    stripped = re.sub(r"^[-*+]\s+", "", stripped)
    stripped = re.sub(r"^\d+[.)]\s+", "", stripped)
    stripped = re.sub(r"^>\s*", "", stripped)
    return stripped.strip()


def _derive_draft_topic(summary: str, lines: list[str]) -> str:
    source = summary if summary != "No summary detected." else (lines[0] if lines else "Project handoff")
    return source[:60]


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _select_candidate_indices(
    *,
    candidate_count: int,
    indices: list[int],
    select_all: bool,
) -> list[int]:
    if select_all and indices:
        raise ValueError("use either --all or --index, not both")
    if select_all:
        return list(range(1, candidate_count + 1))
    selected = indices or [1]
    deduped: list[int] = []
    for index in selected:
        if index < 1 or index > candidate_count:
            raise ValueError(f"candidate index out of range: {index}")
        if index not in deduped:
            deduped.append(index)
    return deduped


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower()).strip("-")
    return slug or "project"


def _clean(value: str | None) -> str:
    return " ".join((value or "").strip().split())
