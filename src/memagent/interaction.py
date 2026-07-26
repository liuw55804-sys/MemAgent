from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import time
from typing import Any

from memagent.context import ProjectContext, context_payload
from memagent.draft import draft_memory, render_memory_draft
from memagent.eval import run_trace_eval, run_trace_replay
from memagent.handoff import HandoffStore, draft_handoff_from_text, render_handoff_draft
from memagent.llm import default_semantic_mode
from memagent.memory import DEFAULT_RECALL_STRATEGY, MemoryMatch, MemoryStore, retrieval_terms
from memagent.relevance import select_relevant_memories
from memagent.router import RouteDecision, route_interaction


PROCESS_SCHEMA_VERSION = "memagent.process.v1"


@dataclass(frozen=True)
class ProcessResult:
    route: RouteDecision
    executed: bool
    result_text: str
    artifacts: dict[str, Any]
    writes: tuple[str, ...]
    warnings: tuple[str, ...]
    payload: dict[str, Any] | None = None

    def to_payload(self, *, context: ProjectContext | None = None) -> dict[str, Any]:
        payload = {
            "schema_version": PROCESS_SCHEMA_VERSION,
            "route": self.route.to_payload(context=context),
            "executed": self.executed,
            "result_text": self.result_text,
            "artifacts": self.artifacts,
            "writes": list(self.writes),
            "warnings": list(self.warnings),
            "payload": self.payload,
        }
        if context is not None:
            payload["context"] = context_payload(context)
        return payload


def process_interaction(
    *,
    message: str,
    recent_text: str,
    context: ProjectContext,
    store: MemoryStore,
    handoff_store: HandoffStore,
    provider: str = "heuristic",
    semantic_mode: str | None = None,
    llm_profile: str | None = None,
    llm_config_path: Path | None = None,
    draft_provider: str | None = None,
    draft_llm_profile: str | None = None,
    draft_llm_config_path: Path | None = None,
    allow_writes: bool = True,
    trace_recall: bool = True,
    limit: int = 5,
    max_emitted: int = 1,
    max_lines: int = 12,
    show_sources: bool = True,
    show_reasons: bool = True,
    strategy: str = DEFAULT_RECALL_STRATEGY,
    eval_workspace: Path | None = None,
    replay_workspace: Path | None = None,
    trace_none: bool = False,
    agent_suggested: bool = False,
    suggestion_evidence: str | None = None,
) -> ProcessResult:
    if agent_suggested:
        if not recent_text.strip():
            raise ValueError("agent-suggested memory requires a short lesson summary")
        route = RouteDecision(
            action="draft_memory",
            confidence=0.9,
            reason="The coding agent identified a reusable lesson at a meaningful task boundary.",
            signals=("agent_suggested", suggestion_evidence or "reusable_lesson"),
            user_message=message,
            provider="agent_suggested",
            requires_confirmation=True,
            recent_text_used=True,
            suggested_next="Show one short preview and wait for user confirmation.",
        )
    else:
        route = route_interaction(
            message,
            recent_text=recent_text,
            context=context,
            provider=provider,
            semantic_mode=semantic_mode,
            llm_profile=llm_profile,
            llm_config_path=llm_config_path,
            has_recent_trace=_has_recent_trace(store),
            has_pending_draft=store.has_pending_memory_draft(context=context),
        )
    active_mode = semantic_mode or ("llm" if provider == "openai-compatible" else default_semantic_mode())
    effective_draft_provider = draft_provider or os.environ.get("MEMAGENT_DRAFT_PROVIDER") or (
        "openai-compatible" if active_mode in {"llm", "hybrid"} else provider
    )
    effective_draft_profile = draft_llm_profile or os.environ.get("MEMAGENT_DRAFT_LLM_PROFILE") or llm_profile
    effective_draft_config = draft_llm_config_path or llm_config_path

    if route.action == "recall":
        return _with_process_trace(
            _process_recall(
                route=route,
                context=context,
                store=store,
                allow_writes=allow_writes,
                trace_recall=trace_recall,
                limit=limit,
                max_lines=max_lines,
                show_sources=show_sources,
                show_reasons=show_reasons,
                strategy=strategy,
                semantic_mode=active_mode,
                llm_profile=llm_profile,
                llm_config_path=llm_config_path,
                max_emitted=max_emitted,
            ),
            context=context,
            store=store,
            allow_writes=allow_writes,
            recent_text=recent_text,
            trace_none=trace_none,
        )
    if route.action == "draft_memory":
        return _with_process_trace(
            _process_draft_memory(
                route=route,
                context=context,
                recent_text=recent_text,
                store=store,
                allow_writes=allow_writes,
                provider=effective_draft_provider,
                llm_profile=effective_draft_profile,
                llm_config_path=effective_draft_config,
                source="agent_suggested" if agent_suggested else "user_requested",
                evidence=suggestion_evidence,
            ),
            context=context,
            store=store,
            allow_writes=allow_writes,
            recent_text=recent_text,
            trace_none=trace_none,
        )
    if route.action == "save_memory":
        return _with_process_trace(
            _process_save_memory(
                route=route,
                context=context,
                store=store,
                allow_writes=allow_writes,
            ),
            context=context,
            store=store,
            allow_writes=allow_writes,
            recent_text=recent_text,
            trace_none=trace_none,
        )
    if route.action == "reject_memory":
        return _with_process_trace(
            _process_reject_memory(
                route=route,
                context=context,
                store=store,
                allow_writes=allow_writes,
            ),
            context=context,
            store=store,
            allow_writes=allow_writes,
            recent_text=recent_text,
            trace_none=trace_none,
        )
    if route.action == "label_feedback":
        return _with_process_trace(
            _process_label_feedback(route=route, store=store, allow_writes=allow_writes),
            context=context,
            store=store,
            allow_writes=allow_writes,
            recent_text=recent_text,
            trace_none=trace_none,
        )
    if route.action == "handoff_show":
        return _with_process_trace(
            _process_handoff_show(route=route, context=context, handoff_store=handoff_store),
            context=context,
            store=store,
            allow_writes=allow_writes,
            recent_text=recent_text,
            trace_none=trace_none,
        )
    if route.action == "handoff_save":
        return _with_process_trace(
            _process_handoff_save(
                route=route,
                context=context,
                handoff_store=handoff_store,
                recent_text=recent_text,
                message=message,
                allow_writes=allow_writes,
            ),
            context=context,
            store=store,
            allow_writes=allow_writes,
            recent_text=recent_text,
            trace_none=trace_none,
        )
    if route.action == "developer_eval":
        return _with_process_trace(
            _process_developer_eval(
                route=route,
                store=store,
                eval_workspace=eval_workspace,
                replay_workspace=replay_workspace,
                allow_writes=allow_writes,
            ),
            context=context,
            store=store,
            allow_writes=allow_writes,
            recent_text=recent_text,
            trace_none=trace_none,
        )
    return _with_process_trace(
        ProcessResult(
            route=route,
            executed=False,
            result_text="[MemAgent process]\n- action: none\n- Continue normally without MemAgent.",
            artifacts={},
            writes=(),
            warnings=(),
        ),
        context=context,
        store=store,
        allow_writes=allow_writes,
        recent_text=recent_text,
        trace_none=trace_none,
    )


def render_process_result(result: ProcessResult, *, context: ProjectContext | None = None) -> str:
    payload = result.to_payload(context=context)
    lines = [
        "[MemAgent process]",
        f"- action: {payload['route']['action']}",
        f"- confidence: {payload['route']['confidence']:.2f}",
        f"- executed: {'yes' if payload['executed'] else 'no'}",
        f"- writes: {', '.join(payload['writes']) if payload['writes'] else '-'}",
    ]
    if payload["warnings"]:
        lines.append(f"- warnings: {'; '.join(payload['warnings'])}")
    lines.extend(["", result.result_text])
    return "\n".join(lines)


def _process_recall(
    *,
    route: RouteDecision,
    context: ProjectContext,
    store: MemoryStore,
    allow_writes: bool,
    trace_recall: bool,
    limit: int,
    max_lines: int,
    show_sources: bool,
    show_reasons: bool,
    strategy: str,
    semantic_mode: str,
    llm_profile: str | None,
    llm_config_path: Path | None,
    max_emitted: int,
) -> ProcessResult:
    query = route.query or route.user_message
    semantic_hints = _semantic_recall_hints(route)
    candidate_started = time.perf_counter()
    candidates = store.recall(
        query,
        context=context,
        limit=limit,
        strategy=strategy,
        semantic_hints=semantic_hints,
    )
    candidate_latency_ms = max(int(round((time.perf_counter() - candidate_started) * 1000)), 0)
    selection = select_relevant_memories(
        query,
        matches=candidates,
        context=context,
        semantic_mode=semantic_mode,
        llm_profile=llm_profile,
        llm_config_path=llm_config_path,
        max_emitted=max_emitted,
        state_home=store.home,
        apply_recall_cooldown=True,
    )
    matches = list(selection.emitted)
    retrieval_payload = selection.to_payload()
    retrieval_payload["candidate_generation_ms"] = candidate_latency_ms
    payload = store.build_recall_payload(
        query=query,
        context=context,
        matches=matches,
        max_lines=max_lines,
        show_sources=show_sources,
        show_reasons=show_reasons,
        candidates=candidates,
        retrieval=retrieval_payload,
    )
    writes: list[str] = []
    artifacts: dict[str, Any] = {
        "recall_considered": True,
        "candidates": len(candidates),
        "matches": len(matches),
        "emitted": len(matches),
        "abstained": selection.abstained,
        "candidate_generation_ms": candidate_latency_ms,
        "local_relevance_ms": selection.local_latency_ms,
        "relevance_gate_ms": selection.gate.latency_ms,
        "relevance_gate_attempted": selection.gate.attempted,
        "relevance_gate_fallback": selection.gate.fallback,
        "relevance_gate_skipped_cooldown": selection.gate.skipped_due_to_cooldown,
        "relevance_gate_failure_kind": selection.gate.failure_kind,
        "suppressed_by_cooldown": len(selection.suppressed_memory_ids),
        "recall_cooldown_scope": selection.cooldown_scope,
    }
    if semantic_hints:
        payload["retrieval_hints"] = list(semantic_hints)
        artifacts["retrieval_hints"] = list(semantic_hints)
    output_payload = payload
    if allow_writes and trace_recall:
        saved = store.save_recall_trace(payload, source="process")
        writes.append("recall_trace")
        artifacts["trace_id"] = saved.identifier
        artifacts["trace_path"] = str(saved.path)
        output_payload = saved.payload
    effective_route = route
    if selection.abstained:
        effective_route = replace(
            route,
            action="none",
            confidence=max(route.confidence, 0.75),
            reason=selection.reason,
            signals=(*route.signals, "recall_abstained"),
            suggested_next="Continue normally without recalled memory.",
        )
        result_text = "[MemAgent process]\n- action: none\n- No high-confidence project memory; continue normally."
    else:
        result_text = str(output_payload["text"])
    if artifacts.get("trace_id") and not selection.abstained:
        result_text = "\n".join(
            [
                result_text,
                "",
                "[MemAgent recall trace saved]",
                f"- id: {artifacts['trace_id']}",
                f"- path: {artifacts['trace_path']}",
            ]
        )
    return ProcessResult(
        route=effective_route,
        executed=not selection.abstained,
        result_text=result_text,
        artifacts=artifacts,
        writes=tuple(writes),
        warnings=(
            ("LLM relevance gate unavailable; local precision policy abstained.",)
            if selection.gate.fallback
            else ()
        ),
        payload=output_payload,
    )


def _semantic_recall_hints(route: RouteDecision) -> tuple[str, ...]:
    if "user_preference" not in route.signals:
        return ()
    return (
        "preference",
        "habit",
        "convention",
        "用户偏好",
        "用户习惯",
        "开发习惯",
        "协作约束",
    )


def _with_process_trace(
    result: ProcessResult,
    *,
    context: ProjectContext,
    store: MemoryStore,
    allow_writes: bool,
    recent_text: str,
    trace_none: bool,
) -> ProcessResult:
    if not allow_writes:
        return result
    if (
        result.route.action == "none"
        and not trace_none
        and not result.artifacts.get("recall_considered")
        and not result.artifacts.get("agent_suggested")
    ):
        return result
    process_payload = result.to_payload(context=context)
    if result.route.action == "draft_memory" and isinstance(process_payload.get("payload"), dict):
        draft_payload = dict(process_payload["payload"])
        draft_payload.pop("source_excerpt", None)
        quality_gate = draft_payload.get("quality_gate")
        if isinstance(quality_gate, dict):
            draft_payload["quality_gate"] = _minimal_quality_gate_trace(quality_gate)
        process_payload["payload"] = draft_payload
    process_payload["input"] = {
        "recent_text_present": bool(recent_text.strip()),
        "recent_text_chars": len(recent_text),
    }
    saved = store.save_process_trace(process_payload, source="process")
    artifacts = dict(result.artifacts)
    artifacts["process_trace_id"] = saved.identifier
    artifacts["process_trace_path"] = str(saved.path)
    writes = tuple([*result.writes, "process_trace"])
    return replace(result, artifacts=artifacts, writes=writes)


def _process_draft_memory(
    *,
    route: RouteDecision,
    context: ProjectContext,
    recent_text: str,
    store: MemoryStore,
    allow_writes: bool,
    provider: str,
    llm_profile: str | None,
    llm_config_path: Path | None,
    source: str,
    evidence: str | None,
) -> ProcessResult:
    source_text = recent_text.strip() or route.user_message
    draft = draft_memory(
        source_text,
        context=context,
        provider=provider,
        llm_profile=llm_profile,
        llm_config_path=llm_config_path,
    )
    payload = draft.to_payload(context=context)
    duplicate = (
        _find_duplicate_memory(store=store, context=context, text=draft.memory)
        if source == "agent_suggested"
        else None
    )
    if duplicate is not None:
        return ProcessResult(
            route=replace(route, action="none", reason="A sufficiently similar durable memory already exists."),
            executed=False,
            result_text="\n".join(
                [
                    "[MemAgent memory suggestion]",
                    "- status: duplicate",
                    f"- existing: {duplicate.title}",
                    "- no new preview was created",
                ]
            ),
            artifacts={
                "agent_suggested": source == "agent_suggested",
                "source": source,
                "status": "duplicate",
                "duplicate_memory": duplicate.path.name,
            },
            writes=(),
            warnings=(),
            payload=payload,
        )
    active_pending = (
        store.load_pending_memory_draft(context=context)
        if store.has_pending_memory_draft(context=context)
        else None
    )
    replaced_pending_id: str | None = None
    if active_pending is not None:
        pending_meta = (
            active_pending.get("pending")
            if isinstance(active_pending.get("pending"), dict)
            else {}
        )
        pending_source = str(pending_meta.get("source") or "user_requested")
        same_lesson = _pending_draft_similar(active_pending, payload)
        if source == "agent_suggested" and (pending_source != "agent_suggested" or same_lesson):
            return ProcessResult(
                route=replace(route, action="none", reason="A related project-scoped memory preview is already pending."),
                executed=False,
                result_text="[MemAgent proactive suggestion]\n- skipped: a related preview is still waiting for confirmation",
                artifacts={
                    "agent_suggested": True,
                    "status": "pending_exists",
                    "pending_draft_id": pending_meta.get("id"),
                    "pending_source": pending_source,
                },
                writes=(),
                warnings=(),
                payload=payload,
            )
        if allow_writes:
            replaced_pending_id = str(pending_meta.get("id") or "") or None
            store.archive_pending_memory_draft(
                context=context,
                status="replaced",
                payload=active_pending,
            )
    warnings = tuple(payload.get("warnings") or ())
    artifacts: dict[str, Any] = {
        "quality_label": draft.quality_label,
        "requires_confirmation": draft.requires_confirmation,
        "source": source,
        "agent_suggested": source == "agent_suggested",
        "suggestion_evidence": evidence,
        "replaced_pending_id": replaced_pending_id,
    }
    writes: tuple[str, ...] = ()
    if allow_writes:
        pending = store.save_pending_memory_draft(
            draft=payload,
            context=context,
            source=source,
            evidence=evidence,
        )
        artifacts["pending_draft_id"] = pending.identifier
        artifacts["pending_draft_path"] = str(pending.path)
        writes = (
            ("pending_memory_draft_replaced", "pending_memory_draft")
            if replaced_pending_id
            else ("pending_memory_draft",)
        )
    else:
        warnings = (*warnings, "writes disabled; memory draft was not saved for confirmation")
    result_text = render_memory_draft(draft, context=context)
    if source == "agent_suggested":
        replacement_line = (
            "- A different stale suggestion was archived and replaced."
            if replaced_pending_id
            else None
        )
        result_text = "\n".join(
            item
            for item in [
                "[MemAgent proactive suggestion]",
                "- This task formed one reusable lesson. Ask the user whether to save this preview.",
                replacement_line,
                "",
                result_text,
            ]
            if item is not None
        )
    return ProcessResult(
        route=route,
        executed=True,
        result_text=result_text,
        artifacts=artifacts,
        writes=writes,
        warnings=warnings,
        payload=payload,
    )


def _process_save_memory(
    *,
    route: RouteDecision,
    context: ProjectContext,
    store: MemoryStore,
    allow_writes: bool,
) -> ProcessResult:
    if not allow_writes:
        return ProcessResult(
            route=route,
            executed=False,
            result_text="[MemAgent memory save]\n- Confirmation received, but writes are disabled.",
            artifacts={},
            writes=(),
            warnings=("writes disabled; pending memory draft was not saved",),
        )
    try:
        pending = store.load_pending_memory_draft(context=context)
    except ValueError as exc:
        return ProcessResult(
            route=route,
            executed=False,
            result_text=f"[MemAgent memory save]\n- Could not save the pending draft: {exc}",
            artifacts={},
            writes=(),
            warnings=(str(exc),),
        )
    pending_meta = pending.get("pending") if isinstance(pending.get("pending"), dict) else {}
    pending_draft_id = str(pending_meta.get("id") or "") or None
    source = str(pending_meta.get("source") or "user_requested")
    try:
        saved = store.remember_pending_memory_draft(context=context)
    except ValueError as exc:
        return ProcessResult(
            route=route,
            executed=False,
            result_text=f"[MemAgent memory save]\n- Could not save the pending draft: {exc}",
            artifacts={},
            writes=(),
            warnings=(str(exc),),
        )
    return ProcessResult(
        route=route,
        executed=True,
        result_text="\n".join(
            [
                "[MemAgent memory saved]",
                f"- id: {saved.identifier}",
                f"- path: {saved.path}",
                "- source: confirmed pending memory preview",
            ]
        ),
        artifacts={
            "memory_id": saved.identifier,
            "memory_path": str(saved.path),
            "pending_draft_id": pending_draft_id,
            "source": source,
            "user_confirmed": True,
        },
        writes=("memory", "pending_memory_draft_cleared"),
        warnings=(),
    )


def _process_reject_memory(
    *,
    route: RouteDecision,
    context: ProjectContext,
    store: MemoryStore,
    allow_writes: bool,
) -> ProcessResult:
    if not allow_writes:
        return ProcessResult(
            route=route,
            executed=False,
            result_text="[MemAgent memory preview]\n- Rejection detected, but writes are disabled.",
            artifacts={},
            writes=(),
            warnings=("writes disabled; pending memory draft was not cleared",),
        )
    try:
        pending = store.discard_pending_memory_draft(context=context)
    except ValueError as exc:
        return ProcessResult(
            route=route,
            executed=False,
            result_text=f"[MemAgent memory preview]\n- No pending preview to reject: {exc}",
            artifacts={},
            writes=(),
            warnings=(str(exc),),
        )
    pending_meta = pending.get("pending") if isinstance(pending.get("pending"), dict) else {}
    source = str(pending_meta.get("source") or "user_requested")
    return ProcessResult(
        route=route,
        executed=True,
        result_text="[MemAgent memory preview]\n- Preview discarded; no durable memory was written.",
        artifacts={
            "pending_draft_id": pending_meta.get("id"),
            "source": source,
            "user_rejected": True,
        },
        writes=("pending_memory_draft_cleared",),
        warnings=(),
    )


def _find_duplicate_memory(*, store: MemoryStore, context: ProjectContext, text: str) -> MemoryMatch | None:
    candidates = store.recall(text, context=context, limit=3)
    selection = select_relevant_memories(
        text,
        matches=candidates,
        context=context,
        semantic_mode="heuristic",
        max_emitted=1,
    )
    if not selection.emitted:
        return None
    selected = selection.emitted[0]
    selected_id = selected.path.name.removesuffix(".memory.yaml")
    assessment = next(
        (item for item in selection.assessments if item.memory_id == selected_id),
        None,
    )
    if assessment is None or assessment.confidence < 0.88:
        return None
    return selected


def _pending_draft_similar(pending: dict[str, object], draft: dict[str, object]) -> bool:
    pending_draft = pending.get("draft") if isinstance(pending.get("draft"), dict) else {}
    suggested = draft.get("suggested_remember") if isinstance(draft.get("suggested_remember"), dict) else draft
    left = " ".join(
        str(pending_draft.get(key) or "")
        for key in ("topic", "text")
    ).strip()
    right = " ".join(
        str(suggested.get(key) or "")
        for key in ("topic", "text", "memory")
    ).strip()
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    left_terms = set(retrieval_terms(left))
    right_terms = set(retrieval_terms(right))
    union = left_terms | right_terms
    return bool(union) and len(left_terms & right_terms) / len(union) >= 0.55


def _process_label_feedback(*, route: RouteDecision, store: MemoryStore, allow_writes: bool) -> ProcessResult:
    rating = route.feedback_rating or "neutral"
    if not allow_writes:
        return ProcessResult(
            route=route,
            executed=False,
            result_text="[MemAgent feedback]\n- Feedback detected, but writes are disabled.",
            artifacts={"rating": rating},
            writes=(),
            warnings=("writes disabled; latest trace was not labeled",),
        )
    try:
        saved = store.label_recall_trace(None, rating=rating, note=route.reason)
    except ValueError as exc:
        return ProcessResult(
            route=route,
            executed=False,
            result_text=f"[MemAgent feedback]\n- Could not label feedback: {exc}",
            artifacts={"rating": rating},
            writes=(),
            warnings=(str(exc),),
        )
    return ProcessResult(
        route=route,
        executed=True,
        result_text="\n".join(
            [
                "[MemAgent recall trace labeled]",
                f"- id: {saved.identifier}",
                f"- rating: {rating.replace('-', '_')}",
                f"- path: {saved.path}",
            ]
        ),
        artifacts={"trace_id": saved.identifier, "trace_path": str(saved.path), "rating": rating},
        writes=("trace_feedback",),
        warnings=(),
        payload=saved.payload,
    )


def _process_handoff_show(
    *,
    route: RouteDecision,
    context: ProjectContext,
    handoff_store: HandoffStore,
) -> ProcessResult:
    return ProcessResult(
        route=route,
        executed=True,
        result_text=handoff_store.compose_latest(context=context, max_lines=40, show_source=True),
        artifacts={},
        writes=(),
        warnings=(),
    )


def _process_handoff_save(
    *,
    route: RouteDecision,
    context: ProjectContext,
    handoff_store: HandoffStore,
    recent_text: str,
    message: str,
    allow_writes: bool,
) -> ProcessResult:
    source = recent_text.strip() or message.strip()
    if not allow_writes:
        return ProcessResult(
            route=route,
            executed=False,
            result_text="[MemAgent handoff]\n- Handoff requested, but writes are disabled.",
            artifacts={},
            writes=(),
            warnings=("writes disabled; handoff was not saved",),
        )
    draft = draft_handoff_from_text(source, topic="Codex continuation handoff")
    saved = handoff_store.save_draft(context=context, draft=draft)
    rendered = "\n".join(
        [
            render_handoff_draft(draft),
            "",
            "[MemAgent handoff saved]",
            f"- project key: {saved.project_key}",
            f"- latest: {saved.latest_path}",
            f"- history: {saved.history_path}",
        ]
    )
    return ProcessResult(
        route=route,
        executed=True,
        result_text=rendered,
        artifacts={
            "project_key": saved.project_key,
            "latest_path": str(saved.latest_path),
            "history_path": str(saved.history_path),
        },
        writes=("handoff",),
        warnings=(),
    )


def _process_developer_eval(
    *,
    route: RouteDecision,
    store: MemoryStore,
    eval_workspace: Path | None,
    replay_workspace: Path | None,
    allow_writes: bool,
) -> ProcessResult:
    if not allow_writes or not eval_workspace or not replay_workspace:
        return ProcessResult(
            route=route,
            executed=False,
            result_text=(
                "[MemAgent developer eval]\n"
                "- Developer eval requested. Provide --eval-workspace and --replay-workspace to write reports."
            ),
            artifacts={},
            writes=(),
            warnings=("developer eval requires explicit workspaces",),
        )
    eval_result = run_trace_eval(store=store, workspace=eval_workspace)
    replay_result = run_trace_replay(store=store, workspace=replay_workspace)
    return ProcessResult(
        route=route,
        executed=True,
        result_text="\n".join(
            [
                "[MemAgent developer eval]",
                f"- trace eval: {eval_result.report_path}",
                f"- trace replay: {replay_result.report_path}",
            ]
        ),
        artifacts={
            "trace_eval_report": str(eval_result.report_path),
            "trace_replay_report": str(replay_result.report_path),
        },
        writes=("trace_eval_report", "trace_replay_report"),
        warnings=(),
    )


def _has_recent_trace(store: MemoryStore) -> bool:
    return bool(store.list_recall_traces(limit=1))


def _minimal_quality_gate_trace(value: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "provider",
        "attempted",
        "selected",
        "fallback",
        "final_source",
        "heuristic_score",
        "heuristic_label",
        "fallback_reason",
        "llm_score",
        "llm_label",
    )
    return {key: value[key] for key in keys if key in value}


def process_payload_json(result: ProcessResult, *, context: ProjectContext | None = None) -> str:
    return json.dumps(result.to_payload(context=context), ensure_ascii=False, indent=2)
