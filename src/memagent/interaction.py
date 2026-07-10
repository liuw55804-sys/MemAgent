from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any

from memagent.context import ProjectContext
from memagent.draft import draft_memory, render_memory_draft
from memagent.eval import run_trace_eval, run_trace_replay
from memagent.handoff import HandoffStore, draft_handoff_from_text, render_handoff_draft
from memagent.memory import DEFAULT_RECALL_STRATEGY, MemoryStore
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
            payload["context"] = {
                "cwd": str(context.cwd),
                "git_root": str(context.git_root) if context.git_root else None,
                "branch": context.branch,
                "repo_name": context.repo_name,
            }
        return payload


def process_interaction(
    *,
    message: str,
    recent_text: str,
    context: ProjectContext,
    store: MemoryStore,
    handoff_store: HandoffStore,
    provider: str = "heuristic",
    llm_profile: str | None = None,
    llm_config_path: Path | None = None,
    allow_writes: bool = True,
    trace_recall: bool = True,
    limit: int = 5,
    max_lines: int = 12,
    show_sources: bool = True,
    show_reasons: bool = True,
    strategy: str = DEFAULT_RECALL_STRATEGY,
    eval_workspace: Path | None = None,
    replay_workspace: Path | None = None,
    trace_none: bool = False,
) -> ProcessResult:
    route = route_interaction(
        message,
        recent_text=recent_text,
        context=context,
        provider=provider,
        llm_profile=llm_profile,
        llm_config_path=llm_config_path,
        has_recent_trace=_has_recent_trace(store),
        has_pending_draft=store.has_pending_memory_draft(context=context),
    )

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
                provider=provider,
                llm_profile=llm_profile,
                llm_config_path=llm_config_path,
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
) -> ProcessResult:
    query = route.query or route.user_message
    matches = store.recall(query, context=context, limit=limit, strategy=strategy)
    payload = store.build_recall_payload(
        query=query,
        context=context,
        matches=matches,
        max_lines=max_lines,
        show_sources=show_sources,
        show_reasons=show_reasons,
    )
    writes: list[str] = []
    artifacts: dict[str, Any] = {"matches": len(matches)}
    output_payload = payload
    if allow_writes and trace_recall:
        saved = store.save_recall_trace(payload, source="process")
        writes.append("recall_trace")
        artifacts["trace_id"] = saved.identifier
        artifacts["trace_path"] = str(saved.path)
        output_payload = saved.payload
    result_text = str(output_payload["text"])
    if artifacts.get("trace_id"):
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
        route=route,
        executed=True,
        result_text=result_text,
        artifacts=artifacts,
        writes=tuple(writes),
        warnings=(),
        payload=output_payload,
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
    if result.route.action == "none" and not trace_none:
        return result
    process_payload = result.to_payload(context=context)
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
) -> ProcessResult:
    source = recent_text.strip() or route.user_message
    draft = draft_memory(
        source,
        context=context,
        provider=provider,
        llm_profile=llm_profile,
        llm_config_path=llm_config_path,
    )
    payload = draft.to_payload(context=context)
    warnings = tuple(payload.get("warnings") or ())
    artifacts: dict[str, Any] = {
        "quality_label": draft.quality_label,
        "requires_confirmation": draft.requires_confirmation,
    }
    writes: tuple[str, ...] = ()
    if allow_writes:
        pending = store.save_pending_memory_draft(draft=payload, context=context)
        artifacts["pending_draft_id"] = pending.identifier
        artifacts["pending_draft_path"] = str(pending.path)
        writes = ("pending_memory_draft",)
    else:
        warnings = (*warnings, "writes disabled; memory draft was not saved for confirmation")
    return ProcessResult(
        route=route,
        executed=True,
        result_text=render_memory_draft(draft, context=context),
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
        artifacts={"memory_id": saved.identifier, "memory_path": str(saved.path)},
        writes=("memory", "pending_memory_draft_cleared"),
        warnings=(),
    )


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


def process_payload_json(result: ProcessResult, *, context: ProjectContext | None = None) -> str:
    return json.dumps(result.to_payload(context=context), ensure_ascii=False, indent=2)
