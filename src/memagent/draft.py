from __future__ import annotations

from dataclasses import dataclass
import json
import re
import shlex
from typing import Any

from memagent.context import ProjectContext
from memagent.llm import OpenAICompatibleConfig, chat_completion, loads_json_object
from memagent.memory import ALLOWED_KINDS, DEFAULT_DOMAIN, normalize_kind


MEMORY_DRAFT_SCHEMA_VERSION = "memagent.memory_draft.v1"
QUALITY_LABELS = {"keep", "revise", "reject"}


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
        return draft_memory_openai_compatible(text, context=context, topic=topic, kind=kind, max_chars=max_chars)
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
    )


def draft_memory_openai_compatible(
    source_text: str,
    *,
    context: ProjectContext | None,
    topic: str | None,
    kind: str | None,
    max_chars: int,
) -> MemoryDraft:
    config = OpenAICompatibleConfig.from_env()
    context_payload = (
        {
            "cwd": str(context.cwd),
            "git_root": str(context.git_root) if context.git_root else None,
            "branch": context.branch,
            "repo_name": context.repo_name,
        }
        if context is not None
        else {}
    )
    prompt_payload = {
        "source_text": source_text[-6000:],
        "context": context_payload,
        "topic_override": topic,
        "kind_override": kind,
        "allowed_kinds": sorted(ALLOWED_KINDS),
        "max_memory_chars": max_chars,
    }
    completion = chat_completion(
        config=config,
        messages=[
            {"role": "system", "content": _DRAFT_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
        ],
    )
    payload = loads_json_object(completion)
    return _draft_from_payload(payload, source_text=source_text, provider="openai-compatible", topic=topic, kind=kind)


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
    lines.extend(["", "[Suggested remember command]", _remember_command(draft)])
    return "\n".join(lines)


def _draft_from_payload(
    payload: dict[str, Any],
    *,
    source_text: str,
    provider: str,
    topic: str | None,
    kind: str | None,
) -> MemoryDraft:
    inferred_kind = normalize_kind(kind or str(payload.get("kind") or "note"))
    triggers_value = payload.get("triggers")
    triggers = tuple(_derive_triggers(" ".join(str(item) for item in triggers_value))) if isinstance(triggers_value, list) else tuple(_derive_triggers(source_text))
    label = str(payload.get("quality_label") or "revise")
    if label not in QUALITY_LABELS:
        label = "revise"
    reasons_value = payload.get("reasons")
    warnings_value = payload.get("warnings")
    return MemoryDraft(
        topic=topic or _short(str(payload.get("topic") or _derive_topic(source_text, kind=inferred_kind)), 80),
        kind=inferred_kind,
        triggers=triggers[:8],
        memory=_short(str(payload.get("memory") or _memory_text(source_text)), 600),
        quality_score=float(payload.get("quality_score") or 0.5),
        quality_label=label,
        reasons=tuple(str(item) for item in reasons_value) if isinstance(reasons_value, list) else (),
        warnings=tuple(str(item) for item in warnings_value) if isinstance(warnings_value, list) else (),
        source_excerpt=_excerpt(source_text),
        provider=provider,
    )


def _infer_kind(text: str) -> str:
    lower = text.lower()
    if any(value in lower for value in ("schema", "table", "db ", "数据库", "表名", "api", "endpoint", "入口")):
        return "data_entrypoint"
    if any(value in lower for value in ("bytedcli", "curl", "go test", "pytest", "sql", "mcp", "命令")):
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
    if any(value in lower for value in ("bytedcli", "rds", "bam", "mcp", "curl", "sql", "go test", "pytest")):
        score += 0.18
        reasons.append("contains reusable tool or command signal")
    if any(value in lower for value in ("schema", "table", "api", "owner", "入口", "数据库", "表")):
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
        if stripped.startswith(("bytedcli ", "curl ", "go test", "pytest ", "python ", "memagent ")):
            return stripped[:64]
    match = re.search(
        r"(bytedcli\s+(?:rds|bam|mcp|db|api|insearch)\b[^。；;]+|"
        r"curl\s+[^。；;]+|go test\s+[^。；;]+|pytest\s+[^。；;]+)",
        text,
    )
    if match:
        return match.group(1).strip()[:64]
    return None


def _is_good_trigger(token: str) -> bool:
    if any(noisy in token for noisy in ("别忘", "这个", "下次", "入口下次")):
        return False
    if token in {"bytedcli", "rds", "bam", "mcp", "sql", "schema", "owner", "audit_rule_lib"}:
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


_DRAFT_SYSTEM_PROMPT = f"""
You are MemAgent's memory draft generator for coding-agent workflow memory.
Return only a JSON object. Do not explain outside JSON.

Allowed kinds: {sorted(ALLOWED_KINDS)}
Allowed quality labels: {sorted(QUALITY_LABELS)}

Create a short reviewable memory draft from the source text.
The memory must be 1-3 sentences and action-oriented.
Prefer exact reusable tool recipes, data entrypoints, pitfalls, and verification
steps when they are the lesson.
Do not include tokens, passwords, cookies, private keys, long raw outputs, or
large request/response bodies.

Required JSON shape:
{{
  "topic": "short topic",
  "kind": "one allowed kind",
  "triggers": ["keyword"],
  "memory": "1-3 sentence reusable lesson",
  "quality_score": 0.0,
  "quality_label": "keep | revise | reject",
  "reasons": ["why this is or is not reusable"],
  "warnings": ["quality or safety warnings"]
}}
""".strip()
