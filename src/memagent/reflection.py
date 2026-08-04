from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from pathlib import Path
import time
from typing import Any, Callable, Iterable

from memagent.context import ProjectContext
from memagent.draft import draft_memory_heuristic
from memagent.gate_health import GateHealthStore
from memagent.llm import (
    OpenAICompatibleConfig,
    chat_completion,
    load_semantic_config,
    loads_json_object,
    sanitize_llm_text,
)
from memagent.recall_cooldown import current_session_id


REFLECTION_SCHEMA_VERSION = "memagent.reflection.v1"
REFLECTION_TRACE_SCHEMA_VERSION = "memagent.reflection_trace.v1"
REFLECTION_SESSION_SCHEMA_VERSION = "memagent.reflection_session.v1"
REFLECTION_TIMEOUT_SECONDS = 3
REFLECTION_SUMMARY_LIMIT = 1200
DEFAULT_FALLBACK_COOLDOWN_SECONDS = 6 * 60 * 60
SESSION_RECORD_RETENTION_DAYS = 30

ALLOWED_REFLECTION_SIGNALS = {
    "detour",
    "correction",
    "verified_entrypoint",
    "costly_investigation",
    "workflow",
    "project_boundary",
    "verified_outcome",
}

_SIGNAL_WEIGHTS = {
    "detour": 0.16,
    "correction": 0.24,
    "verified_entrypoint": 0.24,
    "costly_investigation": 0.20,
    "workflow": 0.18,
    "project_boundary": 0.16,
    "verified_outcome": 0.20,
}


@dataclass(frozen=True)
class ReflectionGateTrace:
    mode: str
    attempted: bool
    selected: bool
    fallback: bool
    provider: str
    latency_ms: int
    profile: str | None = None
    skipped_due_to_cooldown: bool = False
    failure_kind: str | None = None
    fallback_reason: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "attempted": self.attempted,
            "selected": self.selected,
            "fallback": self.fallback,
            "provider": self.provider,
            "latency_ms": self.latency_ms,
            "profile": self.profile,
            "skipped_due_to_cooldown": self.skipped_due_to_cooldown,
            "failure_kind": self.failure_kind,
            "fallback_reason": self.fallback_reason,
        }


@dataclass(frozen=True)
class ReflectionAssessment:
    verdict: str
    score: float
    reason: str
    lesson: str | None
    signals: tuple[str, ...]
    provider: str
    local_score: float
    quality_score: float
    quality_label: str
    latency_ms: int
    gate: ReflectionGateTrace
    status: str = "assessed"

    @property
    def should_suggest(self) -> bool:
        return self.verdict == "suggest" and bool(self.lesson)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": REFLECTION_SCHEMA_VERSION,
            "verdict": self.verdict,
            "score": round(self.score, 2),
            "reason": self.reason,
            "lesson": self.lesson,
            "signals": list(self.signals),
            "provider": self.provider,
            "local_score": round(self.local_score, 2),
            "quality_score": round(self.quality_score, 2),
            "quality_label": self.quality_label,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "gate": self.gate.to_payload(),
        }


class ReflectionSessionStore:
    def __init__(
        self,
        home: Path,
        *,
        now: Callable[[], datetime] | None = None,
        fallback_cooldown_seconds: int = DEFAULT_FALLBACK_COOLDOWN_SECONDS,
    ) -> None:
        self.path = home.expanduser().resolve() / "runtime" / "reflection_sessions.json"
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.fallback_cooldown_seconds = max(fallback_cooldown_seconds, 1)

    def already_suggested(
        self,
        *,
        context: ProjectContext,
        session_id: str | None = None,
    ) -> bool:
        active_session = current_session_id(session_id)
        record = self._records().get(_session_key(context, active_session))
        if not isinstance(record, dict):
            return False
        if active_session:
            return True
        emitted_at = _parse_datetime(record.get("emitted_at"))
        return bool(
            emitted_at
            and emitted_at + timedelta(seconds=self.fallback_cooldown_seconds) > self._now()
        )

    def record(
        self,
        *,
        context: ProjectContext,
        pending_draft_id: str | None,
        session_id: str | None = None,
    ) -> None:
        active_session = current_session_id(session_id)
        records = self._prune_records(self._records())
        records[_session_key(context, active_session)] = {
            "project_id": reflection_project_id(context),
            "scope": "session" if active_session else "time",
            "emitted_at": self._now().isoformat(),
            "pending_draft_id": pending_draft_id,
        }
        output = {
            "schema_version": REFLECTION_SESSION_SCHEMA_VERSION,
            "records": records,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def _prune_records(self, records: dict[str, object]) -> dict[str, object]:
        cutoff = self._now() - timedelta(days=SESSION_RECORD_RETENTION_DAYS)
        return {
            key: value
            for key, value in records.items()
            if not isinstance(value, dict)
            or (emitted_at := _parse_datetime(value.get("emitted_at"))) is None
            or emitted_at >= cutoff
        }

    def _records(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        records = payload.get("records") if isinstance(payload, dict) else None
        return dict(records) if isinstance(records, dict) else {}


def assess_reflection(
    summary: str,
    *,
    signals: Iterable[str],
    context: ProjectContext,
    semantic_mode: str = "heuristic",
    llm_profile: str | None = None,
    llm_config_path: Path | None = None,
    state_home: Path | None = None,
) -> ReflectionAssessment:
    started = time.perf_counter()
    cleaned = _clean_summary(summary)
    normalized_signals = _normalize_signals(signals)
    candidate = reflection_candidate(cleaned)
    draft = draft_memory_heuristic(
        candidate,
        context=context,
        topic=None,
        kind=None,
        max_chars=420,
    )
    signal_score = min(sum(_SIGNAL_WEIGHTS[item] for item in normalized_signals), 0.72)
    verified_pair = (
        "verified_outcome" in normalized_signals
        and bool(set(normalized_signals) - {"verified_outcome"})
    )
    local_score = min(
        0.08 + signal_score + 0.30 * draft.quality_score + (0.10 if verified_pair else 0.0),
        0.98,
    )
    hard_rejection = _hard_rejection_reason(
        cleaned,
        signals=normalized_signals,
        quality_label=draft.quality_label,
    )
    if hard_rejection:
        return _local_assessment(
            verdict="abstain",
            score=min(local_score, 0.39),
            reason=hard_rejection,
            lesson=None,
            signals=normalized_signals,
            draft_quality=draft.quality_score,
            draft_label=draft.quality_label,
            started=started,
            mode=semantic_mode,
        )

    local_verdict = "suggest" if local_score >= 0.65 else "ambiguous" if local_score >= 0.48 else "abstain"
    if semantic_mode == "heuristic" or (semantic_mode == "hybrid" and local_verdict != "ambiguous"):
        return _local_assessment(
            verdict=local_verdict if local_verdict != "ambiguous" else "abstain",
            score=local_score,
            reason=(
                "Concrete reusable evidence passed the local reflection policy."
                if local_verdict == "suggest"
                else "The reflection did not have enough local evidence to interrupt the user."
            ),
            lesson=candidate if local_verdict == "suggest" else None,
            signals=normalized_signals,
            draft_quality=draft.quality_score,
            draft_label=draft.quality_label,
            started=started,
            mode=semantic_mode,
        )

    profile = _active_profile_name(llm_profile, llm_config_path)
    health_store = GateHealthStore(state_home) if state_home else None
    health = health_store.get(profile) if health_store else None
    if health and health.cooling_down:
        fallback_suggest = local_verdict == "suggest"
        return ReflectionAssessment(
            verdict="suggest" if fallback_suggest else "abstain",
            score=local_score,
            reason=(
                "The optional reflection gate is cooling down; used the local decision."
                if fallback_suggest
                else "The optional reflection gate is cooling down; local precision fallback abstained."
            ),
            lesson=candidate if fallback_suggest else None,
            signals=normalized_signals,
            provider="heuristic_fallback",
            local_score=local_score,
            quality_score=draft.quality_score,
            quality_label=draft.quality_label,
            latency_ms=_elapsed_ms(started),
            gate=ReflectionGateTrace(
                mode=semantic_mode,
                attempted=False,
                selected=False,
                fallback=True,
                provider="openai-compatible",
                latency_ms=0,
                profile=profile,
                skipped_due_to_cooldown=True,
                failure_kind=health.last_failure_kind,
            ),
        )

    gate_started = time.perf_counter()
    try:
        llm_result = _assess_with_llm(
            summary=cleaned,
            signals=normalized_signals,
            context=context,
            profile=llm_profile,
            config_path=llm_config_path,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        failure_kind = _failure_kind(exc)
        if health_store:
            health_store.record_failure(profile, failure_kind=failure_kind)
        fallback_suggest = local_verdict == "suggest"
        return ReflectionAssessment(
            verdict="suggest" if fallback_suggest else "abstain",
            score=local_score,
            reason=(
                "The optional reflection gate failed; used the high-confidence local decision."
                if fallback_suggest
                else "The optional reflection gate failed; local precision fallback abstained."
            ),
            lesson=candidate if fallback_suggest else None,
            signals=normalized_signals,
            provider="heuristic_fallback",
            local_score=local_score,
            quality_score=draft.quality_score,
            quality_label=draft.quality_label,
            latency_ms=_elapsed_ms(started),
            gate=ReflectionGateTrace(
                mode=semantic_mode,
                attempted=True,
                selected=False,
                fallback=True,
                provider="openai-compatible",
                latency_ms=_elapsed_ms(gate_started),
                profile=profile,
                failure_kind=failure_kind,
                fallback_reason=_safe_reason(exc),
            ),
        )

    if health_store:
        health_store.record_success(profile)
    verdict = "suggest" if llm_result["worth_remembering"] else "abstain"
    lesson = llm_result["lesson"] if verdict == "suggest" else None
    return ReflectionAssessment(
        verdict=verdict,
        score=llm_result["score"],
        reason=llm_result["reason"],
        lesson=lesson,
        signals=normalized_signals,
        provider="llm_assisted",
        local_score=local_score,
        quality_score=draft.quality_score,
        quality_label=draft.quality_label,
        latency_ms=_elapsed_ms(started),
        gate=ReflectionGateTrace(
            mode=semantic_mode,
            attempted=True,
            selected=True,
            fallback=False,
            provider="openai-compatible",
            latency_ms=_elapsed_ms(gate_started),
            profile=profile,
        ),
    )


def suppress_for_session(assessment: ReflectionAssessment) -> ReflectionAssessment:
    return replace(
        assessment,
        verdict="abstain",
        reason="A proactive memory suggestion was already shown in this coding-agent task.",
        lesson=None,
        status="session_limit",
    )


def reflection_trace_payload(
    *,
    assessment: ReflectionAssessment,
    summary: str,
    context: ProjectContext,
    action: str,
    status: str,
    pending_draft_id: str | None,
) -> dict[str, object]:
    summary_hash = hashlib.sha256(_clean_summary(summary).encode("utf-8")).hexdigest()[:20]
    return {
        "schema_version": REFLECTION_TRACE_SCHEMA_VERSION,
        "context": {
            "project_id": reflection_project_id(context),
            "repo_name": context.repo_name,
        },
        "input": {
            "summary_chars": len(_clean_summary(summary)),
            "summary_hash": summary_hash,
            "signals": list(assessment.signals),
        },
        "assessment": {
            key: value
            for key, value in assessment.to_payload().items()
            if key != "lesson"
        },
        "outcome": {
            "action": action,
            "status": status,
            "pending_draft_id": pending_draft_id,
        },
    }


def _local_assessment(
    *,
    verdict: str,
    score: float,
    reason: str,
    lesson: str | None,
    signals: tuple[str, ...],
    draft_quality: float,
    draft_label: str,
    started: float,
    mode: str,
) -> ReflectionAssessment:
    return ReflectionAssessment(
        verdict=verdict,
        score=score,
        reason=reason,
        lesson=lesson,
        signals=signals,
        provider="heuristic",
        local_score=score,
        quality_score=draft_quality,
        quality_label=draft_label,
        latency_ms=_elapsed_ms(started),
        gate=ReflectionGateTrace(
            mode=mode,
            attempted=False,
            selected=False,
            fallback=False,
            provider="local",
            latency_ms=0,
        ),
    )


def _normalize_signals(signals: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(str(item).strip().lower() for item in signals if str(item).strip()))
    invalid = sorted(set(normalized) - ALLOWED_REFLECTION_SIGNALS)
    if invalid:
        raise ValueError(f"unsupported reflection signals: {', '.join(invalid)}")
    return normalized


def _clean_summary(summary: str) -> str:
    cleaned = re.sub(r"\s+", " ", summary or "").strip()
    if not cleaned:
        raise ValueError("reflection summary cannot be empty")
    if len(cleaned) > REFLECTION_SUMMARY_LIMIT:
        raise ValueError(f"reflection summary must be at most {REFLECTION_SUMMARY_LIMIT} characters")
    return cleaned


def reflection_candidate(summary: str) -> str:
    cleaned = _clean_summary(summary)
    sentences = [item.strip() for item in re.split(r"(?<=[。！？.!?])\s*", cleaned) if item.strip()]
    action_markers = (
        " should ", " must ", " first ", " avoid ", " verify ", " prefer ", " use ",
        "下次", "应该", "必须", "先", "避免", "不要", "验证", "优先", "使用",
    )
    ranked = sorted(
        enumerate(sentences),
        key=lambda item: (
            any(marker in f" {item[1].lower()} " for marker in action_markers),
            item[0],
        ),
        reverse=True,
    )
    selected = ranked[0][1] if ranked else cleaned
    return selected[:420].rstrip()


def _hard_rejection_reason(
    summary: str,
    *,
    signals: tuple[str, ...],
    quality_label: str,
) -> str | None:
    if not signals:
        return "No concrete evidence signal was supplied."
    if len(summary) < 28:
        return "The reflection is too short to form a reusable, project-specific lesson."
    if quality_label == "reject" and not ({"correction", "verified_entrypoint", "verified_outcome"} & set(signals)):
        return "The reflection contains no actionable or verified workflow detail."
    lower = summary.lower()
    transient = (
        "spelling",
        "typo",
        "formatting",
        "temporary network",
        "transient network",
        "拼写",
        "格式错误",
        "一次性网络",
        "临时网络",
    )
    if any(value in lower for value in transient):
        return "The reflection describes a routine transient mistake rather than a reusable workflow lesson."
    generic = (
        "be careful", "check the code", "fix the bug", "try again",
        "仔细检查", "检查代码", "修复问题", "再试一次",
    )
    if any(value in lower for value in generic) and len(summary) < 90:
        return "The reflection is generic and not reusable enough to interrupt the user."
    return None


def _assess_with_llm(
    *,
    summary: str,
    signals: tuple[str, ...],
    context: ProjectContext,
    profile: str | None,
    config_path: Path | None,
) -> dict[str, Any]:
    config = (
        OpenAICompatibleConfig.from_profile(profile, config_path=config_path, timeout_seconds=REFLECTION_TIMEOUT_SECONDS)
        if profile
        else OpenAICompatibleConfig.from_default_profile(config_path=config_path, timeout_seconds=REFLECTION_TIMEOUT_SECONDS)
    )
    payload = {
        "task_reflection": sanitize_llm_text(summary, limit=600),
        "evidence_signals": list(signals),
        "context": {"has_git_project": bool(context.git_root)},
    }
    completion = chat_completion(
        config=config,
        messages=[
            {"role": "system", "content": _REFLECTION_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    result = loads_json_object(completion)
    worth = result.get("worth_remembering")
    if not isinstance(worth, bool):
        raise ValueError("LLM reflection gate returned invalid worth_remembering")
    try:
        score = float(result.get("score"))
    except (TypeError, ValueError) as exc:
        raise ValueError("LLM reflection gate returned invalid score") from exc
    if not 0.0 <= score <= 1.0:
        raise ValueError("LLM reflection gate score must be between 0 and 1")
    lesson = re.sub(r"\s+", " ", str(result.get("lesson") or "")).strip()[:420]
    reason = re.sub(r"\s+", " ", str(result.get("reason") or "")).strip()[:180]
    if worth and not lesson:
        raise ValueError("LLM reflection gate selected a candidate without a lesson")
    return {
        "worth_remembering": worth,
        "score": score,
        "lesson": lesson,
        "reason": reason or "Optional semantic reflection decision.",
    }


def _active_profile_name(profile: str | None, config_path: Path | None) -> str:
    if profile:
        return profile
    try:
        settings = load_semantic_config(config_path=config_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return "default"
    return str(settings.get("active_profile") or "default")


def _failure_kind(exc: Exception) -> str:
    text = str(exc).lower()
    if "429" in text or "rate limit" in text:
        return "rate_limited"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "requires" in text or "not found" in text or "environment" in text:
        return "not_configured"
    return "provider_error"


def _safe_reason(exc: Exception) -> str:
    return sanitize_llm_text(str(exc), limit=180)


def _elapsed_ms(started: float) -> int:
    return max(int(round((time.perf_counter() - started) * 1000)), 0)


def reflection_project_id(context: ProjectContext) -> str:
    if context.canonical_repo_id:
        return context.canonical_repo_id
    root = context.git_root or context.cwd
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"local:{digest}"


def _session_key(context: ProjectContext, session_id: str | None) -> str:
    base = reflection_project_id(context)
    if not session_id:
        return f"{base}:time"
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:20]
    return f"{base}:session:{digest}"


def _parse_datetime(value: object) -> datetime | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


_REFLECTION_SYSTEM_PROMPT = """
You are MemAgent's selective task-reflection gate for coding-agent workflow memory.
Return only one JSON object with this shape:
{
  "worth_remembering": true,
  "score": 0.0,
  "lesson": "one concise, actionable, reusable lesson",
  "reason": "one short reason"
}

Suggest only stable lessons that would shorten a future coding or debugging task:
a corrected assumption, verified entrypoint, costly detour with a shorter path,
repeatable workflow, or stable project boundary. Reject routine edits, transient
errors, unverified guesses, generic advice, and temporary task status. Never
request more context. Do not invent identifiers or facts. User confirmation is
still required before durable storage.
""".strip()
