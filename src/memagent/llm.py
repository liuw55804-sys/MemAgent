from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib import error, request


LLM_DOCTOR_SCHEMA_VERSION = "memagent.llm_doctor.v1"
CONFIG_SCHEMA_VERSION = "memagent.config.v1"
SUPPORTED_LLM_PROVIDERS = {"openai-compatible"}
SEMANTIC_MODES = {"heuristic", "llm", "hybrid"}
DEFAULT_LLM_PROVIDERS_PATH = Path("~/.memagent/llm_providers.local.json")
DEFAULT_CONFIG_PATH = Path("~/.memagent/config.json")


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls, *, timeout_seconds: int = 30, allow_no_key: bool = False) -> "OpenAICompatibleConfig":
        base_url = os.environ.get("MEMAGENT_LLM_BASE_URL", "").strip()
        api_key = os.environ.get("MEMAGENT_LLM_API_KEY", "").strip()
        model = os.environ.get("MEMAGENT_LLM_MODEL", "").strip()
        if not base_url or not model or (not api_key and not allow_no_key):
            raise ValueError(
                "openai-compatible provider requires MEMAGENT_LLM_BASE_URL, "
                "MEMAGENT_LLM_MODEL, and MEMAGENT_LLM_API_KEY unless no-key mode is enabled"
            )
        return cls(base_url=base_url, api_key=api_key, model=model, timeout_seconds=timeout_seconds)

    @classmethod
    def from_profile(
        cls,
        profile: str,
        *,
        config_path: Path | None = None,
        timeout_seconds: int = 30,
    ) -> "OpenAICompatibleConfig":
        profile_payload, _ = _load_profile_payload(profile, config_path=config_path)
        return _config_from_profile_payload(profile_payload, timeout_seconds=timeout_seconds)

    @classmethod
    def from_default_profile(
        cls,
        *,
        config_path: Path | None = None,
        timeout_seconds: int = 30,
    ) -> "OpenAICompatibleConfig":
        settings = load_semantic_config(config_path=config_path)
        profile = str(settings.get("active_profile") or "default")
        profiles = settings.get("profiles")
        if not isinstance(profiles, dict) or not isinstance(profiles.get(profile), dict):
            return cls.from_env(timeout_seconds=timeout_seconds)
        return _config_from_profile_payload(profiles[profile], timeout_seconds=timeout_seconds)

    @property
    def chat_completions_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


@dataclass(frozen=True)
class LlmDoctorResult:
    provider: str
    mode: str
    configured: bool
    live_checked: bool
    live_ok: bool | None
    status: str
    base_url: str | None
    model: str | None
    chat_completions_url: str | None
    missing_env: tuple[str, ...]
    api_key_set: bool
    api_key_env: str | None = None
    profile: str | None = None
    config_path: str | None = None
    allow_no_key: bool = False
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": LLM_DOCTOR_SCHEMA_VERSION,
            "provider": self.provider,
            "mode": self.mode,
            "configured": self.configured,
            "live_checked": self.live_checked,
            "live_ok": self.live_ok,
            "status": self.status,
            "base_url": self.base_url,
            "model": self.model,
            "chat_completions_url": self.chat_completions_url,
            "missing_env": list(self.missing_env),
            "error": self.error,
            "api_key_set": self.api_key_set,
            "api_key_env": self.api_key_env,
            "profile": self.profile,
            "config_path": self.config_path,
            "allow_no_key": self.allow_no_key,
            "privacy": "Only short sanitized task summaries and draft candidates are eligible for LLM requests; API keys are never printed or stored by configure.",
        }


def default_config_path() -> Path:
    return Path(os.environ.get("MEMAGENT_CONFIG_PATH", str(DEFAULT_CONFIG_PATH))).expanduser()


def default_semantic_mode() -> str:
    configured = os.environ.get("MEMAGENT_SEMANTIC_MODE", "").strip().lower()
    if configured in SEMANTIC_MODES:
        return configured
    settings = load_semantic_config()
    mode = str(settings.get("semantic_mode") or "heuristic").lower()
    return mode if mode in SEMANTIC_MODES else "heuristic"


def load_semantic_config(*, config_path: Path | None = None) -> dict[str, Any]:
    path = (config_path or default_config_path()).expanduser()
    if not path.exists():
        return {"schema_version": CONFIG_SCHEMA_VERSION, "semantic_mode": "heuristic", "active_profile": "default", "profiles": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"MemAgent config must be a JSON object: {path}")
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "semantic_mode": str(payload.get("semantic_mode") or "heuristic").lower(),
        "active_profile": str(payload.get("active_profile") or "default"),
        "profiles": payload.get("profiles") if isinstance(payload.get("profiles"), dict) else {},
    }


def save_semantic_config(settings: dict[str, Any], *, config_path: Path | None = None) -> Path:
    path = (config_path or default_config_path()).expanduser()
    normalized = {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "semantic_mode": _validate_mode(str(settings.get("semantic_mode") or "heuristic")),
        "active_profile": str(settings.get("active_profile") or "default"),
        "profiles": settings.get("profiles") if isinstance(settings.get("profiles"), dict) else {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def configure_semantic_mode(
    *,
    mode: str,
    profile: str = "default",
    base_url: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
    allow_no_key: bool = False,
    config_path: Path | None = None,
) -> Path:
    normalized_mode = _validate_mode(mode)
    settings = load_semantic_config(config_path=config_path)
    settings["semantic_mode"] = normalized_mode
    if normalized_mode != "heuristic":
        if not base_url or not model:
            raise ValueError("LLM configuration requires base_url and model")
        profiles = settings["profiles"]
        profiles[profile] = {
            "provider": "openai-compatible",
            "base_url": base_url,
            "model": model,
            "api_key_env": api_key_env or "MEMAGENT_LLM_API_KEY",
            "allow_no_key": bool(allow_no_key),
        }
        settings["active_profile"] = profile
    return save_semantic_config(settings, config_path=config_path)


def activate_semantic_profile(
    *,
    mode: str,
    profile: str,
    config_path: Path | None = None,
) -> Path:
    normalized_mode = _validate_mode(mode)
    if normalized_mode == "heuristic":
        raise ValueError("--use-profile requires --mode llm or --mode hybrid")
    settings = load_semantic_config(config_path=config_path)
    profiles = settings.get("profiles")
    if not isinstance(profiles, dict) or not isinstance(profiles.get(profile), dict):
        raise ValueError(f"configured profile not found: {profile}")
    settings["semantic_mode"] = normalized_mode
    settings["active_profile"] = profile
    return save_semantic_config(settings, config_path=config_path)


def check_llm_provider(
    *,
    provider: str = "openai-compatible",
    profile: str | None = None,
    config_path: Path | None = None,
    check_live: bool = False,
    timeout_seconds: int = 30,
    mode: str | None = None,
) -> LlmDoctorResult:
    if provider not in SUPPORTED_LLM_PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(SUPPORTED_LLM_PROVIDERS)}")
    semantic_mode = _validate_mode(mode or default_semantic_mode())
    selected_profile = profile
    source_path: Path | None = config_path
    profile_payload: dict[str, Any] | None = None
    api_key_env = "MEMAGENT_LLM_API_KEY"
    try:
        if profile:
            profile_payload, source_path = _load_profile_payload(profile, config_path=config_path)
            api_key_env = _profile_api_key_env(profile_payload)
            config = _config_from_profile_payload(profile_payload, timeout_seconds=timeout_seconds)
        else:
            settings = load_semantic_config(config_path=config_path)
            selected_profile = str(settings.get("active_profile") or "default")
            profiles = settings.get("profiles")
            if isinstance(profiles, dict) and isinstance(profiles.get(selected_profile), dict):
                profile_payload = profiles[selected_profile]
                api_key_env = _profile_api_key_env(profile_payload)
                config = _config_from_profile_payload(profile_payload, timeout_seconds=timeout_seconds)
                source_path = config_path or default_config_path()
            else:
                config = OpenAICompatibleConfig.from_env(timeout_seconds=timeout_seconds)
                selected_profile = None
                source_path = None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return LlmDoctorResult(
            provider=provider, mode=semantic_mode, configured=False, live_checked=False,
            live_ok=None, status="not_configured", base_url=None, model=None,
            chat_completions_url=None,
            missing_env=tuple(_missing_profile_env(profile_payload, api_key_env)),
            api_key_set=bool(os.environ.get(api_key_env, "").strip()),
            api_key_env=api_key_env,
            profile=selected_profile, config_path=str(source_path) if source_path else None,
            error=_safe_error(str(exc)),
        )
    allow_no_key = bool(profile_payload and profile_payload.get("allow_no_key"))
    result = LlmDoctorResult(
        provider=provider, mode=semantic_mode, configured=True, live_checked=False,
        live_ok=None, status="configured", base_url=config.base_url, model=config.model,
        chat_completions_url=config.chat_completions_url, missing_env=(),
        api_key_set=bool(config.api_key), api_key_env=api_key_env, profile=selected_profile,
        config_path=str(source_path) if source_path else None, allow_no_key=allow_no_key,
    )
    if not check_live:
        return result
    return _live_check_result(result=result, config=config)


def load_llm_profile(profile: str, *, config_path: Path | None = None) -> dict[str, Any]:
    path = (config_path or DEFAULT_LLM_PROVIDERS_PATH).expanduser()
    payload = json.loads(path.read_text(encoding="utf-8"))
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, dict):
        raise ValueError(f"LLM provider config has no profiles object: {path}")
    profile_payload = profiles.get(profile)
    if not isinstance(profile_payload, dict):
        raise ValueError(f"LLM provider profile not found: {profile}")
    provider = str(profile_payload.get("provider") or "openai-compatible")
    if provider != "openai-compatible":
        raise ValueError(f"profile {profile!r} provider must be openai-compatible")
    return profile_payload


def _load_profile_payload(profile: str, *, config_path: Path | None = None) -> tuple[dict[str, Any], Path]:
    """Read a named profile from the new config first, then the legacy file."""
    primary_path = (config_path or default_config_path()).expanduser()
    if primary_path.exists():
        settings = load_semantic_config(config_path=primary_path)
        profiles = settings.get("profiles")
        payload = profiles.get(profile) if isinstance(profiles, dict) else None
        if isinstance(payload, dict):
            _validate_profile_provider(profile, payload)
            return payload, primary_path
        if config_path is not None:
            raise ValueError(f"LLM provider profile not found: {profile}")

    legacy_path = DEFAULT_LLM_PROVIDERS_PATH.expanduser()
    if legacy_path.exists():
        return load_llm_profile(profile, config_path=legacy_path), legacy_path
    raise ValueError(f"LLM provider profile not found: {profile}")


def render_llm_doctor(result: LlmDoctorResult) -> str:
    payload = result.to_payload()
    lines = [
        "[MemAgent LLM doctor]",
        f"- semantic mode: {payload['mode']}",
        f"- provider: {payload['provider']}",
        f"- status: {payload['status']}",
        f"- configured: {_yes_no(payload['configured'])}",
        f"- API key environment: {payload['api_key_env'] or 'not applicable'}",
        f"- API key environment present: {_yes_no(payload['api_key_set'])}",
        f"- no-key local service: {_yes_no(payload['allow_no_key'])}",
        f"- live checked: {_yes_no(payload['live_checked'])}",
    ]
    if payload["profile"]:
        lines.append(f"- profile: {payload['profile']}")
    if payload["base_url"]:
        lines.append(f"- base URL: {payload['base_url']}")
    if payload["model"]:
        lines.append(f"- model: {payload['model']}")
    if payload["missing_env"]:
        lines.append(f"- missing environment variables: {', '.join(payload['missing_env'])}")
    if payload["error"]:
        lines.append(f"- detail: {payload['error']}")
    lines.extend(["", "- privacy: only sanitized short task summaries and draft candidates may be sent; keys and full transcripts are never printed or stored."])
    if not payload["configured"]:
        lines.append("- next: run `memagent configure` to stay local-only or add an optional OpenAI-compatible profile.")
        if payload["missing_env"]:
            lines.append(f"- next: set {' and '.join(payload['missing_env'])} in your shell, then rerun `memagent llm doctor`.")
    elif not payload["live_checked"]:
        lines.append("- next: add --check-live only when you want to test a real provider request.")
    return "\n".join(lines)


def chat_completion(*, config: OpenAICompatibleConfig, messages: list[dict[str, str]]) -> str:
    payload = {"model": config.model, "messages": messages, "temperature": 0}
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    req = request.Request(config.chat_completions_url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=config.timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ValueError(_safe_error(f"LLM provider request failed: HTTP {exc.code}: {body[:500]}")) from exc
    except error.URLError as exc:
        raise ValueError(_safe_error(f"LLM provider request failed: {exc}")) from exc
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("LLM provider response did not include choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM provider response did not include message content")
    return content


def loads_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("LLM response must be a JSON object")
    return payload


def sanitize_llm_text(text: str, *, limit: int = 600) -> str:
    sanitized = re.sub(r"https?://[^\s]+", "<url>", text or "", flags=re.I)
    sanitized = re.sub(r"(?:~|/Users|/home|/private|/tmp)/[^\s,，。；;]+", "<path>", sanitized)
    sanitized = re.sub(r"\b(?:sk|rk|pk)[-_][A-Za-z0-9_-]{6,}\b", "<secret>", sanitized, flags=re.I)
    sanitized = re.sub(r"\b(?:token|api[_-]?key|authorization)\s*[:=]\s*[^\s,，。；;]+", "<secret>", sanitized, flags=re.I)
    sanitized = re.sub(r"\b[a-zA-Z][a-zA-Z0-9]*(?:_[a-zA-Z0-9]+)+\b", "<identifier>", sanitized)
    sanitized = re.sub(r"\b\d{6,}\b", "<number>", sanitized)
    normalized = re.sub(r"\s+", " ", sanitized).strip()
    return normalized[:limit]


def _config_from_profile_payload(payload: dict[str, Any], *, timeout_seconds: int) -> OpenAICompatibleConfig:
    base_url = str(payload.get("base_url") or "").strip()
    model = str(payload.get("model") or "").strip()
    api_key_env = _profile_api_key_env(payload)
    api_key = os.environ.get(api_key_env, "").strip()
    # Read legacy local profiles without writing keys back into the new config.
    if not api_key and payload.get("api_key"):
        api_key = str(payload["api_key"]).strip()
    allow_no_key = bool(payload.get("allow_no_key"))
    if not base_url or not model or (not api_key and not allow_no_key):
        missing = [name for name, value in (("base_url", base_url), ("model", model), (api_key_env, api_key)) if not value]
        raise ValueError(f"profile requires {', '.join(missing)} unless allow_no_key is true")
    return OpenAICompatibleConfig(base_url=base_url, api_key=api_key, model=model, timeout_seconds=timeout_seconds)


def _validate_profile_provider(profile: str, payload: dict[str, Any]) -> None:
    provider = str(payload.get("provider") or "openai-compatible")
    if provider != "openai-compatible":
        raise ValueError(f"profile {profile!r} provider must be openai-compatible")


def _missing_openai_compatible_env() -> list[str]:
    return [name for name in ("MEMAGENT_LLM_BASE_URL", "MEMAGENT_LLM_MODEL", "MEMAGENT_LLM_API_KEY") if not os.environ.get(name, "").strip()]


def _profile_api_key_env(payload: dict[str, Any]) -> str:
    return str(payload.get("api_key_env") or "MEMAGENT_LLM_API_KEY").strip()


def _missing_profile_env(payload: dict[str, Any] | None, api_key_env: str) -> list[str]:
    if payload is None:
        return _missing_openai_compatible_env()
    if bool(payload.get("allow_no_key")) or payload.get("api_key") or os.environ.get(api_key_env, "").strip():
        return []
    return [api_key_env]


def _validate_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized not in SEMANTIC_MODES:
        raise ValueError(f"semantic mode must be one of {sorted(SEMANTIC_MODES)}")
    return normalized


def _live_check_result(*, result: LlmDoctorResult, config: OpenAICompatibleConfig) -> LlmDoctorResult:
    try:
        content = chat_completion(config=config, messages=[{"role": "system", "content": "Return only a short health check response."}, {"role": "user", "content": "Reply with: memagent-ok"}])
    except ValueError as exc:
        return LlmDoctorResult(**{**result.__dict__, "live_checked": True, "live_ok": False, "status": "live_failed", "error": _safe_error(str(exc))})
    return LlmDoctorResult(**{**result.__dict__, "live_checked": True, "live_ok": bool(content.strip()), "status": "live_ok" if content.strip() else "live_failed", "error": None if content.strip() else "empty response"})


def _safe_error(value: str) -> str:
    return sanitize_llm_text(value, limit=240)


def _yes_no(value: object) -> str:
    return "yes" if bool(value) else "no"
