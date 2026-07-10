from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

from memagent.context import ProjectContext
from memagent.handoff import HandoffStore, project_handoff_key
from memagent.memory import MemoryStore


@dataclass(frozen=True)
class ActivityEvent:
    created_at: datetime
    category: str
    label: str
    identifier: str
    detail: str

    def to_payload(self) -> dict[str, str]:
        return {
            "created_at": self.created_at.isoformat(),
            "category": self.category,
            "label": self.label,
            "identifier": self.identifier,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ActivityReport:
    context: ProjectContext
    window_label: str
    events: tuple[ActivityEvent, ...]
    action_counts: dict[str, int]
    recall_total: int
    feedback_counts: dict[str, int]
    memory_count: int
    handoff_count: int

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": "memagent.activity.v1",
            "window": self.window_label,
            "context": {
                "cwd": str(self.context.cwd),
                "git_root": str(self.context.git_root) if self.context.git_root else None,
                "repo_name": self.context.repo_name,
            },
            "summary": {
                "actions": self.action_counts,
                "recalls": self.recall_total,
                "feedback": self.feedback_counts,
                "memories_created": self.memory_count,
                "handoffs_saved": self.handoff_count,
            },
            "events": [event.to_payload() for event in self.events],
        }


def build_activity_report(
    *,
    store: MemoryStore,
    handoff_store: HandoffStore,
    context: ProjectContext,
    since: date | None = None,
    limit: int = 20,
) -> ActivityReport:
    events: list[ActivityEvent] = []
    action_counts: Counter[str] = Counter()
    recall_total = 0
    feedback_counts: Counter[str] = Counter()

    for path in _json_paths(store.process_traces_dir, "process_trace_*.json"):
        payload = _read_json(path)
        process = payload.get("process") if isinstance(payload.get("process"), dict) else {}
        process_context = process.get("context") if isinstance(process.get("context"), dict) else {}
        if not _matches_context(process_context, context):
            continue
        created_at = _created_at(payload.get("trace"), path)
        if not _in_window(created_at, since):
            continue
        route = process.get("route") if isinstance(process.get("route"), dict) else {}
        action = _text(route.get("action")) or "unknown"
        action_counts[action] += 1
        artifacts = process.get("artifacts") if isinstance(process.get("artifacts"), dict) else {}
        detail = _event_detail(action, artifacts)
        events.append(
            ActivityEvent(
                created_at=created_at,
                category="process",
                label=action,
                identifier=_trace_identifier(payload.get("trace"), path),
                detail=detail,
            )
        )

    for path in _json_paths(store.traces_dir, "trace_*.json"):
        payload = _read_json(path)
        trace_context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        if not _matches_context(trace_context, context):
            continue
        created_at = _created_at(payload.get("trace"), path)
        if not _in_window(created_at, since):
            continue
        recall_total += 1
        feedback = payload.get("feedback") if isinstance(payload.get("feedback"), dict) else {}
        rating = _text(feedback.get("rating"))
        if rating:
            feedback_counts[rating] += 1

    memory_count = 0
    for path in sorted(store.memories_dir.glob("*.memory.yaml"), reverse=True):
        raw = path.read_text(encoding="utf-8", errors="replace")
        if not _memory_matches_context(raw, context):
            continue
        created_at = _parse_datetime(_yaml_value(raw, "created_at")) or datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        if not _in_window(created_at, since):
            continue
        memory_count += 1
        events.append(
            ActivityEvent(
                created_at=created_at,
                category="memory",
                label="memory_saved",
                identifier=_yaml_value(raw, "id") or path.stem,
                detail=_yaml_value(raw, "topic") or path.stem,
            )
        )

    handoff_count = 0
    handoff_history = handoff_store.handoffs_dir / project_handoff_key(context) / "history"
    for path in sorted(handoff_history.glob("handoff_*.md"), reverse=True) if handoff_history.exists() else []:
        raw = path.read_text(encoding="utf-8", errors="replace")
        created_at = _parse_datetime(_handoff_value(raw, "created_at")) or datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        if not _in_window(created_at, since):
            continue
        handoff_count += 1
        events.append(
            ActivityEvent(
                created_at=created_at,
                category="handoff",
                label="handoff_saved",
                identifier=path.stem,
                detail=_handoff_topic(raw) or context.repo_name or "project handoff",
            )
        )

    events.sort(key=lambda event: event.created_at, reverse=True)
    return ActivityReport(
        context=context,
        window_label=_window_label(since),
        events=tuple(events[: max(limit, 0)]),
        action_counts=dict(sorted(action_counts.items())),
        recall_total=recall_total,
        feedback_counts=dict(sorted(feedback_counts.items())),
        memory_count=memory_count,
        handoff_count=handoff_count,
    )


def render_activity_report(report: ActivityReport) -> str:
    lines = [
        "[MemAgent activity]",
        f"- Project: {report.context.repo_name or 'unknown'}",
        f"- CWD: {report.context.cwd}",
        f"- Window: {report.window_label}",
        f"- Actions: {_render_counts(report.action_counts)}",
        f"- Recall traces: {report.recall_total}",
        f"- Recall feedback: {_render_counts(report.feedback_counts)}",
        f"- Memory cards saved: {report.memory_count}",
        f"- Handoffs saved: {report.handoff_count}",
    ]
    if not report.events:
        lines.append("- No local MemAgent activity found in this window.")
        return "\n".join(lines)
    lines.extend(["", "## Recent activity", ""])
    for event in report.events:
        local = event.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
        suffix = f" | {event.detail}" if event.detail else ""
        lines.append(f"- {local} | {event.label}{suffix}")
    return "\n".join(lines)


def _json_paths(directory: Path, pattern: str) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob(pattern), reverse=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _matches_context(payload: dict[str, Any], context: ProjectContext) -> bool:
    candidate_root = _text(payload.get("git_root"))
    candidate_cwd = _text(payload.get("cwd"))
    candidate_repo = _text(payload.get("repo_name"))
    if context.git_root and candidate_root:
        return Path(candidate_root).expanduser().resolve() == context.git_root.resolve()
    if candidate_cwd:
        candidate_path = Path(candidate_cwd).expanduser().resolve()
        return candidate_path == context.cwd or context.cwd.is_relative_to(candidate_path) or candidate_path.is_relative_to(context.cwd)
    return bool(context.repo_name and candidate_repo and candidate_repo == context.repo_name)


def _memory_matches_context(raw: str, context: ProjectContext) -> bool:
    repo = _yaml_scope_repo(raw)
    return bool(context.repo_name and repo and repo == context.repo_name)


def _yaml_scope_repo(raw: str) -> str | None:
    lines = raw.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "scope:":
            continue
        for child in lines[index + 1 :]:
            if child and not child.startswith(" "):
                break
            if child.strip().startswith("repo:"):
                return _unquote(child.split(":", 1)[1].strip())
    return None


def _yaml_value(raw: str, key: str) -> str | None:
    prefix = f"{key}:"
    for line in raw.splitlines():
        if line.startswith(prefix):
            return _unquote(line.split(":", 1)[1].strip())
    return None


def _handoff_value(raw: str, key: str) -> str | None:
    prefix = f"- {key}:"
    for line in raw.splitlines():
        if line.startswith(prefix):
            return _unquote(line.split(":", 1)[1].strip()) or None
    return None


def _handoff_topic(raw: str) -> str | None:
    prefix = "# MemAgent Handoff:"
    for line in raw.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip() or None
    return None


def _created_at(trace: object, path: Path) -> datetime:
    if isinstance(trace, dict):
        parsed = _parse_datetime(_text(trace.get("created_at")))
        if parsed:
            return parsed
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone()


def _trace_identifier(trace: object, path: Path) -> str:
    if isinstance(trace, dict):
        identifier = _text(trace.get("id"))
        if identifier:
            return identifier
    return path.stem


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _in_window(created_at: datetime, since: date | None) -> bool:
    return since is None or created_at.astimezone().date() >= since


def _event_detail(action: str, artifacts: dict[str, Any]) -> str:
    if action == "recall":
        matches = artifacts.get("matches")
        return f"{matches} matching memories" if matches is not None else "memory recall"
    if action == "draft_memory":
        return _text(artifacts.get("topic")) or "memory preview drafted"
    if action == "save_memory":
        return "confirmed memory preview saved"
    if action == "label_feedback":
        return _text(artifacts.get("rating")) or "recall feedback labeled"
    if action.startswith("handoff"):
        return "project continuation state"
    return ""


def _render_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in counts.items()) if counts else "none"


def _window_label(since: date | None) -> str:
    return f"since {since.isoformat()} (local time)" if since else "all local history"


def _text(value: object) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == "`":
        return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
