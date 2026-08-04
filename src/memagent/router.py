from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from memagent.context import ProjectContext, context_payload
from memagent.llm import (
    OpenAICompatibleConfig,
    chat_completion,
    default_semantic_mode,
    loads_json_object,
    sanitize_llm_text,
)


ROUTE_SCHEMA_VERSION = "memagent.route.v1"
ROUTE_ACTIONS = {
    "recall",
    "draft_memory",
    "save_memory",
    "reject_memory",
    "label_feedback",
    "handoff_show",
    "handoff_save",
    "developer_eval",
    "none",
}
FEEDBACK_RATINGS = {"useful", "not-useful", "neutral"}


@dataclass(frozen=True)
class RouteDecision:
    action: str
    confidence: float
    reason: str
    signals: tuple[str, ...]
    user_message: str
    provider: str = "heuristic"
    query: str | None = None
    feedback_rating: str | None = None
    requires_confirmation: bool = False
    requires_pending_draft: bool = False
    requires_recent_trace: bool = False
    developer_mode: bool = False
    suggested_next: str | None = None
    recent_text_used: bool = False
    recall_likelihood: float | None = None

    def to_payload(self, *, context: ProjectContext | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": ROUTE_SCHEMA_VERSION,
            "provider": self.provider,
            "action": self.action,
            "confidence": round(max(min(self.confidence, 1.0), 0.0), 2),
            "reason": self.reason,
            "signals": list(self.signals),
            "user_message": self.user_message,
            "query": self.query,
            "feedback_rating": self.feedback_rating,
            "requires_confirmation": self.requires_confirmation,
            "requires_pending_draft": self.requires_pending_draft,
            "requires_recent_trace": self.requires_recent_trace,
            "developer_mode": self.developer_mode,
            "suggested_next": self.suggested_next,
            "recent_text_used": self.recent_text_used,
            "recall_likelihood": (
                round(max(min(self.recall_likelihood, 1.0), 0.0), 2)
                if self.recall_likelihood is not None
                else None
            ),
        }
        if context is not None:
            payload["context"] = context_payload(context)
        return payload


def route_interaction(
    user_message: str,
    *,
    recent_text: str = "",
    context: ProjectContext | None = None,
    provider: str = "heuristic",
    semantic_mode: str | None = None,
    llm_profile: str | None = None,
    llm_config_path: Path | None = None,
    has_recent_trace: bool | None = None,
    has_pending_draft: bool | None = None,
) -> RouteDecision:
    message = _clean(user_message)
    if not message:
        raise ValueError("route message cannot be empty")
    provider = provider or "heuristic"
    mode = semantic_mode or ("llm" if provider == "openai-compatible" else default_semantic_mode())
    heuristic = route_with_heuristics(
        message,
        recent_text=recent_text,
        has_recent_trace=has_recent_trace,
        has_pending_draft=has_pending_draft,
    )
    if mode == "heuristic":
        return heuristic
    if mode not in {"llm", "hybrid"}:
        raise ValueError("semantic_mode must be heuristic, llm, or hybrid")
    if mode == "hybrid":
        if _should_use_llm_recall_estimator(heuristic):
            try:
                return estimate_recall_with_openai_compatible(
                    message,
                    context=context,
                    llm_profile=llm_profile,
                    llm_config_path=llm_config_path,
                )
            except (OSError, ValueError, json.JSONDecodeError):
                return RouteDecision(
                    **{
                        **heuristic.__dict__,
                        "provider": "heuristic_fallback",
                        "reason": "Optional LLM recall estimation was unavailable; used local heuristic routing.",
                    }
                )
        if not _should_use_llm_router(heuristic):
            return heuristic
    try:
        return route_with_openai_compatible(
            message,
            recent_text=recent_text,
            context=context,
            llm_profile=llm_profile,
            llm_config_path=llm_config_path,
            has_recent_trace=has_recent_trace,
            has_pending_draft=has_pending_draft,
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return RouteDecision(
            **{**heuristic.__dict__, "provider": "heuristic_fallback", "reason": "Optional LLM routing was unavailable; used local heuristic routing."}
        )


def route_with_heuristics(
    user_message: str,
    *,
    recent_text: str = "",
    has_recent_trace: bool | None = None,
    has_pending_draft: bool | None = None,
) -> RouteDecision:
    text = _clean(user_message)
    lower = text.lower()
    candidates: list[RouteDecision] = []

    developer_signals = _matched(
        lower,
        (
            "trace eval",
            "trace replay",
            "质量报告",
            "评估 memagent",
            "自测报告",
            "interview evidence",
            "retrieval behavior",
            "top-stability",
        ),
    )
    if developer_signals:
        candidates.append(
            RouteDecision(
                action="developer_eval",
                confidence=_confidence(developer_signals, base=0.68),
                reason="The message asks for MemAgent quality or evaluation artifacts.",
                signals=developer_signals,
                user_message=text,
                provider="heuristic",
                developer_mode=True,
                suggested_next="Run trace eval/replay with explicit --workspace paths.",
            )
        )

    handoff_show_signals = _matched(
        lower,
        (
            "上次做到哪",
            "接着上次继续",
            "catch me up",
            "where did we leave off",
            "继续刚才",
            "我们上回到哪",
            "看看上次交接",
        ),
    )
    if handoff_show_signals:
        candidates.append(
            RouteDecision(
                action="handoff_show",
                confidence=_confidence(handoff_show_signals, base=0.72),
                reason="The message asks to continue from previous project state.",
                signals=handoff_show_signals,
                user_message=text,
                provider="heuristic",
                suggested_next="Run handoff show for the current project.",
            )
        )

    handoff_save_signals = _matched(
        lower,
        (
            "先到这",
            "下次继续",
            "换个会话",
            "交接一下",
            "记录当前进展",
            "保存一个 handoff",
            "生成 handoff",
            "wrap up",
            "handoff",
        ),
    )
    if handoff_save_signals:
        candidates.append(
            RouteDecision(
                action="handoff_save",
                confidence=_confidence(handoff_save_signals, base=0.72),
                reason="The message asks to preserve current continuation state.",
                signals=handoff_save_signals,
                user_message=text,
                provider="heuristic",
                requires_confirmation=False,
                suggested_next="Summarize done/next/open questions and run handoff save.",
            )
        )

    confirmation_signals = _matched(
        lower,
        (
            "确认保存",
            "确认下保存",
            "就按这个保存",
            "按这个保存",
            "确认写入",
            "保存这条",
            "记下这条",
            "save it",
            "save that",
            "remember it",
            "yes, save",
        ),
    )
    if confirmation_signals and has_pending_draft is True:
        candidates.append(
            RouteDecision(
                action="save_memory",
                confidence=_confidence(confirmation_signals, base=0.9),
                reason="The user confirmed the pending memory preview.",
                signals=confirmation_signals,
                user_message=text,
                provider="heuristic",
                requires_pending_draft=True,
                suggested_next="Save the pending memory draft for the current project.",
            )
        )

    rejection_signals = _matched(
        lower,
        (
            "不用记",
            "不需要记",
            "这不值得存",
            "不值得记录",
            "别保存",
            "取消保存",
            "discard this memory",
            "do not save this",
            "don't save",
            "dont save",
        ),
    )
    if rejection_signals and has_pending_draft is True:
        candidates.append(
            RouteDecision(
                action="reject_memory",
                confidence=_confidence(rejection_signals, base=0.9),
                reason="The user rejected the pending memory preview.",
                signals=rejection_signals,
                user_message=text,
                provider="heuristic",
                requires_pending_draft=True,
                suggested_next="Discard the pending memory draft for the current project.",
            )
        )

    feedback_rating, feedback_signals = _feedback_signal(lower)
    if feedback_signals:
        confidence = _confidence(feedback_signals, base=0.7)
        if has_recent_trace is False:
            confidence = min(confidence, 0.55)
        candidates.append(
            RouteDecision(
                action="label_feedback",
                confidence=confidence,
                reason="The message looks like feedback on a recently recalled memory.",
                signals=feedback_signals,
                user_message=text,
                provider="heuristic",
                feedback_rating=feedback_rating,
                requires_recent_trace=True,
                suggested_next="Label the latest recall trace if one exists.",
            )
        )

    memory_signals = _matched(
        lower,
        (
            "记住这个",
            "记住",
            "请记住",
            "记住并",
            "把这个习惯记住",
            "把这个偏好记住",
            "这个习惯以后保持",
            "以后按这个来",
            "沉淀一下",
            "下次别再",
            "做成 memory",
            "保存为 memagent",
            "下次别忘",
            "以后还会用",
            "绕路的原因",
            "这个入口",
            "这个命令",
            "踩坑",
            "生成草稿",
            "remember this",
            "save this lesson",
        ),
    )
    if "草稿" in lower and any(value in lower for value in ("记忆", "约束", "经验", "习惯", "偏好", "可复用")):
        memory_signals = (*memory_signals, "memory_draft")
    if memory_signals:
        candidates.append(
            RouteDecision(
                action="draft_memory",
                confidence=_confidence(memory_signals, base=0.74),
                reason="The message asks to preserve a reusable workflow lesson.",
                signals=memory_signals,
                user_message=text,
                provider="heuristic",
                requires_confirmation=True,
                recent_text_used=bool(recent_text.strip()),
                suggested_next="Run draft memory for a preview, then wait for confirmation before remember.",
            )
        )

    recall_signals = _recall_signals(lower)
    if recall_signals:
        candidates.append(
            RouteDecision(
                action="recall",
                confidence=_confidence(recall_signals, base=0.58),
                reason="The task may benefit from prior coding workflow memory.",
                signals=recall_signals,
                user_message=text,
                provider="heuristic",
                query=_route_query(text),
                suggested_next="Run recall with --show-sources --show-reasons --strategy bm25 --trace, then verify against live sources.",
            )
        )

    if not candidates:
        return RouteDecision(
            action="none",
            confidence=0.25,
            reason="No strong memory interaction signal was detected.",
            signals=(),
            user_message=text,
            provider="heuristic",
            suggested_next="Continue normally without MemAgent.",
        )

    action_priority = {
        "save_memory": 90,
        "reject_memory": 90,
        "label_feedback": 80,
        "handoff_save": 75,
        "handoff_show": 75,
        "developer_eval": 70,
        "draft_memory": 60,
        "recall": 50,
    }
    return max(candidates, key=lambda decision: (action_priority.get(decision.action, 0), decision.confidence))


def route_with_openai_compatible(
    user_message: str,
    *,
    recent_text: str,
    context: ProjectContext | None,
    llm_profile: str | None,
    llm_config_path: Path | None,
    has_recent_trace: bool | None,
    has_pending_draft: bool | None,
) -> RouteDecision:
    config = (
        OpenAICompatibleConfig.from_profile(llm_profile, config_path=llm_config_path)
        if llm_profile
        else OpenAICompatibleConfig.from_default_profile(config_path=llm_config_path)
    )
    context_payload = {
        "has_git_project": bool(context and context.git_root),
        "has_branch": bool(context and context.branch),
        "project_scope": "current_project" if context else "unknown_project",
    }
    prompt_payload = {
        "user_message": sanitize_llm_text(user_message, limit=600),
        "recent_text": sanitize_llm_text(recent_text, limit=800),
        "context": context_payload,
        "has_recent_trace": has_recent_trace,
        "has_pending_memory_draft": has_pending_draft,
        "allowed_actions": sorted(ROUTE_ACTIONS),
        "allowed_feedback_ratings": sorted(FEEDBACK_RATINGS),
    }
    completion = chat_completion(
        config=config,
        messages=[
            {
                "role": "system",
                "content": _ROUTER_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": json.dumps(prompt_payload, ensure_ascii=False),
            },
        ],
    )
    payload = loads_json_object(completion)
    return _decision_from_payload(payload, user_message=user_message, provider="openai-compatible")


def estimate_recall_with_openai_compatible(
    user_message: str,
    *,
    context: ProjectContext | None,
    llm_profile: str | None,
    llm_config_path: Path | None,
) -> RouteDecision:
    config = (
        OpenAICompatibleConfig.from_profile(llm_profile, config_path=llm_config_path)
        if llm_profile
        else OpenAICompatibleConfig.from_default_profile(config_path=llm_config_path)
    )
    prompt_payload = {
        "user_message": sanitize_llm_text(user_message, limit=360),
        "context": {
            "has_git_project": bool(context and context.git_root),
            "project_scope": "current_project" if context else "unknown_project",
        },
    }
    completion = chat_completion(
        config=config,
        messages=[
            {"role": "system", "content": _RECALL_ESTIMATOR_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
        ],
    )
    payload = loads_json_object(completion)
    likelihood = _recall_likelihood_from_payload(payload)
    should_recall = likelihood >= 0.55
    signals_value = payload.get("signals")
    signals = tuple(str(item) for item in signals_value if str(item).strip()) if isinstance(signals_value, list) else ()
    return RouteDecision(
        action="recall" if should_recall else "none",
        confidence=likelihood if should_recall else 1 - likelihood,
        reason=str(payload.get("reason") or "LLM recall estimate."),
        signals=("llm_recall_estimate", *signals),
        user_message=user_message,
        provider="llm_recall_estimator",
        query=_route_query(user_message) if should_recall else None,
        suggested_next=(
            "Recall short project-scoped memory context, then verify against live sources."
            if should_recall
            else "Continue normally without recalling project memory."
        ),
        recall_likelihood=likelihood,
    )


def render_route_decision(decision: RouteDecision, *, context: ProjectContext | None = None) -> str:
    payload = decision.to_payload(context=context)
    lines = [
        "[MemAgent route]",
        f"- action: {payload['action']}",
        f"- confidence: {payload['confidence']:.2f}",
        f"- provider: {payload['provider']}",
        f"- reason: {payload['reason']}",
    ]
    signals = payload["signals"]
    lines.append(f"- signals: {', '.join(signals) if signals else '-'}")
    if payload.get("recall_likelihood") is not None:
        lines.append(f"- recall_likelihood: {payload['recall_likelihood']:.2f}")
    if payload.get("query"):
        lines.append(f"- query: {payload['query']}")
    if payload.get("feedback_rating"):
        lines.append(f"- feedback_rating: {payload['feedback_rating']}")
    if payload.get("requires_confirmation"):
        lines.append("- requires_confirmation: yes")
    if payload.get("requires_pending_draft"):
        lines.append("- requires_pending_draft: yes")
    if payload.get("requires_recent_trace"):
        lines.append("- requires_recent_trace: yes")
    if payload.get("developer_mode"):
        lines.append("- developer_mode: yes")
    if payload.get("suggested_next"):
        lines.append(f"- suggested_next: {payload['suggested_next']}")
    return "\n".join(lines)


def _decision_from_payload(payload: dict[str, Any], *, user_message: str, provider: str) -> RouteDecision:
    action = str(payload.get("action") or "none")
    if action not in ROUTE_ACTIONS:
        raise ValueError(f"LLM router returned invalid action: {action}")
    confidence = float(payload.get("confidence") or 0.0)
    feedback_rating = payload.get("feedback_rating")
    if feedback_rating is not None:
        feedback_rating = str(feedback_rating).replace("_", "-")
        if feedback_rating not in FEEDBACK_RATINGS:
            feedback_rating = None
    signals_value = payload.get("signals")
    signals = tuple(str(item) for item in signals_value if str(item).strip()) if isinstance(signals_value, list) else ()
    return RouteDecision(
        action=action,
        confidence=confidence,
        reason=str(payload.get("reason") or "LLM router decision."),
        signals=signals,
        user_message=user_message,
        provider=provider,
        query=str(payload.get("query")) if payload.get("query") else None,
        feedback_rating=feedback_rating,
        requires_confirmation=bool(payload.get("requires_confirmation")),
        requires_pending_draft=bool(payload.get("requires_pending_draft")),
        requires_recent_trace=bool(payload.get("requires_recent_trace")),
        developer_mode=bool(payload.get("developer_mode")),
        suggested_next=str(payload.get("suggested_next")) if payload.get("suggested_next") else None,
        recent_text_used=bool(payload.get("recent_text_used")),
    )


def _recall_likelihood_from_payload(payload: dict[str, Any]) -> float:
    value = payload.get("recall_likelihood")
    try:
        likelihood = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("LLM recall estimator response requires recall_likelihood") from exc
    if not 0 <= likelihood <= 1:
        raise ValueError("LLM recall estimator recall_likelihood must be between 0 and 1")
    return likelihood


def _feedback_signal(text: str) -> tuple[str | None, tuple[str, ...]]:
    positive = _matched(
        text,
        ("这个有用", "那条有用", "提醒有用", "是对的", "帮到了", "命中了", "有帮助", "useful"),
    )
    negative = _matched(text, ("没帮上忙", "不相关", "不是这个问题", "没用", "错了", "过期", "not useful"))
    if positive and not negative:
        return "useful", positive
    if negative:
        return "not-useful", negative
    return None, ()


def _recall_signals(text: str) -> tuple[str, ...]:
    if _matched(text, ("typo", "拼写", "格式化一下", "改个文案", "简单改下")):
        return ()
    signals = list(
        _matched(
            text,
            (
                "排查",
                "定位",
                "debug",
                "继续查",
                "继续排查",
                "以前踩过",
                "类似上次",
                "先按你觉得最省时间",
                "mcp",
                "service",
                "maintainer",
                "task",
                "schema",
                "接口",
                "数据库",
                "表",
                "sql",
                "go test",
                "pytest",
            ),
        )
    )
    preference_patterns = (
        r"用户.*(?:习惯|偏好|约束|规则)",
        r"(?:开发|编码|协作).*(?:习惯|偏好|约束|规则)",
        r"之前.*(?:习惯|偏好|约束|规则)",
        r"(?:有什么|知道).*(?:习惯|偏好|约束|规则)",
        r"(?:user|coding|development).*(?:preference|habit|constraint|convention)",
    )
    for pattern in preference_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            signals.append("user_preference")
            break
    return tuple(signals)


def _should_use_llm_router(decision: RouteDecision) -> bool:
    return decision.action == "none" or decision.confidence <= 0.64


def _should_use_llm_recall_estimator(decision: RouteDecision) -> bool:
    return decision.action in {"none", "recall"} and decision.confidence <= 0.64


def _matched(text: str, phrases: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(phrase for phrase in phrases if phrase.lower() in text)


def _confidence(signals: tuple[str, ...], *, base: float) -> float:
    return min(0.95, base + max(len(signals) - 1, 0) * 0.06)


def _route_query(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:240]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


_ROUTER_SYSTEM_PROMPT = f"""
You are MemAgent's routing classifier for Codex-native memory UX.
Return only a JSON object. Do not explain outside JSON.

Allowed actions:
- recall: task start may benefit from prior coding workflow memory.
- draft_memory: current interaction contains a reusable lesson; preview before saving.
- save_memory: user confirmed the pending memory preview for the current project.
- reject_memory: user rejected the pending memory preview for the current project.
- label_feedback: user gave feedback on a recalled memory.
- handoff_show: user wants to resume previous project state.
- handoff_save: user wants to stop or continue in another session.
- developer_eval: user asks to evaluate MemAgent quality or produce trace eval/replay artifacts.
- none: no memory action is useful.

Required JSON shape:
{{
  "action": "<one of {sorted(ROUTE_ACTIONS)}>",
  "confidence": 0.0,
  "reason": "short reason",
  "signals": ["short matched semantic signals"],
  "query": "short recall query or null",
  "feedback_rating": "useful | not-useful | neutral | null",
  "requires_confirmation": false,
  "requires_pending_draft": false,
  "requires_recent_trace": false,
  "developer_mode": false,
  "suggested_next": "short next step",
  "recent_text_used": false
}}

Rules:
- Never choose draft_memory for ordinary summaries unless there is a reusable workflow lesson.
- draft_memory always requires confirmation before durable saving.
- Only choose save_memory when has_pending_memory_draft is true and the user explicitly confirms saving.
- Only choose reject_memory when has_pending_memory_draft is true and the user explicitly declines saving.
- label_feedback requires a recent recall trace.
- trace eval/replay are developer_eval, not normal product work.
- Memories are hints; live code, schema, docs, and command output remain source of truth.
""".strip()


_RECALL_ESTIMATOR_SYSTEM_PROMPT = """
You estimate whether a coding-agent user message is likely to benefit from
recalling prior project-local workflow memory. Return only a JSON object.

Use a high score when the user asks about earlier work, established preferences,
habits, conventions, previous investigations, recurring tools, or known pitfalls.
Use a low score for a self-contained question or a small mechanical edit.

Do not assume any memory content exists. You receive no memory cards, paths,
repository names, or conversation transcript.

Required JSON shape:
{
  "recall_likelihood": 0.0,
  "reason": "short reason",
  "signals": ["short semantic signals"]
}
""".strip()
