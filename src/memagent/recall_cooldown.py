from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable

from memagent.context import ProjectContext


RECALL_COOLDOWN_SCHEMA_VERSION = "memagent.recall_cooldown.v1"
DEFAULT_RECALL_COOLDOWN_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class RecallCooldownDecision:
    suppressed: bool
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
    ) -> RecallCooldownDecision:
        records = self._records()
        value = records.get(_record_key(context, memory_id))
        if not isinstance(value, dict):
            return RecallCooldownDecision(suppressed=False)
        emitted_at = _parse_datetime(value.get("emitted_at"))
        if not emitted_at or emitted_at + timedelta(seconds=self.cooldown_seconds) <= self._now():
            return RecallCooldownDecision(suppressed=False)
        previous_terms = tuple(
            str(item).strip().lower()
            for item in value.get("discriminative_terms", [])
            if str(item).strip()
        )
        current_terms = {str(item).strip().lower() for item in discriminative_terms if str(item).strip()}
        has_new_signal = bool(current_terms - set(previous_terms))
        return RecallCooldownDecision(
            suppressed=not has_new_signal,
            previous_terms=previous_terms,
            emitted_at=emitted_at,
        )

    def record(
        self,
        *,
        context: ProjectContext,
        memory_id: str,
        discriminative_terms: Iterable[str],
    ) -> None:
        payload = self._load()
        records = payload.get("records") if isinstance(payload.get("records"), dict) else {}
        records = dict(records)
        records[_record_key(context, memory_id)] = {
            "memory_id": memory_id,
            "project_id": _project_id(context),
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


def _record_key(context: ProjectContext, memory_id: str) -> str:
    return f"{_project_id(context)}:{memory_id}"


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
