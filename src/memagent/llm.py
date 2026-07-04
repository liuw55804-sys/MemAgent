from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib import error, request


LLM_DOCTOR_SCHEMA_VERSION = "memagent.llm_doctor.v1"
SUPPORTED_LLM_PROVIDERS = {"openai-compatible"}
DEFAULT_LLM_PROVIDERS_PATH = Path("~/.memagent/llm_providers.local.json")


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls, *, timeout_seconds: int = 30) -> "OpenAICompatibleConfig":
        base_url = os.environ.get("MEMAGENT_LLM_BASE_URL", "").strip()
        api_key = os.environ.get("MEMAGENT_LLM_API_KEY", "").strip()
        model = os.environ.get("MEMAGENT_LLM_MODEL", "").strip()
        if not base_url or not api_key or not model:
            raise ValueError(
                "openai-compatible provider requires MEMAGENT_LLM_BASE_URL, "
                "MEMAGENT_LLM_API_KEY, and MEMAGENT_LLM_MODEL"
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
        profile_payload = load_llm_profile(profile, config_path=config_path)
        base_url = str(profile_payload.get("base_url") or "").strip()
        api_key = str(profile_payload.get("api_key") or "").strip()
        model = str(profile_payload.get("model") or "").strip()
        if not base_url or not api_key or not model:
            raise ValueError(
                f"profile {profile!r} requires base_url, api_key, and model"
            )
        return cls(base_url=base_url, api_key=api_key, model=model, timeout_seconds=timeout_seconds)

    @property
    def chat_completions_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


@dataclass(frozen=True)
class LlmDoctorResult:
    provider: str
    configured: bool
    live_checked: bool
    live_ok: bool | None
    status: str
    base_url: str | None
    model: str | None
    chat_completions_url: str | None
    missing_env: tuple[str, ...]
    api_key_set: bool
    profile: str | None = None
    config_path: str | None = None
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": LLM_DOCTOR_SCHEMA_VERSION,
            "provider": self.provider,
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
            "profile": self.profile,
            "config_path": self.config_path,
        }


def check_llm_provider(
    *,
    provider: str = "openai-compatible",
    profile: str | None = None,
    config_path: Path | None = None,
    check_live: bool = False,
    timeout_seconds: int = 30,
) -> LlmDoctorResult:
    if provider not in SUPPORTED_LLM_PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(SUPPORTED_LLM_PROVIDERS)}")
    if profile:
        return _check_profile_provider(
            provider=provider,
            profile=profile,
            config_path=config_path,
            check_live=check_live,
            timeout_seconds=timeout_seconds,
        )
    missing = _missing_openai_compatible_env()
    if missing:
        return LlmDoctorResult(
            provider=provider,
            configured=False,
            live_checked=False,
            live_ok=None,
            status="not_configured",
            base_url=os.environ.get("MEMAGENT_LLM_BASE_URL") or None,
            model=os.environ.get("MEMAGENT_LLM_MODEL") or None,
            chat_completions_url=None,
            missing_env=tuple(missing),
            api_key_set=bool(os.environ.get("MEMAGENT_LLM_API_KEY", "").strip()),
            profile=None,
            config_path=None,
            error="missing required environment variables",
        )
    config = OpenAICompatibleConfig.from_env(timeout_seconds=timeout_seconds)
    if not check_live:
        return LlmDoctorResult(
            provider=provider,
            configured=True,
            live_checked=False,
            live_ok=None,
            status="configured",
            base_url=config.base_url,
            model=config.model,
            chat_completions_url=config.chat_completions_url,
            missing_env=(),
            api_key_set=True,
            profile=None,
            config_path=None,
        )
    return _live_check_result(
        provider=provider,
        config=config,
        profile=None,
        config_path=None,
    )


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


def _check_profile_provider(
    *,
    provider: str,
    profile: str,
    config_path: Path | None,
    check_live: bool,
    timeout_seconds: int,
) -> LlmDoctorResult:
    path = (config_path or DEFAULT_LLM_PROVIDERS_PATH).expanduser()
    try:
        config = OpenAICompatibleConfig.from_profile(
            profile,
            config_path=path,
            timeout_seconds=timeout_seconds,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return LlmDoctorResult(
            provider=provider,
            configured=False,
            live_checked=False,
            live_ok=None,
            status="not_configured",
            base_url=None,
            model=None,
            chat_completions_url=None,
            missing_env=(),
            api_key_set=False,
            profile=profile,
            config_path=str(path),
            error=str(exc),
        )
    if not check_live:
        return LlmDoctorResult(
            provider=provider,
            configured=True,
            live_checked=False,
            live_ok=None,
            status="configured",
            base_url=config.base_url,
            model=config.model,
            chat_completions_url=config.chat_completions_url,
            missing_env=(),
            api_key_set=True,
            profile=profile,
            config_path=str(path),
        )
    return _live_check_result(
        provider=provider,
        config=config,
        profile=profile,
        config_path=str(path),
    )


def _live_check_result(
    *,
    provider: str,
    config: OpenAICompatibleConfig,
    profile: str | None,
    config_path: str | None,
) -> LlmDoctorResult:
    try:
        content = chat_completion(
            config=config,
            messages=[
                {
                    "role": "system",
                    "content": "Return only a short plain text health check response.",
                },
                {
                    "role": "user",
                    "content": "Reply with: memagent-ok",
                },
            ],
        )
    except ValueError as exc:
        return LlmDoctorResult(
            provider=provider,
            configured=True,
            live_checked=True,
            live_ok=False,
            status="live_failed",
            base_url=config.base_url,
            model=config.model,
            chat_completions_url=config.chat_completions_url,
            missing_env=(),
            api_key_set=True,
            profile=profile,
            config_path=config_path,
            error=str(exc),
        )
    return LlmDoctorResult(
        provider=provider,
        configured=True,
        live_checked=True,
        live_ok=True,
        status="live_ok",
        base_url=config.base_url,
        model=config.model,
        chat_completions_url=config.chat_completions_url,
        missing_env=(),
        api_key_set=True,
        profile=profile,
        config_path=config_path,
        error=None if content.strip() else "empty response",
    )


def render_llm_doctor(result: LlmDoctorResult) -> str:
    payload = result.to_payload()
    lines = [
        "[MemAgent LLM doctor]",
        f"- provider: {payload['provider']}",
        f"- status: {payload['status']}",
        f"- configured: {_yes_no(payload['configured'])}",
        f"- api key set: {_yes_no(payload['api_key_set'])}",
        f"- live checked: {_yes_no(payload['live_checked'])}",
    ]
    if payload["live_checked"]:
        lines.append(f"- live ok: {_yes_no(payload['live_ok'])}")
    if payload["profile"]:
        lines.append(f"- profile: {payload['profile']}")
    if payload["config_path"]:
        lines.append(f"- config: {payload['config_path']}")
    if payload["base_url"]:
        lines.append(f"- base url: {payload['base_url']}")
    if payload["model"]:
        lines.append(f"- model: {payload['model']}")
    if payload["chat_completions_url"]:
        lines.append(f"- chat completions: {payload['chat_completions_url']}")
    if payload["missing_env"]:
        lines.append(f"- missing env: {', '.join(payload['missing_env'])}")
    if payload["error"]:
        lines.append(f"- error: {payload['error']}")
    if not payload["configured"]:
        lines.extend(
            [
                "",
                "Set these environment variables before using --provider openai-compatible:",
                "- MEMAGENT_LLM_BASE_URL",
                "- MEMAGENT_LLM_API_KEY",
                "- MEMAGENT_LLM_MODEL",
            ]
        )
    elif not payload["live_checked"]:
        lines.append("- next: rerun with --check-live when you want to test the actual API call.")
    return "\n".join(lines)


def chat_completion(*, config: OpenAICompatibleConfig, messages: list[dict[str, str]]) -> str:
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": 0,
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        config.chat_completions_url,
        data=data,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=config.timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"LLM provider request failed: HTTP {exc.code}: {body[:500]}") from exc
    except error.URLError as exc:
        raise ValueError(f"LLM provider request failed: {exc}") from exc
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


def _missing_openai_compatible_env() -> list[str]:
    return [
        name
        for name in (
            "MEMAGENT_LLM_BASE_URL",
            "MEMAGENT_LLM_API_KEY",
            "MEMAGENT_LLM_MODEL",
        )
        if not os.environ.get(name, "").strip()
    ]


def _yes_no(value: object) -> str:
    return "yes" if bool(value) else "no"
