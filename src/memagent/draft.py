from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import shlex
from typing import Any

from memagent.context import ProjectContext
from memagent.llm import OpenAICompatibleConfig, chat_completion, loads_json_object
from memagent.memory import ALLOWED_KINDS, DEFAULT_DOMAIN, normalize_kind


MEMORY_DRAFT_SCHEMA_VERSION = "memagent.memory_draft.v1"
QUALITY_LABELS = {"keep", "revise", "reject"}
LLM_ASSIST_KINDS = {"preference", "decision", "workflow"}
AMBIGUOUS_QUALITY_MIN = 0.32
AMBIGUOUS_QUALITY_MAX = 0.60


@dataclass(frozen=True)
class QualityGateTrace:
    provider: str
    attempted: bool
    selected: bool
    fallback: bool
    final_source: str
    heuristic_score: float
    heuristic_label: str
    fallback_reason: str | None = None
    llm_score: float | None = None
    llm_label: str | None = None
    suggested_rewrite: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "attempted": self.attempted,
            "selected": self.selected,
            "fallback": self.fallback,
            "final_source": self.final_source,
            "heuristic_score": round(self.heuristic_score, 2),
            "heuristic_label": self.heuristic_label,
            "fallback_reason": self.fallback_reason,
            "llm_score": round(self.llm_score, 2) if self.llm_score is not None else None,
            "llm_label": self.llm_label,
            "suggested_rewrite": self.suggested_rewrite,
        }


@dataclass(frozen=True)
class MemoryDraft:
    topic: str
    kind: str
    triggers: tuple[str, ...]
    memory: str
    quality_score: float
    quality_label: str
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    source_excerpt: str
    provider: str = "heuristic"
    domain: str = DEFAULT_DOMAIN
    requires_confirmation: bool = True
    quality_gate: QualityGateTrace | None = None

    def to_payload(self, *, context: ProjectContext | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": MEMORY_DRAFT_SCHEMA_VERSION,
            "provider": self.provider,
            "domain": self.domain,
            "kind": self.kind,
            "topic": self.topic,
            "triggers": list(self.triggers),
            "memory": self.memory,
            "quality_score": round(max(min(self.quality_score, 1.0), 0.0), 2),
            "quality_label": self.quality_label,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "requires_confirmation": self.requires_confirmation,
            "source_excerpt": self.source_excerpt,
            "quality_gate": self.quality_gate.to_payload() if self.quality_gate else None,
            "suggested_remember": {
                "domain": self.domain,
                "kind": self.kind,
                "topic": self.topic,
                "triggers": list(self.triggers),
                "text": self.memory,
            },
        }
        if context is not None:
            payload["context"] = {
                "cwd": str(context.cwd),
                "git_root": str(context.git_root) if context.git_root else None,
                "branch": context.branch,
                "repo_name": context.repo_name,
            }
        return payload


def draft_memory(
    source_text: str,
    *,
    context: ProjectContext | None = None,
    provider: str = "heuristic",
    llm_profile: str | None = None,
    llm_config_path: Path | None = None,
    topic: str | None = None,
    kind: str | None = None,
    max_chars: int = 420,
) -> MemoryDraft:
    text = _clean_source(source_text)
    if not text:
        raise ValueError("memory draft source cannot be empty")
    provider = provider or "heuristic"
    if provider == "heuristic":
        return draft_memory_heuristic(text, context=context, topic=topic, kind=kind, max_chars=max_chars)
    if provider == "openai-compatible":
        return draft_memory_openai_compatible(
            text,
            context=context,
            llm_profile=llm_profile,
            llm_config_path=llm_config_path,
            topic=topic,
            kind=kind,
            max_chars=max_chars,
        )
    raise ValueError("provider must be heuristic or openai-compatible")


def draft_memory_heuristic(
    source_text: str,
    *,
    context: ProjectContext | None,
    topic: str | None,
    kind: str | None,
    max_chars: int,
) -> MemoryDraft:
    inferred_kind = normalize_kind(kind) if kind else _infer_kind(source_text)
    memory = _memory_text(source_text, max_chars=max_chars)
    triggers = _derive_triggers(" ".join([source_text, context.repo_name or ""] if context else [source_text]))
    score, label, reasons, warnings = _quality(source_text, kind=inferred_kind)
    return MemoryDraft(
        topic=topic or _derive_topic(source_text, kind=inferred_kind),
        kind=inferred_kind,
        triggers=tuple(triggers),
        memory=memory,
        quality_score=score,
        quality_label=label,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
        source_excerpt=_excerpt(source_text),
        provider="heuristic",
        quality_gate=QualityGateTrace(
            provider="heuristic",
            attempted=False,
            selected=False,
            fallback=False,
            final_source="heuristic",
            heuristic_score=score,
            heuristic_label=label,
        ),
    )


def draft_memory_openai_compatible(
    source_text: str,
    *,
    context: ProjectContext | None,
    llm_profile: str | None,
    llm_config_path: Path | None,
    topic: str | None,
    kind: str | None,
    max_chars: int,
) -> MemoryDraft:
    baseline = draft_memory_heuristic(
        source_text,
        context=context,
        topic=topic,
        kind=kind,
        max_chars=max_chars,
    )
    if not _should_use_llm_quality_gate(baseline, source_text):
        return replace(
            baseline,
            quality_gate=QualityGateTrace(
                provider="openai-compatible",
                attempted=False,
                selected=False,
                fallback=False,
                final_source="heuristic_skipped",
                heuristic_score=baseline.quality_score,
                heuristic_label=baseline.quality_label,
            ),
        )
    try:
        config = (
            OpenAICompatibleConfig.from_profile(llm_profile, config_path=llm_config_path)
            if llm_profile
            else OpenAICompatibleConfig.from_default_profile()
        )
        completion = chat_completion(
            config=config,
            messages=[
                {"role": "system", "content": _QUALITY_GATE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        _quality_gate_input(baseline=baseline, source_text=source_text, context=context),
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        assessment = _quality_assessment_from_payload(loads_json_object(completion))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return replace(
            baseline,
            warnings=(*baseline.warnings, "LLM quality gate unavailable; used heuristic fallback"),
            quality_gate=QualityGateTrace(
                provider="openai-compatible",
                attempted=True,
                selected=False,
                fallback=True,
                final_source="heuristic_fallback",
                heuristic_score=baseline.quality_score,
                heuristic_label=baseline.quality_label,
                fallback_reason=_safe_error_reason(exc),
            ),
        )

    return replace(
        baseline,
        kind=assessment["kind"],
        quality_score=assessment["quality_score"],
        quality_label=assessment["quality_label"],
        reasons=assessment["reasons"] or baseline.reasons,
        provider="openai-compatible",
        quality_gate=QualityGateTrace(
            provider="openai-compatible",
            attempted=True,
            selected=True,
            fallback=False,
            final_source="llm_assisted",
            heuristic_score=baseline.quality_score,
            heuristic_label=baseline.quality_label,
            llm_score=assessment["quality_score"],
            llm_label=assessment["quality_label"],
            suggested_rewrite=assessment["memory_rewrite"],
        ),
    )


def render_memory_draft(draft: MemoryDraft, *, context: ProjectContext | None = None) -> str:
    payload = draft.to_payload(context=context)
    lines = [
        "[MemAgent memory draft]",
        f"- topic: {payload['topic']}",
        f"- kind: {payload['kind']}",
        f"- triggers: {', '.join(payload['triggers']) if payload['triggers'] else '-'}",
        f"- quality: {payload['quality_label']} ({payload['quality_score']:.2f})",
        "- requires_confirmation: yes",
        "- memory:",
        f"  {payload['memory']}",
    ]
    if payload["reasons"]:
        lines.append(f"- reasons: {'; '.join(payload['reasons'])}")
    if payload["warnings"]:
        lines.append(f"- warnings: {'; '.join(payload['warnings'])}")
    quality_gate = payload.get("quality_gate")
    if isinstance(quality_gate, dict):
        lines.append(
            "- quality_gate: "
            f"{quality_gate.get('final_source')}; "
            f"heuristic={quality_gate.get('heuristic_label')} ({quality_gate.get('heuristic_score')})"
        )
        if quality_gate.get("fallback"):
            lines.append(f"- quality_gate_fallback: {quality_gate.get('fallback_reason') or 'provider unavailable'}")
        if quality_gate.get("suggested_rewrite"):
            lines.append(f"- llm_rewrite: {quality_gate['suggested_rewrite']}")
    lines.extend(["", "[Suggested remember command]", _remember_command(draft)])
    return "\n".join(lines)


def _infer_kind(text: str) -> str:
    lower = text.lower()
    if any(value in lower for value in ("用户偏好", "习惯", "默认", "除非", "不希望", "只修改", "不新增")):
        return "preference"
    if any(value in lower for value in ("schema", "table", "db ", "数据库", "表名", "api", "endpoint", "入口")):
        return "data_entrypoint"
    if any(value in lower for value in ("curl", "git ", "docker", "kubectl", "go test", "pytest", "sql", "mcp", "命令")):
        return "tool_recipe"
    if any(value in lower for value in ("坑", "绕路", "不要", "避免", "timeout", "failed", "error", "报错")):
        return "pitfall"
    if any(value in lower for value in ("验证", "verify", "检查", "test", "覆盖率")):
        return "verification"
    if any(value in lower for value in ("先", "再", "然后", "最后", "workflow", "流程")):
        return "workflow"
    return "note"


def _quality(text: str, *, kind: str) -> tuple[float, str, list[str], list[str]]:
    lower = text.lower()
    score = 0.24
    reasons: list[str] = []
    warnings: list[str] = []
    if kind != "note":
        score += 0.16
        reasons.append(f"specific kind inferred: {kind}")
    if any(value in lower for value in ("git ", "docker", "kubectl", "mcp", "curl", "sql", "go test", "pytest")):
        score += 0.18
        reasons.append("contains reusable tool or command signal")
    if any(value in lower for value in ("schema", "table", "api", "maintainer", "入口", "数据库", "表")):
        score += 0.16
        reasons.append("contains reusable engineering entrypoint")
    if any(value in lower for value in ("避免", "不要", "坑", "绕路", "timeout", "failed", "error")):
        score += 0.14
        reasons.append("captures a pitfall or failed path")
    if any(value in lower for value in ("验证", "verify", "test", "检查")):
        score += 0.1
        reasons.append("includes verification signal")
    if len(_tokenize(text)) < 4:
        score -= 0.18
        warnings.append("source is very short; draft may be under-specified")
    if not reasons:
        warnings.append("no strong reusable workflow signal detected")
    score = max(0.0, min(score, 0.98))
    if score >= 0.68:
        label = "keep"
    elif score >= 0.42:
        label = "revise"
    else:
        label = "reject"
    return score, label, reasons or ["generic note only"], warnings


def _should_use_llm_quality_gate(baseline: MemoryDraft, source_text: str) -> bool:
    if baseline.kind in LLM_ASSIST_KINDS:
        return True
    if AMBIGUOUS_QUALITY_MIN <= baseline.quality_score <= AMBIGUOUS_QUALITY_MAX:
        return True
    lower = source_text.lower()
    return any(value in lower for value in ("用户偏好", "习惯", "默认", "除非", "不希望", "只修改", "不新增"))


def _quality_gate_input(
    *,
    baseline: MemoryDraft,
    source_text: str,
    context: ProjectContext | None,
) -> dict[str, object]:
    return {
        "candidate": {
            "kind": baseline.kind,
            "topic": _sanitize_for_llm(baseline.topic),
            "triggers": [_sanitize_for_llm(trigger) for trigger in baseline.triggers[:6]],
            "memory": _sanitize_for_llm(_short(baseline.memory, 420)),
            "heuristic_quality": {
                "score": round(baseline.quality_score, 2),
                "label": baseline.quality_label,
            },
        },
        "source_summary": _source_summary(source_text),
        "context": {
            "has_git_project": bool(context and context.git_root),
            "has_branch": bool(context and context.branch),
            "scope": "current_project" if context else "unknown_project",
        },
        "allowed_kinds": sorted(ALLOWED_KINDS),
        "allowed_quality_labels": sorted(QUALITY_LABELS),
        "privacy": "Identifiers, absolute paths, URLs, secrets, and long numeric values were generalized before this request.",
    }


def _quality_assessment_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    kind = normalize_kind(str(payload.get("kind") or "note"))
    label = str(payload.get("quality_label") or "revise").strip().lower()
    if label not in QUALITY_LABELS:
        raise ValueError("LLM quality gate returned invalid quality_label")
    try:
        score = float(payload.get("quality_score"))
    except (TypeError, ValueError) as exc:
        raise ValueError("LLM quality gate returned invalid quality_score") from exc
    if not 0.0 <= score <= 1.0:
        raise ValueError("LLM quality gate quality_score must be between 0 and 1")
    reasons_value = payload.get("reasons")
    reasons = tuple(_short(str(item), 160) for item in reasons_value if str(item).strip()) if isinstance(reasons_value, list) else ()
    rewrite = _short(str(payload.get("memory_rewrite") or ""), 420) or None
    return {
        "kind": kind,
        "quality_label": label,
        "quality_score": score,
        "reasons": reasons[:4],
        "memory_rewrite": rewrite,
    }


def _source_summary(source_text: str) -> str:
    lower = source_text.lower()
    signals: list[str] = []
    if any(value in lower for value in ("用户偏好", "习惯", "默认", "除非", "不希望", "只修改", "不新增")):
        signals.append("explicit user preference or default/exception rule")
    if any(value in lower for value in ("先", "再", "然后", "最后", "流程", "workflow")):
        signals.append("ordered workflow guidance")
    if any(value in lower for value in ("git ", "docker", "kubectl", "sql", "mcp", "curl", "go test", "pytest")):
        signals.append("reusable tool or verification signal")
    if any(value in lower for value in ("避免", "不要", "坑", "绕路", "error", "timeout", "报错")):
        signals.append("pitfall or prohibited path")
    if not signals:
        signals.append("short reusable coding-session lesson")
    return "; ".join(signals[:3])


def _sanitize_for_llm(text: str) -> str:
    sanitized = _clean_source(text)
    sanitized = re.sub(r"https?://[^\s]+", "<url>", sanitized, flags=re.I)
    sanitized = re.sub(r"(?:~|/Users|/home|/private|/tmp)/[^\s,，。；;]+", "<path>", sanitized)
    sanitized = re.sub(r"\b(?:sk|rk|pk)[-_][A-Za-z0-9_-]{6,}\b", "<secret>", sanitized, flags=re.I)
    sanitized = re.sub(r"\b(?:token|api[_-]?key|authorization)\s*[:=]\s*[^\s,，。；;]+", "<secret>", sanitized, flags=re.I)
    sanitized = re.sub(r"\b[a-zA-Z][a-zA-Z0-9]*(?:_[a-zA-Z0-9]+)+\b", "<identifier>", sanitized)
    sanitized = re.sub(r"\b\d{6,}\b", "<number>", sanitized)
    return _short(sanitized, 420)


def _safe_error_reason(exc: Exception) -> str:
    return _short(re.sub(r"(?:sk|rk|pk)[-_][A-Za-z0-9_-]+", "<secret>", str(exc), flags=re.I), 180)


def _memory_text(text: str, *, max_chars: int = 420) -> str:
    cleaned = _clean_source(text)
    cleaned = re.sub(r"^这个\s*(.+?)\s*(?:的)?入口下次别忘了[:：,，\s]*", r"\1 入口：", cleaned)
    cleaned = re.sub(r"^这个\s*(.+?)\s*下次别忘了[:：,，\s]*", r"\1：", cleaned)
    cleaned = re.sub(r"^(记住这个|沉淀一下|保存为 memagent 记忆|这个入口下次别忘了)[:：,，\s]*", "", cleaned, flags=re.I)
    sentences = re.split(r"(?<=[。！？.!?])\s+", cleaned)
    selected = " ".join(sentence for sentence in sentences[:3] if sentence).strip() or cleaned
    return _short(selected, max_chars)


def _derive_topic(text: str, *, kind: str) -> str:
    command = _first_command(text)
    if command:
        return _short(f"{kind} {command}", 80)
    return _short(_memory_text(text, max_chars=80), 80)


def _derive_triggers(text: str) -> list[str]:
    tokens = _tokenize(text)
    preferred = [
        token
        for token in tokens
        if _is_good_trigger(token)
    ]
    seen: set[str] = set()
    triggers: list[str] = []
    for token in preferred or tokens:
        if token in seen or len(token) < 2:
            continue
        seen.add(token)
        triggers.append(token)
        if len(triggers) >= 8:
            break
    return triggers or ["memory"]


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[\w\u4e00-\u9fff]+", text.lower()):
        if raw not in seen:
            seen.add(raw)
            tokens.append(raw)
    return tokens


def _first_command(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("git ", "curl ", "docker ", "kubectl ", "go test", "pytest ", "python ", "memagent ")):
            return stripped[:64]
    match = re.search(
        r"((?:git|docker|kubectl)\s+[^。；;]+|"
        r"curl\s+[^。；;]+|go test\s+[^。；;]+|pytest\s+[^。；;]+)",
        text,
    )
    if match:
        return match.group(1).strip()[:64]
    return None


def _is_good_trigger(token: str) -> bool:
    if any(noisy in token for noisy in ("别忘", "这个", "下次", "入口下次")):
        return False
    if token in {"git", "docker", "kubectl", "mcp", "sql", "schema", "api", "test"}:
        return True
    if re.fullmatch(r"[a-z0-9_./-]+", token) and len(token) >= 4:
        return True
    return 2 <= len(token) <= 8 and bool(re.search(r"[\u4e00-\u9fff]", token))


def _remember_command(draft: MemoryDraft) -> str:
    parts = [
        "memagent",
        "remember",
        "--domain",
        draft.domain,
        "--kind",
        draft.kind,
        "--topic",
        draft.topic,
    ]
    for trigger in draft.triggers:
        parts.extend(["--trigger", trigger])
    parts.append(draft.memory)
    return " ".join(shlex.quote(part) for part in parts)


def _clean_source(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _excerpt(text: str) -> str:
    return _short(_clean_source(text), 500)


def _short(text: str, limit: int) -> str:
    clean = _clean_source(text)
    if len(clean) <= limit:
        return clean
    return clean[: max(limit - 1, 0)].rstrip() + "…"


_QUALITY_GATE_SYSTEM_PROMPT = f"""
You are MemAgent's selective memory quality gate for coding-agent workflow memory.
Return only a JSON object. Do not explain outside JSON.

Allowed kinds: {sorted(ALLOWED_KINDS)}
Allowed quality labels: {sorted(QUALITY_LABELS)}

Assess the generalized candidate. A stable user-specific engineering preference,
default/exception rule, reusable decision, or workflow can be high quality even
when it contains no command, API, database, or tool keyword. Do not decide
whether it is saved; a user confirmation is always required.

Required JSON shape:
{{
  "kind": "one allowed kind",
  "memory_rewrite": "a generalized 1-3 sentence rewrite without sensitive details",
  "quality_score": 0.0,
  "quality_label": "keep | revise | reject",
  "reasons": ["short quality reasons"]
}}
""".strip()
