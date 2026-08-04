from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

from memagent.context import ProjectContext, matches_project_context, repo_scope_matches
from memagent.handoff import HandoffStore, project_handoff_key
from memagent.lifecycle import LifecycleSummary, build_lifecycle_summary
from memagent.memory import MemoryStore
from memagent.reflection import reflection_project_id


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
    adoption_counts: dict[str, int]
    memory_count: int
    handoff_count: int
    lifecycle: LifecycleSummary
    retrieval: dict[str, int | float]
    suggestions: dict[str, int]
    reflections: dict[str, int | float]

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": "memagent.activity.v2",
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
                "adoption": self.adoption_counts,
                "memories_created": self.memory_count,
                "handoffs_saved": self.handoff_count,
                "retrieval": self.retrieval,
                "suggestions": self.suggestions,
                "reflections": self.reflections,
            },
            "events": [event.to_payload() for event in self.events],
            "lifecycle": self.lifecycle.to_payload(),
        }


def build_activity_report(
    *,
    store: MemoryStore,
    handoff_store: HandoffStore,
    context: ProjectContext,
    since: date | None = None,
    limit: int = 20,
) -> ActivityReport:
    store.expire_pending_memory_draft(context=context)
    events: list[ActivityEvent] = []
    action_counts: Counter[str] = Counter()
    recall_total = 0
    feedback_counts: Counter[str] = Counter()
    adoption_counts: Counter[str] = Counter()
    retrieval_counts: Counter[str] = Counter()
    suggestion_counts: Counter[str] = Counter()
    reflection_counts: Counter[str] = Counter()
    reflection_latencies: list[int] = []
    automatic_memory_ids: set[str] = set()
    retrieval_latencies: dict[str, list[int]] = {
        "candidate_generation_ms": [],
        "local_relevance_ms": [],
        "relevance_gate_ms": [],
    }

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
        if artifacts.get("recall_considered"):
            retrieval_counts["considered"] += 1
            retrieval_counts["candidates"] += _integer(artifacts.get("candidates"))
            retrieval_counts["emitted"] += _integer(artifacts.get("emitted"))
            if artifacts.get("abstained"):
                retrieval_counts["abstained"] += 1
            if artifacts.get("relevance_gate_attempted"):
                retrieval_counts["llm_gate_attempted"] += 1
            if artifacts.get("relevance_gate_fallback"):
                retrieval_counts["llm_gate_fallback"] += 1
            if artifacts.get("relevance_gate_skipped_cooldown"):
                retrieval_counts["llm_gate_skipped_cooldown"] += 1
            failure_kind = _text(artifacts.get("relevance_gate_failure_kind"))
            if failure_kind:
                retrieval_counts[f"llm_gate_{failure_kind}"] += 1
            retrieval_counts["suppressed_by_cooldown"] += _integer(
                artifacts.get("suppressed_by_cooldown")
            )
            cooldown_scope = _text(artifacts.get("recall_cooldown_scope"))
            if cooldown_scope in {"session", "time"}:
                retrieval_counts[f"cooldown_scope_{cooldown_scope}"] += 1
            for key in retrieval_latencies:
                value = artifacts.get(key)
                if isinstance(value, (int, float)):
                    retrieval_latencies[key].append(max(int(value), 0))
        if artifacts.get("agent_suggested"):
            suggestion_counts["suggested"] += 1
            status = _text(artifacts.get("status"))
            if status in {"duplicate", "pending_exists"}:
                suggestion_counts[status] += 1
        source = _text(artifacts.get("source"))
        if source in {"agent_suggested", "automatic_reflection"} and artifacts.get("user_confirmed"):
            suggestion_counts["accepted"] += 1
        if source in {"agent_suggested", "automatic_reflection"} and artifacts.get("user_rejected"):
            suggestion_counts["rejected"] += 1
        if source == "automatic_reflection" and artifacts.get("user_confirmed"):
            reflection_counts["accepted"] += 1
        if source == "automatic_reflection" and artifacts.get("user_rejected"):
            reflection_counts["rejected"] += 1
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

    for path in _json_paths(store.reflection_traces_dir, "reflection_*.json"):
        payload = _read_json(path)
        reflection_context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        if not _matches_reflection_context(reflection_context, context):
            continue
        created_at = _created_at(payload.get("trace"), path)
        if not _in_window(created_at, since):
            continue
        assessment = payload.get("assessment") if isinstance(payload.get("assessment"), dict) else {}
        outcome = payload.get("outcome") if isinstance(payload.get("outcome"), dict) else {}
        reflection_counts["considered"] += 1
        verdict = _text(assessment.get("verdict")) or "abstain"
        status = _text(outcome.get("status")) or _text(assessment.get("status")) or "assessed"
        if verdict == "suggest" and _text(outcome.get("action")) == "draft_memory":
            reflection_counts["emitted"] += 1
        else:
            reflection_counts["abstained"] += 1
        if status in {"duplicate", "pending_exists"}:
            reflection_counts["duplicate_suppressed"] += 1
        if status == "session_limit":
            reflection_counts["session_suppressed"] += 1
        gate = assessment.get("gate") if isinstance(assessment.get("gate"), dict) else {}
        if gate.get("attempted"):
            reflection_counts["llm_gate_attempted"] += 1
        if gate.get("fallback"):
            reflection_counts["llm_gate_fallback"] += 1
        latency = assessment.get("latency_ms")
        if isinstance(latency, (int, float)):
            reflection_latencies.append(max(int(latency), 0))
        if verdict == "suggest" and _text(outcome.get("action")) == "draft_memory":
            events.append(
                ActivityEvent(
                    created_at=created_at,
                    category="reflection",
                    label="memory_suggested",
                    identifier=_trace_identifier(payload.get("trace"), path),
                    detail=status,
                )
            )

    for path in _json_paths(store.pending_drafts_archive_dir, "*.json"):
        payload = _read_json(path)
        archived_context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        if not _matches_context(archived_context, context):
            continue
        pending = payload.get("pending") if isinstance(payload.get("pending"), dict) else {}
        resolved_at = _parse_datetime(_text(pending.get("resolved_at")))
        if resolved_at and not _in_window(resolved_at, since):
            continue
        pending_source = _text(pending.get("source"))
        if pending_source not in {"agent_suggested", "automatic_reflection"}:
            continue
        status = _text(pending.get("status"))
        if status in {"expired", "replaced"}:
            suggestion_counts[status] += 1
        if pending_source == "automatic_reflection":
            if status == "expired":
                reflection_counts["expired"] += 1
            memory_id = _text(pending.get("memory_id"))
            if status == "confirmed" and memory_id:
                automatic_memory_ids.add(memory_id)

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
        adoption = payload.get("adoption") if isinstance(payload.get("adoption"), dict) else {}
        signal = _text(adoption.get("signal"))
        if signal:
            adoption_counts[signal] += 1

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
    lifecycle = build_lifecycle_summary(store=store, context=context, since=since)
    if store.has_pending_memory_draft(context=context):
        try:
            pending = store.load_pending_memory_draft(context=context)
            pending_meta = pending.get("pending") if isinstance(pending.get("pending"), dict) else {}
            if pending_meta.get("source") in {"agent_suggested", "automatic_reflection"}:
                suggestion_counts["pending"] = 1
            if pending_meta.get("source") == "automatic_reflection":
                reflection_counts["pending"] = 1
        except ValueError:
            pass
    retrieval = dict(sorted(retrieval_counts.items()))
    for key, values in retrieval_latencies.items():
        if values:
            retrieval[f"avg_{key}"] = round(sum(values) / len(values), 1)
    reflections: dict[str, int | float] = dict(sorted(reflection_counts.items()))
    resolved = reflection_counts["accepted"] + reflection_counts["rejected"]
    if resolved:
        reflections["acceptance_rate"] = round(reflection_counts["accepted"] / resolved, 3)
    reused_ids = {item.identifier for item in lifecycle.reused_memories}
    if automatic_memory_ids:
        reflections["confirmed_memories"] = len(automatic_memory_ids)
        reflections["later_recalled"] = len(automatic_memory_ids & reused_ids)
    if reflection_latencies:
        reflections["avg_decision_latency_ms"] = round(
            sum(reflection_latencies) / len(reflection_latencies),
            1,
        )
    return ActivityReport(
        context=context,
        window_label=_window_label(since),
        events=tuple(events[: max(limit, 0)]),
        action_counts=dict(sorted(action_counts.items())),
        recall_total=recall_total,
        feedback_counts=dict(sorted(feedback_counts.items())),
        adoption_counts=dict(sorted(adoption_counts.items())),
        memory_count=memory_count,
        handoff_count=handoff_count,
        lifecycle=lifecycle,
        retrieval=retrieval,
        suggestions=dict(sorted(suggestion_counts.items())),
        reflections=reflections,
    )


def render_activity_report(report: ActivityReport) -> str:
    if not report.events and not report.reflections and not _has_lifecycle_data(report.lifecycle):
        return "\n".join(
            [
                "[MemAgent activity]",
                f"- Project: {report.context.repo_name or 'unknown'}",
                f"- Window: {report.window_label}",
                "- No local MemAgent activity found in this window.",
            ]
        )
    lines = [
        "[MemAgent activity]",
        f"- Project: {report.context.repo_name or 'unknown'}",
        f"- CWD: {report.context.cwd}",
        f"- Window: {report.window_label}",
        f"- Actions: {_render_counts(report.action_counts)}",
        f"- Recall traces: {report.recall_total}",
        f"- Recall feedback: {_render_counts(report.feedback_counts)}",
        f"- Recall adoption: {_render_counts(report.adoption_counts)}",
        f"- Memory cards saved: {report.memory_count}",
        f"- Handoffs saved: {report.handoff_count}",
        f"- Recall precision: {_render_retrieval(report.retrieval)}",
        f"- Proactive memory: {_render_counts(report.suggestions)}",
        f"- Task reflections: {_render_counts(report.reflections)}",
        (
            "- Draft lifecycle: "
            f"total={report.lifecycle.draft_total}, "
            f"pending={len(report.lifecycle.draft_pending)}, "
            f"confirmed={report.lifecycle.draft_confirmed}, "
            f"unconfirmed={report.lifecycle.draft_unconfirmed}"
        ),
        (
            "- Memory reuse: "
            f"{report.lifecycle.memory_recalled_again}/{report.lifecycle.memory_total} cards recalled again; "
            f"later recalls={report.lifecycle.later_recall_count}"
        ),
    ]
    if not report.events:
        lines.append("- No local MemAgent activity found in this window.")
        return "\n".join(lines)
    if report.lifecycle.draft_legacy_unlinked:
        lines.append(
            "- Legacy draft links: "
            f"{report.lifecycle.draft_legacy_unlinked} older drafts cannot be matched to confirmation events."
        )
    if report.lifecycle.draft_pending or report.lifecycle.reused_memories:
        lines.extend(["", "## Lifecycle", ""])
        for draft in report.lifecycle.draft_pending:
            lines.append(f"- Pending draft: {draft.topic} | waiting {_render_age(draft.age_seconds)}")
        for memory in report.lifecycle.reused_memories:
            lines.append(f"- Recalled again: {memory.topic} | {memory.later_recall_count} later recalls")
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


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return max(int(value), 0)
    return 0


def _render_retrieval(values: dict[str, int | float]) -> str:
    if not values:
        return "-"
    primary = (
        "considered",
        "emitted",
        "abstained",
        "llm_gate_attempted",
        "llm_gate_fallback",
        "llm_gate_skipped_cooldown",
        "suppressed_by_cooldown",
        "cooldown_scope_session",
        "cooldown_scope_time",
    )
    parts = [f"{key}={values.get(key, 0)}" for key in primary]
    if "avg_candidate_generation_ms" in values or "avg_local_relevance_ms" in values:
        local_ms = float(values.get("avg_candidate_generation_ms", 0)) + float(
            values.get("avg_local_relevance_ms", 0)
        )
        parts.append(f"avg_local_ms={local_ms:.1f}")
    if "avg_relevance_gate_ms" in values:
        parts.append(f"avg_llm_ms={float(values['avg_relevance_gate_ms']):.1f}")
    return ", ".join(parts)


def _matches_context(payload: dict[str, Any], context: ProjectContext) -> bool:
    return matches_project_context(payload, context)


def _matches_reflection_context(payload: dict[str, Any], context: ProjectContext) -> bool:
    project_id = _text(payload.get("project_id"))
    if project_id:
        return project_id == reflection_project_id(context)
    return matches_project_context(payload, context)


def _memory_matches_context(raw: str, context: ProjectContext) -> bool:
    repo = _yaml_scope_repo(raw)
    return repo_scope_matches(repo, context)


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


def _render_age(seconds: int) -> str:
    if seconds < 60:
        return "under 1 minute"
    if seconds < 3600:
        return f"{seconds // 60} minutes"
    if seconds < 86400:
        return f"{seconds // 3600} hours"
    return f"{seconds // 86400} days"


def _has_lifecycle_data(lifecycle: LifecycleSummary) -> bool:
    return bool(
        lifecycle.recall_total
        or lifecycle.draft_total
        or lifecycle.draft_pending
        or lifecycle.memory_total
    )


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
