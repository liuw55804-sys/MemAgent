from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from memagent.context import ProjectContext
from memagent.llm import OpenAICompatibleConfig, chat_completion, loads_json_object


ROUTE_SCHEMA_VERSION = "memagent.route.v1"
ROUTE_ACTIONS = {
    "recall",
    "draft_memory",
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
    requires_recent_trace: bool = False
    developer_mode: bool = False
    suggested_next: str | None = None
    recent_text_used: bool = False

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
            "requires_recent_trace": self.requires_recent_trace,
            "developer_mode": self.developer_mode,
            "suggested_next": self.suggested_next,
            "recent_text_used": self.recent_text_used,
        }
        if context is not None:
            payload["context"] = {
                "cwd": str(context.cwd),
                "git_root": str(context.git_root) if context.git_root else None,
                "branch": context.branch,
                "repo_name": context.repo_name,
            }
        return payload


def route_interaction(
    user_message: str,
    *,
    recent_text: str = "",
    context: ProjectContext | None = None,
    provider: str = "heuristic",
    has_recent_trace: bool | None = None,
) -> RouteDecision:
    message = _clean(user_message)
    if not message:
        raise ValueError("route message cannot be empty")
    provider = provider or "heuristic"
    if provider == "heuristic":
        return route_with_heuristics(
            message,
            recent_text=recent_text,
            has_recent_trace=has_recent_trace,
        )
    if provider == "openai-compatible":
        return route_with_openai_compatible(
            message,
            recent_text=recent_text,
            context=context,
            has_recent_trace=has_recent_trace,
        )
    raise ValueError("provider must be heuristic or openai-compatible")


def route_with_heuristics(
    user_message: str,
    *,
    recent_text: str = "",
    has_recent_trace: bool | None = None,
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
        ),
    )
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

    return max(candidates, key=lambda decision: decision.confidence)


def route_with_openai_compatible(
    user_message: str,
    *,
    recent_text: str,
    context: ProjectContext | None,
    has_recent_trace: bool | None,
) -> RouteDecision:
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
        "user_message": user_message,
        "recent_text": recent_text[-4000:],
        "context": context_payload,
        "has_recent_trace": has_recent_trace,
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
    if payload.get("query"):
        lines.append(f"- query: {payload['query']}")
    if payload.get("feedback_rating"):
        lines.append(f"- feedback_rating: {payload['feedback_rating']}")
    if payload.get("requires_confirmation"):
        lines.append("- requires_confirmation: yes")
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
        requires_recent_trace=bool(payload.get("requires_recent_trace")),
        developer_mode=bool(payload.get("developer_mode")),
        suggested_next=str(payload.get("suggested_next")) if payload.get("suggested_next") else None,
        recent_text_used=bool(payload.get("recent_text_used")),
    )


def _feedback_signal(text: str) -> tuple[str | None, tuple[str, ...]]:
    positive = _matched(text, ("这个有用", "提醒有用", "是对的", "帮到了", "命中了", "有帮助", "useful"))
    negative = _matched(text, ("没帮上忙", "不相关", "不是这个问题", "没用", "错了", "过期", "not useful"))
    if positive and not negative:
        return "useful", positive
    if negative:
        return "not-useful", negative
    return None, ()


def _recall_signals(text: str) -> tuple[str, ...]:
    if _matched(text, ("typo", "拼写", "格式化一下", "改个文案", "简单改下")):
        return ()
    return _matched(
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
            "bytedcli",
            "rds",
            "bam",
            "mcp",
            "owner",
            "schema",
            "audit_rule_lib",
            "governance",
            "接口",
            "数据库",
            "表",
            "sql",
            "go test",
            "pytest",
        ),
    )


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
  "requires_recent_trace": false,
  "developer_mode": false,
  "suggested_next": "short next step",
  "recent_text_used": false
}}

Rules:
- Never choose draft_memory for ordinary summaries unless there is a reusable workflow lesson.
- draft_memory always requires confirmation before durable saving.
- label_feedback requires a recent recall trace.
- trace eval/replay are developer_eval, not normal product work.
- Memories are hints; live code, schema, docs, and command output remain source of truth.
""".strip()
