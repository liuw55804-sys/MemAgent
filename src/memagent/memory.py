from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter
import hashlib
import json
import math
import os
import re
import textwrap
from typing import Callable

from memagent.context import ProjectContext, context_payload, matches_project_context


DEFAULT_DOMAIN = "coding"
DEFAULT_KIND = "note"
DEFAULT_RECALL_STRATEGY = "bm25"
GENERIC_RECALL_TERMS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "before",
    "id",
    "code",
    "for",
    "how",
    "in",
    "issue",
    "is",
    "live",
    "of",
    "on",
    "or",
    "please",
    "problem",
    "project",
    "rule",
    "service",
    "should",
    "task",
    "that",
    "the",
    "this",
    "to",
    "what",
    "why",
    "with",
    "排查",
    "定位",
    "问题",
    "需求",
    "代码",
    "文档",
    "任务",
    "相关",
    "当前",
    "之前",
    "上次",
    "类似",
    "这个",
    "那个",
    "一下",
    "为什么",
    "怎么",
    "如何",
    "帮我",
    "进行",
    "处理",
    "解决",
    "补齐",
    "开发",
    "修改",
    "更新",
    "新增",
    "完成",
    "开始",
    "没有",
    "可以",
    "是否",
    "这次",
    "方式",
    "实现",
    "生成",
    "确认",
    "保存",
    "历史",
}
DISCRIMINATIVE_SHORT_CJK_TERMS = {
    "线上",
    "紧急",
    "合并",
    "冲突",
    "接口",
    "测试",
    "构建",
    "验证",
    "偏好",
    "习惯",
    "驳回",
    "交付",
    "移交",
    "分支",
    "工具",
    "数据库",
}
RECALL_FEEDBACK_RATINGS = {
    "useful",
    "not_useful",
    "neutral",
}
DEFAULT_PENDING_DRAFT_TTL_HOURS = 48

ALLOWED_RECALL_STRATEGIES = {
    "bm25",
    "keyword",
}

ALLOWED_DOMAINS = {
    "coding",
    "learning",
    "life",
    "career",
    "generic",
}

ALLOWED_KINDS = {
    "note",
    "tool_recipe",
    "skill_route",
    "data_entrypoint",
    "pitfall",
    "verification",
    "checklist",
    "preference",
    "decision",
    "workflow",
}


@dataclass(frozen=True)
class SavedMemory:
    path: Path
    identifier: str


@dataclass(frozen=True)
class SavedRecallTrace:
    path: Path
    identifier: str
    payload: dict[str, object]


@dataclass(frozen=True)
class SavedProcessTrace:
    path: Path
    identifier: str
    payload: dict[str, object]


@dataclass(frozen=True)
class SavedReflectionTrace:
    path: Path
    identifier: str
    payload: dict[str, object]


@dataclass(frozen=True)
class SavedPendingMemoryDraft:
    path: Path
    identifier: str
    payload: dict[str, object]


@dataclass(frozen=True)
class RecallTraceSummary:
    path: Path
    identifier: str
    created_at: str
    query: str
    repo_name: str | None
    total_matches: int
    top_match: str | None
    feedback_rating: str | None


@dataclass(frozen=True)
class MemoryMatch:
    path: Path
    score: float
    title: str
    domain: str
    kind: str
    strategy: str
    matched_terms: tuple[str, ...]
    lines: tuple[str, ...]


@dataclass(frozen=True)
class PackedMemoryContext:
    lines: tuple[str, ...]
    emitted_matches: int
    skipped_duplicate_lines: int
    truncated: bool
    line_budget: int
    char_budget: int


class MemoryStore:
    def __init__(
        self,
        home: Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.home = home.expanduser().resolve()
        self.memories_dir = self.home / "memories"
        self.traces_dir = self.home / "recall_traces"
        self.process_traces_dir = self.home / "process_traces"
        self.reflection_traces_dir = self.home / "reflection_traces"
        self.pending_drafts_dir = self.home / "pending_memory_drafts"
        self.pending_drafts_archive_dir = self.pending_drafts_dir / "archive"
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.memories_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_home_arg(cls, home: str | None) -> "MemoryStore":
        raw_home = home or os.environ.get("MEMAGENT_HOME") or "~/.memagent"
        return cls(Path(raw_home))

    def count_memory_cards(self) -> int:
        return sum(1 for _ in self.memories_dir.glob("*.memory.yaml"))

    def remember(
        self,
        *,
        text: str,
        topic: str | None,
        domain: str | None,
        kind: str | None,
        repo: str | None,
        module: str | None,
        triggers: list[str],
        exportable: bool,
    ) -> SavedMemory:
        now = self._now()
        identifier = f"mem_{now.strftime('%Y%m%d_%H%M%S_%f')}"
        title = topic or _derive_topic(text)
        normalized_domain = normalize_domain(domain)
        normalized_kind = normalize_kind(kind)
        trigger_values = triggers or _derive_triggers(text)
        body = _render_memory_card(
            identifier=identifier,
            created_at=now.isoformat(),
            domain=normalized_domain,
            kind=normalized_kind,
            topic=title,
            repo=repo,
            module=module,
            triggers=trigger_values,
            text=text,
            exportable=exportable,
        )
        path = self.memories_dir / f"{identifier}.memory.yaml"
        path.write_text(body, encoding="utf-8")
        return SavedMemory(path=path, identifier=identifier)

    def recall(
        self,
        query: str,
        *,
        context: ProjectContext,
        limit: int,
        strategy: str = DEFAULT_RECALL_STRATEGY,
        semantic_hints: tuple[str, ...] = (),
    ) -> list[MemoryMatch]:
        terms = retrieval_terms(
            " ".join(part for part in (query, *semantic_hints) if part),
            repo_name=context.repo_name,
        )
        if not terms:
            return []
        normalized_strategy = normalize_recall_strategy(strategy)
        candidates = []
        for path in sorted(self.memories_dir.glob("*.memory.yaml")):
            raw = path.read_text(encoding="utf-8", errors="replace")
            candidates.append((path, raw))
        if normalized_strategy == "bm25":
            scored = _score_bm25(candidates, terms)
        else:
            scored = _score_keyword(candidates, terms)

        matches: list[MemoryMatch] = []
        for path, raw, score, matched_terms in scored:
            haystack = raw.lower()
            if score <= 0:
                continue
            if context.repo_name and context.repo_name.lower() in haystack:
                score += _repo_scope_bonus(normalized_strategy)
            matches.append(
                MemoryMatch(
                    path=path,
                    score=score,
                    title=_extract_value(raw, "topic") or path.stem,
                    domain=_extract_value(raw, "domain") or DEFAULT_DOMAIN,
                    kind=_extract_value(raw, "kind") or DEFAULT_KIND,
                    strategy=normalized_strategy,
                    matched_terms=matched_terms,
                    lines=tuple(_important_lines(raw)),
                )
            )
        matches.sort(key=lambda item: (item.score, item.path.name), reverse=True)
        return matches[: max(limit, 0)]

    def compose_context(
        self,
        *,
        query: str,
        context: ProjectContext,
        matches: list[MemoryMatch],
        max_lines: int,
        show_sources: bool,
        show_reasons: bool = False,
    ) -> str:
        payload = self.build_recall_payload(
            query=query,
            context=context,
            matches=matches,
            max_lines=max_lines,
            show_sources=show_sources,
            show_reasons=show_reasons,
        )
        return str(payload["text"])

    def build_recall_payload(
        self,
        *,
        query: str,
        context: ProjectContext,
        matches: list[MemoryMatch],
        max_lines: int,
        show_sources: bool,
        show_reasons: bool = False,
        candidates: list[MemoryMatch] | None = None,
        retrieval: dict[str, object] | None = None,
    ) -> dict[str, object]:
        header = "[MemAgent recalled context]"
        context_bits = [
            f"cwd: {context.cwd}",
            f"repo: {context.repo_name or 'unknown'}",
        ]
        if context.branch:
            context_bits.append(f"branch: {context.branch}")

        lines = [header, f"- Task: {query}", f"- Context: {'; '.join(context_bits)}"]
        candidate_matches = candidates if candidates is not None else matches
        payload: dict[str, object] = {
            "schema_version": "memagent.recall.v2" if candidates is not None or retrieval is not None else "memagent.recall.v1",
            "query": query,
            "context": _context_payload(context),
            "total_matches": len(candidate_matches),
            "emitted_matches": len(matches),
            "matches": [_match_payload(match) for match in matches],
        }
        if candidates is not None:
            payload["candidates"] = [_match_payload(match) for match in candidate_matches]
        if retrieval is not None:
            payload["retrieval"] = retrieval
        if not matches:
            lines.append("- No related memories found.")
            payload["pack"] = {
                "emitted_matches": 0,
                "line_budget": 0,
                "char_budget": 0,
                "deduped": 0,
                "truncated": False,
                "lines": [],
            }
            payload["text"] = "\n".join(lines)
            return payload

        total_line_budget = max(max_lines, len(lines) + 2)
        memory_line_budget = max(total_line_budget - len(lines) - 1, 1)
        memory_char_budget = _context_char_budget(total_line_budget)
        packed = _pack_memory_matches(
            matches=matches,
            line_budget=memory_line_budget,
            char_budget=memory_char_budget,
            show_sources=show_sources,
            show_reasons=show_reasons,
        )
        lines.append(_render_pack_summary(packed=packed, total_matches=len(candidate_matches)))
        lines.extend(packed.lines)
        payload["pack"] = _pack_payload(packed)
        payload["text"] = "\n".join(lines)
        return payload

    def save_recall_trace(self, payload: dict[str, object], *, source: str) -> SavedRecallTrace:
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        now = self._now()
        identifier = f"trace_{now.strftime('%Y%m%d_%H%M%S_%f')}"
        path = self.traces_dir / f"{identifier}.json"
        trace_payload = dict(payload)
        trace_payload["trace"] = {
            "id": identifier,
            "created_at": now.isoformat(),
            "source": source,
            "path": str(path),
        }
        path.write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return SavedRecallTrace(path=path, identifier=identifier, payload=trace_payload)

    def save_process_trace(self, payload: dict[str, object], *, source: str) -> SavedProcessTrace:
        self.process_traces_dir.mkdir(parents=True, exist_ok=True)
        now = self._now()
        identifier = f"process_trace_{now.strftime('%Y%m%d_%H%M%S_%f')}"
        path = self.process_traces_dir / f"{identifier}.json"
        trace_payload = {
            "schema_version": "memagent.process_trace.v1",
            "trace": {
                "id": identifier,
                "created_at": now.isoformat(),
                "source": source,
                "path": str(path),
            },
            "process": payload,
        }
        path.write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return SavedProcessTrace(path=path, identifier=identifier, payload=trace_payload)

    def save_reflection_trace(self, payload: dict[str, object]) -> SavedReflectionTrace:
        self.reflection_traces_dir.mkdir(parents=True, exist_ok=True)
        now = self._now()
        identifier = f"reflection_{now.strftime('%Y%m%d_%H%M%S_%f')}"
        path = self.reflection_traces_dir / f"{identifier}.json"
        trace_payload = dict(payload)
        trace_payload["trace"] = {
            "id": identifier,
            "created_at": now.isoformat(),
            "source": "task_boundary_reflection",
            "path": str(path),
        }
        path.write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return SavedReflectionTrace(path=path, identifier=identifier, payload=trace_payload)

    def save_pending_memory_draft(
        self,
        *,
        draft: dict[str, object],
        context: ProjectContext,
        source: str = "user_requested",
        evidence: str | None = None,
    ) -> SavedPendingMemoryDraft:
        suggested = draft.get("suggested_remember") if isinstance(draft.get("suggested_remember"), dict) else draft
        text = str(suggested.get("text") or suggested.get("memory") or "").strip()
        topic = str(suggested.get("topic") or "").strip()
        kind = str(suggested.get("kind") or DEFAULT_KIND).strip()
        domain = str(suggested.get("domain") or DEFAULT_DOMAIN).strip()
        triggers_value = suggested.get("triggers")
        triggers = [str(item).strip() for item in triggers_value] if isinstance(triggers_value, list) else []
        triggers = [item for item in triggers if item]
        if not text or not topic:
            raise ValueError("pending memory draft requires topic and text")

        now = self._now()
        expires_at = now + timedelta(hours=_pending_draft_ttl_hours())
        identifier = f"pending_{now.strftime('%Y%m%d_%H%M%S_%f')}"
        path = self._pending_memory_draft_path(context)
        payload: dict[str, object] = {
            "schema_version": "memagent.pending_memory_draft.v2",
            "pending": {
                "id": identifier,
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "status": "pending",
                "path": str(path),
                "source": source,
                "evidence": evidence,
            },
            "context": _context_payload(context),
            "draft": {
                "domain": normalize_domain(domain),
                "kind": normalize_kind(kind),
                "topic": topic,
                "triggers": triggers or ["memory"],
                "text": text,
            },
            "quality_gate": _minimal_quality_gate_trace(draft.get("quality_gate")),
        }
        self.pending_drafts_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return SavedPendingMemoryDraft(path=path, identifier=identifier, payload=payload)

    def has_pending_memory_draft(self, *, context: ProjectContext) -> bool:
        self.expire_pending_memory_draft(context=context)
        return self._pending_memory_draft_path(context).exists()

    def pending_memory_draft_identifier(self, *, context: ProjectContext) -> str | None:
        self.expire_pending_memory_draft(context=context)
        path = self._pending_memory_draft_path(context)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        pending = payload.get("pending") if isinstance(payload, dict) and isinstance(payload.get("pending"), dict) else {}
        identifier = pending.get("id")
        return str(identifier) if identifier else None

    def load_pending_memory_draft(self, *, context: ProjectContext) -> dict[str, object]:
        self.expire_pending_memory_draft(context=context)
        path = self._pending_memory_draft_path(context)
        if not path.exists():
            raise ValueError("no pending memory draft found for this project")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid pending memory draft JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"invalid pending memory draft payload: {path}")
        return payload

    def discard_pending_memory_draft(self, *, context: ProjectContext) -> dict[str, object]:
        payload = self.load_pending_memory_draft(context=context)
        return self.archive_pending_memory_draft(
            context=context,
            status="rejected",
            payload=payload,
        )

    def expire_pending_memory_draft(self, *, context: ProjectContext) -> dict[str, object] | None:
        path = self._pending_memory_draft_path(context)
        if not path.exists():
            return None
        payload = _read_json_object(path)
        pending = payload.get("pending") if isinstance(payload.get("pending"), dict) else {}
        expires_at = _parse_datetime_value(pending.get("expires_at"))
        if expires_at is None:
            created_at = _parse_datetime_value(pending.get("created_at"))
            expires_at = (
                created_at + timedelta(hours=_pending_draft_ttl_hours())
                if created_at
                else None
            )
        if expires_at is None or expires_at > self._now():
            return None
        return self.archive_pending_memory_draft(
            context=context,
            status="expired",
            payload=payload,
        )

    def archive_pending_memory_draft(
        self,
        *,
        context: ProjectContext,
        status: str,
        payload: dict[str, object] | None = None,
        replacement_id: str | None = None,
        memory_id: str | None = None,
    ) -> dict[str, object]:
        if status not in {"expired", "replaced", "rejected", "confirmed"}:
            raise ValueError(f"invalid pending memory draft archive status: {status}")
        path = self._pending_memory_draft_path(context)
        value = payload or self.load_pending_memory_draft(context=context)
        pending = value.get("pending") if isinstance(value.get("pending"), dict) else {}
        pending = dict(pending)
        identifier = str(pending.get("id") or path.stem)
        pending.update(
            {
                "status": status,
                "resolved_at": self._now().isoformat(),
                "replacement_id": replacement_id,
                "memory_id": memory_id,
            }
        )
        value = dict(value)
        value["pending"] = pending
        self.pending_drafts_archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = self.pending_drafts_archive_dir / f"{identifier}.{status}.json"
        archive_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if path.exists():
            path.unlink()
        return value

    def remember_pending_memory_draft(self, *, context: ProjectContext) -> SavedMemory:
        path = self._pending_memory_draft_path(context)
        payload = self.load_pending_memory_draft(context=context)
        draft = payload.get("draft") if isinstance(payload, dict) and isinstance(payload.get("draft"), dict) else {}
        text = str(draft.get("text") or "").strip()
        topic = str(draft.get("topic") or "").strip()
        kind = str(draft.get("kind") or DEFAULT_KIND)
        domain = str(draft.get("domain") or DEFAULT_DOMAIN)
        triggers_value = draft.get("triggers")
        triggers = [str(item).strip() for item in triggers_value] if isinstance(triggers_value, list) else []
        if not text or not topic:
            raise ValueError("pending memory draft is missing topic or text")
        saved = self.remember(
            text=text,
            topic=topic,
            domain=domain,
            kind=kind,
            repo=context.repo_name,
            module=None,
            triggers=[item for item in triggers if item],
            exportable=False,
        )
        self.archive_pending_memory_draft(
            context=context,
            status="confirmed",
            payload=payload,
            memory_id=saved.identifier,
        )
        return saved

    def load_process_trace(self, identifier: str | None = None) -> dict[str, object]:
        path = self._resolve_process_trace_path(identifier)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid process trace JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"invalid process trace payload: {path}")
        return payload

    def list_recall_traces(self, *, limit: int = 5) -> list[RecallTraceSummary]:
        summaries: list[RecallTraceSummary] = []
        if not self.traces_dir.exists():
            return summaries
        for path in sorted(self.traces_dir.glob("trace_*.json"), reverse=True):
            if len(summaries) >= max(limit, 0):
                break
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            summaries.append(_trace_summary(path=path, payload=payload))
        return summaries

    def load_recall_trace(self, identifier: str | None = None) -> dict[str, object]:
        path = self._resolve_recall_trace_path(identifier)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid recall trace JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"invalid recall trace payload: {path}")
        return payload

    def compose_recall_trace_list(self, *, limit: int = 5) -> str:
        summaries = self.list_recall_traces(limit=limit)
        lines = ["[MemAgent recall traces]"]
        if not summaries:
            lines.append("- No recall traces found.")
            return "\n".join(lines)
        for summary in summaries:
            top = summary.top_match or "none"
            repo = summary.repo_name or "unknown"
            feedback = summary.feedback_rating or "unlabeled"
            lines.append(
                "- "
                f"{summary.identifier} | query={summary.query!r} | repo={repo} | "
                f"matches={summary.total_matches} | top={top} | feedback={feedback}"
            )
        return "\n".join(lines)

    def compose_recall_trace(self, *, identifier: str | None = None) -> str:
        payload = self.load_recall_trace(identifier)
        trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
        lines = ["[MemAgent recall trace]"]
        if trace:
            lines.append(f"- id: {trace.get('id', 'unknown')}")
            lines.append(f"- created_at: {trace.get('created_at', 'unknown')}")
            lines.append(f"- source: {trace.get('source', 'unknown')}")
        feedback = payload.get("feedback")
        if isinstance(feedback, dict):
            lines.append(f"- feedback: {feedback.get('rating', 'unknown')}")
            note = feedback.get("note")
            if note:
                lines.append(f"- feedback_note: {note}")
        adoption = payload.get("adoption")
        if isinstance(adoption, dict):
            lines.append(f"- adoption: {adoption.get('signal', 'unknown')}")
            note = adoption.get("note")
            if note:
                lines.append(f"- adoption_note: {note}")
        lines.append(f"- query: {payload.get('query', '')}")
        context = payload.get("context")
        if isinstance(context, dict):
            lines.append(f"- repo: {context.get('repo_name') or 'unknown'}")
            lines.append(f"- cwd: {context.get('cwd') or 'unknown'}")
        lines.append(f"- total_matches: {payload.get('total_matches', 0)}")
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            lines.extend(["", text])
        return "\n".join(lines)

    def label_recall_trace(
        self,
        identifier: str | None,
        *,
        rating: str,
        note: str | None,
    ) -> SavedRecallTrace:
        normalized_rating = normalize_recall_feedback_rating(rating)
        path = self._resolve_recall_trace_path(identifier)
        payload = self.load_recall_trace(str(path))
        now = datetime.now(timezone.utc)
        payload["feedback"] = {
            "rating": normalized_rating,
            "note": note or "",
            "labeled_at": now.isoformat(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
        return SavedRecallTrace(
            path=path,
            identifier=str(trace.get("id") or path.stem),
            payload=payload,
        )

    def mark_recall_adoption(
        self,
        identifier: str | None,
        *,
        signal: str,
        note: str | None,
    ) -> SavedRecallTrace:
        normalized_signal = signal.strip().lower().replace("-", "_")
        if normalized_signal not in {"applied", "executed", "corrected"}:
            raise ValueError("adoption signal must be applied, executed, or corrected")
        path = self._resolve_recall_trace_path(identifier)
        payload = self.load_recall_trace(str(path))
        now = self._now()
        payload["adoption"] = {
            "signal": normalized_signal,
            "note": (note or "").strip(),
            "recorded_at": now.isoformat(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
        return SavedRecallTrace(
            path=path,
            identifier=str(trace.get("id") or path.stem),
            payload=payload,
        )

    def compose_recall_trace_report(self, *, limit: int = 50) -> str:
        summaries = self.list_recall_traces(limit=limit)
        counts = {rating: 0 for rating in sorted(RECALL_FEEDBACK_RATINGS)}
        unlabeled = 0
        for summary in summaries:
            if summary.feedback_rating in counts:
                counts[summary.feedback_rating] += 1
            else:
                unlabeled += 1
        labeled = sum(counts.values())
        useful_rate = counts["useful"] / labeled if labeled else 0.0
        lines = [
            "[MemAgent recall trace report]",
            f"- traces inspected: {len(summaries)}",
            f"- labeled: {labeled}",
            f"- useful: {counts['useful']}",
            f"- not_useful: {counts['not_useful']}",
            f"- neutral: {counts['neutral']}",
            f"- unlabeled: {unlabeled}",
            f"- useful_rate: {useful_rate:.2f}",
        ]
        return "\n".join(lines)

    def _resolve_recall_trace_path(self, identifier: str | None) -> Path:
        if not self.traces_dir.exists():
            raise ValueError("no recall traces found")
        if not identifier:
            paths = sorted(self.traces_dir.glob("trace_*.json"), reverse=True)
            if not paths:
                raise ValueError("no recall traces found")
            return paths[0]
        raw = Path(identifier).expanduser()
        if raw.exists():
            return raw.resolve()
        stem = raw.stem if raw.suffix else str(raw)
        path = self.traces_dir / f"{stem}.json"
        if path.exists():
            return path
        raise ValueError(f"recall trace not found: {identifier}")

    def _resolve_process_trace_path(self, identifier: str | None) -> Path:
        if not self.process_traces_dir.exists():
            raise ValueError("no process traces found")
        if not identifier:
            paths = sorted(self.process_traces_dir.glob("process_trace_*.json"), reverse=True)
            if not paths:
                raise ValueError("no process traces found")
            return paths[0]
        raw = Path(identifier).expanduser()
        if raw.exists():
            return raw.resolve()
        stem = raw.stem if raw.suffix else str(raw)
        path = self.process_traces_dir / f"{stem}.json"
        if path.exists():
            return path
        raise ValueError(f"process trace not found: {identifier}")

    def _pending_memory_draft_path(self, context: ProjectContext) -> Path:
        identifier = f"pending_{_pending_draft_key(context)}"
        preferred = self.pending_drafts_dir / f"{identifier}.json"
        if preferred.exists() or not self.pending_drafts_dir.exists():
            return preferred
        for candidate in sorted(self.pending_drafts_dir.glob("pending_*.json"), reverse=True):
            payload = _read_json_object(candidate)
            candidate_context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
            if not matches_project_context(candidate_context, context):
                continue
            preferred.parent.mkdir(parents=True, exist_ok=True)
            candidate.replace(preferred)
            pending = payload.get("pending") if isinstance(payload.get("pending"), dict) else {}
            pending = dict(pending)
            pending["path"] = str(preferred)
            payload["pending"] = pending
            preferred.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            break
        return preferred


def _render_memory_card(
    *,
    identifier: str,
    created_at: str,
    domain: str,
    kind: str,
    topic: str,
    repo: str | None,
    module: str | None,
    triggers: list[str],
    text: str,
    exportable: bool,
) -> str:
    wrapped_text = textwrap.wrap(text.strip(), width=88) or [""]
    trigger_block = "\n".join(f"  - {quote_yaml(value)}" for value in triggers)
    note_block = "\n".join(f"  {line}" for line in wrapped_text)
    return "\n".join(
        [
            f"id: {quote_yaml(identifier)}",
            f"created_at: {quote_yaml(created_at)}",
            f"domain: {quote_yaml(domain)}",
            f"kind: {quote_yaml(kind)}",
            f"topic: {quote_yaml(topic)}",
            "scope:",
            f"  repo: {quote_yaml(repo or 'unknown')}",
            f"  module: {quote_yaml(module or 'unknown')}",
            "triggers:",
            trigger_block or "  - unknown",
            "stable_facts:",
            "  - Review the original note before turning this into a durable project rule.",
            "tool_recipes: []",
            "pitfalls:",
            f"  - {quote_yaml(text.strip())}",
            "next_time_prompt:",
            f"  - {quote_yaml(_next_time_prompt(text))}",
            "agents_md_suggestion:",
            "  - Keep this as MemAgent memory unless it becomes a stable project rule.",
            "sensitivity:",
            "  level: private",
            f"  exportable: {'true' if exportable else 'false'}",
            "source_note: |",
            note_block,
            "",
        ]
    )


def _context_payload(context: ProjectContext) -> dict[str, object]:
    return context_payload(context)


def _pending_draft_key(context: ProjectContext) -> str:
    identity = context.canonical_repo_id or str((context.git_root or context.cwd).resolve())
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return digest


def _pending_draft_ttl_hours() -> int:
    raw = os.environ.get("MEMAGENT_PENDING_DRAFT_TTL_HOURS", "").strip()
    if not raw:
        return DEFAULT_PENDING_DRAFT_TTL_HOURS
    try:
        return max(int(raw), 1)
    except ValueError:
        return DEFAULT_PENDING_DRAFT_TTL_HOURS


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_datetime_value(value: object) -> datetime | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _minimal_quality_gate_trace(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
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


def _match_payload(match: MemoryMatch) -> dict[str, object]:
    return {
        "path": str(match.path),
        "file": match.path.name,
        "score": match.score,
        "score_text": _format_score(match.score),
        "title": match.title,
        "domain": match.domain,
        "kind": match.kind,
        "strategy": match.strategy,
        "matched_terms": list(match.matched_terms),
        "lines": list(match.lines),
    }


def _pack_payload(packed: PackedMemoryContext) -> dict[str, object]:
    return {
        "emitted_matches": packed.emitted_matches,
        "line_budget": packed.line_budget,
        "char_budget": packed.char_budget,
        "deduped": packed.skipped_duplicate_lines,
        "truncated": packed.truncated,
        "lines": list(packed.lines),
    }


def _trace_summary(*, path: Path, payload: dict[str, object]) -> RecallTraceSummary:
    trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
    feedback = payload.get("feedback") if isinstance(payload.get("feedback"), dict) else {}
    top_match = None
    if matches and isinstance(matches[0], dict):
        raw_top = matches[0].get("title")
        top_match = str(raw_top) if raw_top is not None else None
    raw_rating = feedback.get("rating")
    return RecallTraceSummary(
        path=path,
        identifier=str(trace.get("id") or path.stem),
        created_at=str(trace.get("created_at") or ""),
        query=str(payload.get("query") or ""),
        repo_name=str(context.get("repo_name")) if context.get("repo_name") is not None else None,
        total_matches=_safe_int(payload.get("total_matches")),
        top_match=top_match,
        feedback_rating=str(raw_rating) if raw_rating is not None else None,
    )


def _safe_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _derive_topic(text: str) -> str:
    clean = " ".join(text.strip().split())
    if not clean:
        return "Untitled memory"
    return clean[:60]


def _derive_triggers(text: str) -> list[str]:
    tokens = _tokenize(text)
    seen: set[str] = set()
    triggers: list[str] = []
    for token in tokens:
        if token in seen or len(token) < 3:
            continue
        seen.add(token)
        triggers.append(token)
        if len(triggers) >= 8:
            break
    return triggers or ["memory"]


def _next_time_prompt(text: str) -> str:
    text = " ".join(text.strip().split())
    if not text:
        return "Check related MemAgent memory before continuing."
    return f"Before continuing, recall this lesson: {text[:120]}"


def normalize_domain(value: str | None) -> str:
    return _normalize_enum(
        value=value,
        default=DEFAULT_DOMAIN,
        allowed=ALLOWED_DOMAINS,
        field_name="domain",
    )


def normalize_kind(value: str | None) -> str:
    return _normalize_enum(
        value=value,
        default=DEFAULT_KIND,
        allowed=ALLOWED_KINDS,
        field_name="kind",
    )


def normalize_recall_strategy(value: str | None) -> str:
    normalized = (value or DEFAULT_RECALL_STRATEGY).strip().lower().replace("-", "_")
    if normalized not in ALLOWED_RECALL_STRATEGIES:
        allowed_values = ", ".join(sorted(ALLOWED_RECALL_STRATEGIES))
        raise ValueError(f"invalid recall strategy: {value}. Allowed values: {allowed_values}")
    return normalized


def normalize_recall_feedback_rating(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized not in RECALL_FEEDBACK_RATINGS:
        allowed_values = ", ".join(sorted(RECALL_FEEDBACK_RATINGS))
        raise ValueError(f"invalid feedback rating: {value}. Allowed values: {allowed_values}")
    return normalized


def _normalize_enum(
    *,
    value: str | None,
    default: str,
    allowed: set[str],
    field_name: str,
) -> str:
    normalized = (value or default).strip().lower().replace("-", "_")
    if not normalized:
        return default
    if normalized not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"invalid {field_name}: {value}. Allowed values: {allowed_values}")
    return normalized


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for candidate in _tokenize_all(text):
        if candidate and candidate not in seen:
            seen.add(candidate)
            tokens.append(candidate)
    return tokens


def retrieval_terms(text: str, *, repo_name: str | None = None) -> list[str]:
    repo_token = (repo_name or "").strip().lower()
    terms: list[str] = []
    for term in _tokenize(text):
        if term in GENERIC_RECALL_TERMS:
            continue
        if repo_token and term == repo_token:
            continue
        if _is_unstable_identifier(term):
            continue
        terms.append(term)
    return terms


def is_discriminative_recall_term(term: str) -> bool:
    normalized = term.strip().lower()
    if not normalized or normalized in GENERIC_RECALL_TERMS or _is_unstable_identifier(normalized):
        return False
    if _contains_cjk(normalized) and len(normalized) <= 2:
        return normalized in DISCRIMINATIVE_SHORT_CJK_TERMS
    return True


def _is_unstable_identifier(term: str) -> bool:
    if re.fullmatch(r"\d+", term):
        return True
    if re.fullmatch(r"[0-9a-f]{12,}", term, flags=re.IGNORECASE):
        return True
    return False


def _tokenize_all(text: str) -> list[str]:
    tokens: list[str] = []
    for raw_token in re.findall(r"[\w\u4e00-\u9fff]+", text):
        token = raw_token.lower()
        tokens.append(token)
        if _contains_cjk(token) and len(token) > 1:
            max_size = min(len(token), 4)
            for size in range(2, max_size + 1):
                tokens.extend(token[index : index + size] for index in range(len(token) - size + 1))
    return tokens


def _score_keyword(candidates: list[tuple[Path, str]], terms: list[str]) -> list[tuple[Path, str, float, tuple[str, ...]]]:
    return [
        (path, raw, float(score), matched_terms)
        for path, raw in candidates
        for score, matched_terms in [_score_terms(raw.lower(), terms)]
    ]


def _score_terms(haystack: str, terms: list[str]) -> tuple[int, tuple[str, ...]]:
    score = 0
    matched_terms: list[str] = []
    for term in terms:
        count = haystack.count(term)
        if count <= 0:
            continue
        score += count
        matched_terms.append(term)
    return score, tuple(matched_terms)


def _score_bm25(candidates: list[tuple[Path, str]], terms: list[str]) -> list[tuple[Path, str, float, tuple[str, ...]]]:
    if not candidates:
        return []
    token_counts: list[Counter[str]] = []
    doc_lengths: list[int] = []
    doc_freq: Counter[str] = Counter()
    for _, raw in candidates:
        tokens = _tokenize_all(raw)
        counts = Counter(tokens)
        token_counts.append(counts)
        doc_lengths.append(max(sum(counts.values()), 1))
        for term in terms:
            if counts.get(term, 0) > 0:
                doc_freq[term] += 1

    total_docs = len(candidates)
    avg_doc_length = sum(doc_lengths) / total_docs
    k1 = 1.5
    b = 0.75
    scored: list[tuple[Path, str, float, tuple[str, ...]]] = []
    for index, (path, raw) in enumerate(candidates):
        counts = token_counts[index]
        doc_length = doc_lengths[index]
        score = 0.0
        matched_terms: list[str] = []
        for term in terms:
            term_freq = counts.get(term, 0)
            if term_freq <= 0:
                continue
            matched_terms.append(term)
            idf = math.log(1 + (total_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            denominator = term_freq + k1 * (1 - b + b * doc_length / avg_doc_length)
            score += idf * (term_freq * (k1 + 1)) / denominator
        scored.append((path, raw, score, tuple(matched_terms)))
    return scored


def _repo_scope_bonus(strategy: str) -> float:
    return 0.75 if strategy == "bm25" else 3.0


def _pack_memory_matches(
    *,
    matches: list[MemoryMatch],
    line_budget: int,
    char_budget: int,
    show_sources: bool,
    show_reasons: bool,
) -> PackedMemoryContext:
    packed_lines: list[str] = []
    seen_items: set[str] = set()
    used_chars = 0
    emitted_matches = 0
    skipped_duplicates = 0
    truncated = False

    for match in matches:
        if len(packed_lines) >= line_budget:
            truncated = True
            break

        match_lines: list[str] = []
        prefix = _render_match_prefix(
            match=match,
            show_sources=show_sources,
            show_reasons=show_reasons,
        )
        fitted_prefix, prefix_truncated = _fit_pack_line(prefix, char_budget - used_chars)
        if not fitted_prefix:
            truncated = True
            break
        match_lines.append(fitted_prefix)
        used_chars += len(fitted_prefix) + 1
        if prefix_truncated:
            truncated = True

        for item in match.lines:
            normalized_item = _normalize_pack_item(item)
            if normalized_item in seen_items:
                skipped_duplicates += 1
                continue
            if len(packed_lines) + len(match_lines) >= line_budget:
                truncated = True
                break

            rendered_item = f"  - {item}"
            fitted_item, item_truncated = _fit_pack_line(rendered_item, char_budget - used_chars)
            if not fitted_item:
                truncated = True
                break
            match_lines.append(fitted_item)
            seen_items.add(normalized_item)
            used_chars += len(fitted_item) + 1
            if item_truncated:
                truncated = True

        packed_lines.extend(match_lines)
        emitted_matches += 1

    if emitted_matches < len(matches):
        truncated = True

    return PackedMemoryContext(
        lines=tuple(packed_lines),
        emitted_matches=emitted_matches,
        skipped_duplicate_lines=skipped_duplicates,
        truncated=truncated,
        line_budget=line_budget,
        char_budget=char_budget,
    )


def _render_match_prefix(*, match: MemoryMatch, show_sources: bool, show_reasons: bool) -> str:
    prefix = f"- Memory: {match.title} [{match.domain}/{match.kind}]"
    if show_sources:
        prefix += f" ({match.path.name})"
    if show_reasons:
        reason = f"score={_format_score(match.score)}; strategy={match.strategy}"
        if match.matched_terms:
            reason += f"; matched={', '.join(match.matched_terms[:8])}"
        prefix += f" | {reason}"
    return prefix


def _render_pack_summary(*, packed: PackedMemoryContext, total_matches: int) -> str:
    return (
        "- Pack: "
        f"{packed.emitted_matches}/{total_matches} memories; "
        f"budget={packed.line_budget} memory lines/{packed.char_budget} chars; "
        f"deduped={packed.skipped_duplicate_lines}; "
        f"truncated={'yes' if packed.truncated else 'no'}"
    )


def _context_char_budget(total_line_budget: int) -> int:
    return max(360, total_line_budget * 120)


def _fit_pack_line(line: str, remaining_chars: int) -> tuple[str, bool]:
    if remaining_chars <= 0:
        return "", False
    if len(line) <= remaining_chars:
        return line, False
    if remaining_chars <= 12:
        return "", True
    return line[: remaining_chars - 3].rstrip() + "...", True


def _normalize_pack_item(item: str) -> str:
    return " ".join(item.strip().lower().split())


def _format_score(score: float) -> str:
    if score.is_integer():
        return str(int(score))
    return f"{score:.2f}"


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _extract_value(raw: str, key: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.+)$", re.MULTILINE)
    match = pattern.search(raw)
    if not match:
        return None
    return match.group(1).strip().strip('"')


def _important_lines(raw: str) -> list[str]:
    wanted_sections = {"pitfalls", "next_time_prompt", "stable_facts"}
    lines: list[str] = []
    current: str | None = None
    for line in raw.splitlines():
        if not line.startswith(" ") and line.endswith(":"):
            current = line[:-1]
            continue
        if current in wanted_sections and line.strip().startswith("- "):
            item = line.strip()[2:].strip().strip('"')
            if item:
                lines.append(item)
        if len(lines) >= 4:
            break
    return lines


def quote_yaml(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
