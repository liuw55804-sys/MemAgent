from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Callable


GATE_HEALTH_SCHEMA_VERSION = "memagent.gate_health.v1"
DEFAULT_COOLDOWN_SECONDS = 10 * 60
DEFAULT_FAILURE_THRESHOLD = 2


@dataclass(frozen=True)
class GateHealth:
    profile: str
    consecutive_failures: int
    last_failure_kind: str | None
    cooldown_until: datetime | None

    @property
    def cooling_down(self) -> bool:
        return self.cooldown_until is not None


class GateHealthStore:
    def __init__(
        self,
        home: Path,
        *,
        now: Callable[[], datetime] | None = None,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    ) -> None:
        self.path = home.expanduser().resolve() / "runtime" / "llm_gate_health.json"
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.cooldown_seconds = max(cooldown_seconds, 1)
        self.failure_threshold = max(failure_threshold, 1)

    def get(self, profile: str) -> GateHealth:
        payload = self._load()
        profiles = payload.get("profiles") if isinstance(payload.get("profiles"), dict) else {}
        value = profiles.get(profile) if isinstance(profiles.get(profile), dict) else {}
        cooldown_until = _parse_datetime(value.get("cooldown_until"))
        now = self._now()
        if cooldown_until and cooldown_until <= now:
            cooldown_until = None
        return GateHealth(
            profile=profile,
            consecutive_failures=_integer(value.get("consecutive_failures")),
            last_failure_kind=_text(value.get("last_failure_kind")),
            cooldown_until=cooldown_until,
        )

    def record_success(self, profile: str) -> GateHealth:
        self._write_profile(
            profile,
            {
                "consecutive_failures": 0,
                "last_failure_kind": None,
                "cooldown_until": None,
                "updated_at": self._now().isoformat(),
            },
        )
        return self.get(profile)

    def record_failure(self, profile: str, *, failure_kind: str) -> GateHealth:
        current = self.get(profile)
        failures = current.consecutive_failures + 1
        should_cool_down = failure_kind == "rate_limited" or failures >= self.failure_threshold
        cooldown_until = (
            self._now() + timedelta(seconds=self.cooldown_seconds)
            if should_cool_down
            else None
        )
        self._write_profile(
            profile,
            {
                "consecutive_failures": failures,
                "last_failure_kind": failure_kind,
                "cooldown_until": cooldown_until.isoformat() if cooldown_until else None,
                "updated_at": self._now().isoformat(),
            },
        )
        return self.get(profile)

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {"schema_version": GATE_HEALTH_SCHEMA_VERSION, "profiles": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": GATE_HEALTH_SCHEMA_VERSION, "profiles": {}}
        return payload if isinstance(payload, dict) else {"schema_version": GATE_HEALTH_SCHEMA_VERSION, "profiles": {}}

    def _write_profile(self, profile: str, value: dict[str, object]) -> None:
        payload = self._load()
        profiles = payload.get("profiles") if isinstance(payload.get("profiles"), dict) else {}
        profiles = dict(profiles)
        profiles[profile] = value
        output = {
            "schema_version": GATE_HEALTH_SCHEMA_VERSION,
            "profiles": profiles,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)


def _parse_datetime(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _integer(value: object) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _text(value: object) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None
