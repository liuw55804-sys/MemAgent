from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from memagent.context import ProjectContext, matches_project_context, repo_scope_matches
from memagent.memory import MemoryStore


@dataclass(frozen=True)
class PendingDraftLifecycle:
    identifier: str
    topic: str
    created_at: datetime
    age_seconds: int

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.identifier,
            "topic": self.topic,
            "created_at": self.created_at.isoformat(),
            "age_seconds": self.age_seconds,
        }


@dataclass(frozen=True)
class MemoryReuseLifecycle:
    identifier: str
    topic: str
    created_at: datetime
    later_recall_count: int

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.identifier,
            "topic": self.topic,
            "created_at": self.created_at.isoformat(),
            "later_recall_count": self.later_recall_count,
        }


@dataclass(frozen=True)
class LifecycleSummary:
    recall_total: int
    feedback_counts: dict[str, int]
    draft_total: int
    draft_confirmed: int
    draft_pending: tuple[PendingDraftLifecycle, ...]
    draft_unconfirmed: int
    draft_legacy_unlinked: int
    draft_status_counts: dict[str, int]
    memory_total: int
    memory_recalled_again: int
    later_recall_count: int
    reused_memories: tuple[MemoryReuseLifecycle, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "recall": {
                "total": self.recall_total,
                "feedback": self.feedback_counts,
            },
            "draft": {
                "total": self.draft_total,
                "confirmed": self.draft_confirmed,
                "pending": len(self.draft_pending),
                "unconfirmed": self.draft_unconfirmed,
                "legacy_unlinked": self.draft_legacy_unlinked,
                "statuses": self.draft_status_counts,
                "pending_drafts": [item.to_payload() for item in self.draft_pending],
            },
            "memory_reuse": {
                "total_memories": self.memory_total,
                "recalled_again": self.memory_recalled_again,
                "later_recall_count": self.later_recall_count,
                "memories": [item.to_payload() for item in self.reused_memories],
            },
        }


def build_lifecycle_summary(
    *,
    store: MemoryStore,
    context: ProjectContext,
    since: date | None = None,
) -> LifecycleSummary:
    store.expire_pending_memory_draft(context=context)
    draft_ids: list[str] = []
    confirmed_ids: set[str] = set()
    saved_memory_paths: set[Path] = set()

    for path in _json_paths(store.process_traces_dir, "process_trace_*.json"):
        payload = _read_json(path)
        process = _object(payload.get("process"))
        if not _matches_context(_object(process.get("context")), context):
            continue
        created_at = _created_at(_object(payload.get("trace")), path)
        if not _in_window(created_at, since):
            continue
        route = _object(process.get("route"))
        artifacts = _object(process.get("artifacts"))
        action = _text(route.get("action"))
        if action == "draft_memory":
            identifier = _text(artifacts.get("pending_draft_id"))
            if identifier:
                draft_ids.append(identifier)
        elif action == "save_memory":
            identifier = _text(artifacts.get("pending_draft_id"))
            if identifier:
                confirmed_ids.add(identifier)
            memory_path = _existing_memory_path(artifacts.get("memory_path"), store)
            if memory_path:
                saved_memory_paths.add(memory_path)

    recall_records: list[tuple[datetime, set[Path], dict[str, Any]]] = []
    feedback_counts: Counter[str] = Counter()
    for path in _json_paths(store.traces_dir, "trace_*.json"):
        payload = _read_json(path)
        if not _matches_context(_object(payload.get("context")), context):
            continue
        created_at = _created_at(_object(payload.get("trace")), path)
        if not _in_window(created_at, since):
            continue
        matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
        memory_paths = {
            candidate
            for match in matches
            if isinstance(match, dict)
            for candidate in [_existing_memory_path(match.get("path"), store)]
            if candidate is not None
        }
        recall_records.append((created_at, memory_paths, payload))
        rating = _text(_object(payload.get("feedback")).get("rating"))
        if rating:
            feedback_counts[rating] += 1

    pending_drafts = _pending_drafts(store=store, context=context)
    archived_statuses, archived_confirmed_ids = _archived_draft_statuses(
        store=store,
        context=context,
        since=since,
    )
    confirmed_ids.update(archived_confirmed_ids)
    pending_ids = {item.identifier for item in pending_drafts}
    draft_total = len(draft_ids)
    legacy_ids = {
        identifier
        for identifier in draft_ids
        if _is_legacy_pending_id(identifier)
        and identifier not in confirmed_ids
        and identifier not in pending_ids
    }
    observable_ids = set(draft_ids) - legacy_ids
    confirmed = len(observable_ids & confirmed_ids)
    unconfirmed = max(len(observable_ids) - confirmed - len(observable_ids & pending_ids), 0)

    recalled_paths = {path for _, paths, _ in recall_records for path in paths}
    memory_paths = _project_memory_paths(
        store=store,
        context=context,
        explicit_paths=saved_memory_paths | recalled_paths,
        since=since,
    )
    memories: list[MemoryReuseLifecycle] = []
    for path in memory_paths:
        raw = path.read_text(encoding="utf-8", errors="replace")
        created_at = _parse_datetime(_yaml_value(raw, "created_at")) or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        later_recall_count = sum(
            1
            for recalled_at, paths, _ in recall_records
            if recalled_at > created_at and path in paths
        )
        memories.append(
            MemoryReuseLifecycle(
                identifier=_yaml_value(raw, "id") or path.stem,
                topic=_yaml_value(raw, "topic") or path.stem,
                created_at=created_at,
                later_recall_count=later_recall_count,
            )
        )
    memories.sort(key=lambda item: item.created_at, reverse=True)
    reused = tuple(item for item in memories if item.later_recall_count > 0)
    return LifecycleSummary(
        recall_total=len(recall_records),
        feedback_counts=dict(sorted(feedback_counts.items())),
        draft_total=draft_total,
        draft_confirmed=confirmed,
        draft_pending=tuple(sorted(pending_drafts, key=lambda item: item.created_at)),
        draft_unconfirmed=unconfirmed,
        draft_legacy_unlinked=len(legacy_ids),
        draft_status_counts=dict(sorted(archived_statuses.items())),
        memory_total=len(memories),
        memory_recalled_again=len(reused),
        later_recall_count=sum(item.later_recall_count for item in reused),
        reused_memories=reused[:3],
    )


def _pending_drafts(*, store: MemoryStore, context: ProjectContext) -> list[PendingDraftLifecycle]:
    now = datetime.now(timezone.utc)
    result: list[PendingDraftLifecycle] = []
    for path in _json_paths(store.pending_drafts_dir, "pending_*.json"):
        payload = _read_json(path)
        if not _matches_context(_object(payload.get("context")), context):
            continue
        pending = _object(payload.get("pending"))
        draft = _object(payload.get("draft"))
        created_at = _parse_datetime(_text(pending.get("created_at"))) or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        identifier = _text(pending.get("id")) or path.stem
        topic = _text(draft.get("topic")) or "Untitled memory draft"
        age_seconds = max(int((now - created_at).total_seconds()), 0)
        result.append(PendingDraftLifecycle(identifier, topic, created_at, age_seconds))
    return result


def _archived_draft_statuses(
    *,
    store: MemoryStore,
    context: ProjectContext,
    since: date | None,
) -> tuple[Counter[str], set[str]]:
    counts: Counter[str] = Counter()
    confirmed_ids: set[str] = set()
    for path in _json_paths(store.pending_drafts_archive_dir, "*.json"):
        payload = _read_json(path)
        if not _matches_context(_object(payload.get("context")), context):
            continue
        pending = _object(payload.get("pending"))
        resolved_at = _parse_datetime(_text(pending.get("resolved_at"))) or datetime.fromtimestamp(
            path.stat().st_mtime,
            timezone.utc,
        )
        if not _in_window(resolved_at, since):
            continue
        status = _text(pending.get("status"))
        identifier = _text(pending.get("id"))
        if status:
            counts[status] += 1
        if status == "confirmed" and identifier:
            confirmed_ids.add(identifier)
    return counts, confirmed_ids


def _project_memory_paths(
    *,
    store: MemoryStore,
    context: ProjectContext,
    explicit_paths: set[Path],
    since: date | None,
) -> list[Path]:
    paths = set(explicit_paths)
    for path in store.memories_dir.glob("*.memory.yaml"):
        raw = path.read_text(encoding="utf-8", errors="replace")
        created_at = _parse_datetime(_yaml_value(raw, "created_at")) or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if _memory_matches_context(raw, context) and _in_window(created_at, since):
            paths.add(path.resolve())
    return sorted(paths)


def _existing_memory_path(value: object, store: MemoryStore) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    try:
        resolved = path.resolve()
        resolved.relative_to(store.memories_dir)
    except (OSError, ValueError):
        return None
    return resolved if resolved.exists() else None


def _matches_context(payload: dict[str, Any], context: ProjectContext) -> bool:
    return matches_project_context(payload, context)


def _memory_matches_context(raw: str, context: ProjectContext) -> bool:
    for index, line in enumerate(raw.splitlines()):
        if line.strip() != "scope:":
            continue
        for child in raw.splitlines()[index + 1 :]:
            if child and not child.startswith(" "):
                break
            if child.strip().startswith("repo:"):
                return repo_scope_matches(
                    _unquote(child.split(":", 1)[1].strip()),
                    context,
                )
    return False


def _json_paths(directory: Path, pattern: str) -> list[Path]:
    return sorted(directory.glob(pattern), reverse=True) if directory.exists() else []


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _created_at(trace: dict[str, Any], path: Path) -> datetime:
    return _parse_datetime(_text(trace.get("created_at"))) or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _in_window(created_at: datetime, since: date | None) -> bool:
    return since is None or created_at.astimezone().date() >= since


def _yaml_value(raw: str, key: str) -> str | None:
    prefix = f"{key}:"
    for line in raw.splitlines():
        if line.startswith(prefix):
            return _unquote(line.split(":", 1)[1].strip())
    return None


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"', "`"}:
        return value[1:-1]
    return value


def _is_legacy_pending_id(identifier: str) -> bool:
    return bool(re.fullmatch(r"pending_[0-9a-f]{12}", identifier))
