from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Iterable

from memagent.context import ProjectContext


RECALL_COOLDOWN_SCHEMA_VERSION = "memagent.recall_cooldown.v2"
DEFAULT_RECALL_COOLDOWN_SECONDS = 6 * 60 * 60
SESSION_RECORD_RETENTION_DAYS = 30


@dataclass(frozen=True)
class RecallCooldownDecision:
    suppressed: bool
    scope: str
    previous_terms: tuple[str, ...] = ()
    emitted_at: datetime | None = None


class RecallCooldownStore:
    def __init__(
        self,
        home: Path,
        *,
        now: Callable[[], datetime] | None = None,
        cooldown_seconds: int = DEFAULT_RECALL_COOLDOWN_SECONDS,
    ) -> None:
        self.path = home.expanduser().resolve() / "runtime" / "recall_cooldown.json"
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.cooldown_seconds = max(cooldown_seconds, 1)

    def check(
        self,
        *,
        context: ProjectContext,
        memory_id: str,
        discriminative_terms: Iterable[str],
        session_id: str | None = None,
    ) -> RecallCooldownDecision:
        records = self._records()
        scope = "session" if session_id else "time"
        value = records.get(_record_key(context, memory_id, session_id=session_id))
        if not isinstance(value, dict):
            return RecallCooldownDecision(suppressed=False, scope=scope)
        emitted_at = _parse_datetime(value.get("emitted_at"))
        if session_id:
            return RecallCooldownDecision(
                suppressed=True,
                scope=scope,
                previous_terms=_terms(value.get("discriminative_terms")),
                emitted_at=emitted_at,
            )
        if not emitted_at or emitted_at + timedelta(seconds=self.cooldown_seconds) <= self._now():
            return RecallCooldownDecision(suppressed=False, scope=scope)
        previous_terms = _terms(value.get("discriminative_terms"))
        current_terms = {str(item).strip().lower() for item in discriminative_terms if str(item).strip()}
        has_new_signal = bool(current_terms - set(previous_terms))
        return RecallCooldownDecision(
            suppressed=not has_new_signal,
            scope=scope,
            previous_terms=previous_terms,
            emitted_at=emitted_at,
        )

    def record(
        self,
        *,
        context: ProjectContext,
        memory_id: str,
        discriminative_terms: Iterable[str],
        session_id: str | None = None,
    ) -> None:
        payload = self._load()
        records = payload.get("records") if isinstance(payload.get("records"), dict) else {}
        records = self._prune_records(dict(records))
        records[_record_key(context, memory_id, session_id=session_id)] = {
            "memory_id": memory_id,
            "project_id": _project_id(context),
            "scope": "session" if session_id else "time",
            "emitted_at": self._now().isoformat(),
            "discriminative_terms": sorted(
                {str(item).strip().lower() for item in discriminative_terms if str(item).strip()}
            ),
        }
        output = {
            "schema_version": RECALL_COOLDOWN_SCHEMA_VERSION,
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
        payload = self._load()
        return payload.get("records") if isinstance(payload.get("records"), dict) else {}

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {"schema_version": RECALL_COOLDOWN_SCHEMA_VERSION, "records": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": RECALL_COOLDOWN_SCHEMA_VERSION, "records": {}}
        return payload if isinstance(payload, dict) else {"schema_version": RECALL_COOLDOWN_SCHEMA_VERSION, "records": {}}


def current_session_id(explicit: str | None = None) -> str | None:
    return (explicit or os.environ.get("MEMAGENT_SESSION_ID") or os.environ.get("CODEX_THREAD_ID") or "").strip() or None


def _record_key(
    context: ProjectContext,
    memory_id: str,
    *,
    session_id: str | None,
) -> str:
    base = f"{_project_id(context)}:{memory_id}"
    if not session_id:
        return base
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:20]
    return f"{base}:session:{digest}"


def _project_id(context: ProjectContext) -> str:
    canonical = getattr(context, "canonical_repo_id", None)
    if canonical:
        return str(canonical)
    root = context.git_root or context.cwd
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"local:{digest}"


def _parse_datetime(value: object) -> datetime | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _terms(value: object) -> tuple[str, ...]:
    return tuple(
        str(item).strip().lower()
        for item in value
        if str(item).strip()
    ) if isinstance(value, list) else ()
