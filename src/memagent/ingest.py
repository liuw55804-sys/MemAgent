from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import textwrap

from memagent.context import ProjectContext
from memagent.memory import quote_yaml


DEFAULT_CODEX_SESSIONS_ROOT = "~/.codex/sessions"
DEFAULT_CODEX_INGEST_WORKSPACE = "local_memory_demo/ingest_codex"


@dataclass(frozen=True)
class IngestCandidate:
    index: int
    title: str
    kind: str
    memory: str
    evidence: str
    triggers: tuple[str, ...]
    score: int
    source_path: Path
    source_line: int
    source_type: str
    cwd: str | None
    command: str | None


@dataclass(frozen=True)
class CodexIngestResult:
    workspace: Path
    report_path: Path
    candidates_dir: Path
    sessions_root: Path
    sessions_scanned: int
    records_scanned: int
    candidates: tuple[IngestCandidate, ...]


def run_codex_ingest(
    *,
    sessions_root: Path,
    workspace: Path,
    context: ProjectContext | None = None,
    limit: int = 5,
    max_candidates: int = 12,
    project_only: bool = False,
) -> CodexIngestResult:
    sessions_root = sessions_root.expanduser().resolve()
    workspace = workspace.expanduser().resolve()
    candidates_dir = workspace / "candidates"
    workspace.mkdir(parents=True, exist_ok=True)
    candidates_dir.mkdir(parents=True, exist_ok=True)
    for stale in candidates_dir.glob("candidate_*.md"):
        stale.unlink()

    session_paths = _recent_session_paths(sessions_root, limit=limit)
    raw_candidates: list[IngestCandidate] = []
    records_scanned = 0
    for path in session_paths:
        session_cwd: str | None = None
        for line_no, record in _iter_jsonl(path):
            records_scanned += 1
            payload = _payload(record)
            session_cwd = _record_cwd(payload) or session_cwd
            cwd = _record_cwd(payload) or session_cwd
            if project_only and context is not None and not _matches_context(cwd, context):
                continue
            for candidate in _record_candidates(
                payload=payload,
                source_path=path,
                source_line=line_no,
                cwd=cwd,
            ):
                raw_candidates.append(candidate)

    selected = _select_candidates(raw_candidates, max_candidates=max_candidates)
    indexed = tuple(
        IngestCandidate(
            index=index,
            title=candidate.title,
            kind=candidate.kind,
            memory=candidate.memory,
            evidence=candidate.evidence,
            triggers=candidate.triggers,
            score=candidate.score,
            source_path=candidate.source_path,
            source_line=candidate.source_line,
            source_type=candidate.source_type,
            cwd=candidate.cwd,
            command=candidate.command,
        )
        for index, candidate in enumerate(selected, start=1)
    )
    for candidate in indexed:
        path = candidates_dir / f"candidate_{candidate.index:03d}.md"
        path.write_text(render_ingest_candidate(candidate), encoding="utf-8")

    result = CodexIngestResult(
        workspace=workspace,
        report_path=workspace / "report.md",
        candidates_dir=candidates_dir,
        sessions_root=sessions_root,
        sessions_scanned=len(session_paths),
        records_scanned=records_scanned,
        candidates=indexed,
    )
    result.report_path.write_text(render_codex_ingest_report(result), encoding="utf-8")
    return result


def render_codex_ingest_report(result: CodexIngestResult) -> str:
    lines = [
        "# MemAgent Codex Transcript Ingest",
        "",
        "This report scans local Codex session JSONL files and drafts memory candidates for human review.",
        "It does not write durable memory cards.",
        "",
        "## Summary",
        "",
        f"- generated_at: `{datetime.now(timezone.utc).isoformat()}`",
        f"- sessions_root: `{result.sessions_root}`",
        f"- sessions_scanned: `{result.sessions_scanned}`",
        f"- records_scanned: `{result.records_scanned}`",
        f"- candidates: `{len(result.candidates)}`",
        f"- candidates_dir: `{result.candidates_dir}`",
        "",
        "## Flow",
        "",
        "```mermaid",
        "flowchart LR",
        '  A["Codex JSONL<br>session logs"] --> B["Rule extractor<br>commands + lessons"]',
        '  B --> C["Candidate drafts<br>review-only Markdown"]',
        '  C --> D["Human review<br>keep / edit / drop"]',
        '  D --> E["memagent remember<br>durable workflow memory"]',
        "```",
        "",
        "## Candidates",
        "",
    ]
    if not result.candidates:
        lines.extend(
            [
                "No candidates found.",
                "",
                "Try increasing `--limit`, disabling `--project-only`, or using a session that contains commands, failures, or explicit lesson signals.",
            ]
        )
        return "\n".join(lines)
    lines.append("| # | Kind | Score | Title | Draft |")
    lines.append("|---|---|---:|---|---|")
    for candidate in result.candidates:
        draft = result.candidates_dir / f"candidate_{candidate.index:03d}.md"
        lines.append(
            "| "
            f"{candidate.index} | `{candidate.kind}` | {candidate.score} | "
            f"{_escape_table(candidate.title)} | `{draft.name}` |"
        )
    lines.extend(
        [
            "",
            "## Review Guidance",
            "",
            "- Keep exact local engineering entrypoints when they are the reusable lesson.",
            "- Remove tokens, cookies, passwords, private keys, and long raw business samples before saving.",
            "- Edit the candidate text before `memagent remember` if the draft is too broad or too noisy.",
            "- Use these drafts as candidates only; live code, schemas, docs, and tool output remain the source of truth.",
        ]
    )
    return "\n".join(lines)


def render_ingest_candidate(candidate: IngestCandidate) -> str:
    trigger_args = " ".join(f"--trigger {quote_yaml(trigger)}" for trigger in candidate.triggers[:5])
    remember_command = (
        "PYTHONPATH=src python -m memagent.cli remember "
        f"--kind {quote_yaml(candidate.kind)} "
        f"--topic {quote_yaml(candidate.title)} "
        f"{trigger_args} "
        f"{quote_yaml(candidate.memory)}"
    )
    lines = [
        f"# MemAgent Ingest Candidate {candidate.index:03d}",
        "",
        "## Metadata",
        "",
        f"- review_status: `pending`",
        f"- kind: `{candidate.kind}`",
        f"- score: `{candidate.score}`",
        f"- source: `{candidate.source_path}`",
        f"- source_line: `{candidate.source_line}`",
        f"- source_type: `{candidate.source_type}`",
        f"- cwd: `{candidate.cwd or 'unknown'}`",
        f"- command: `{candidate.command or 'none'}`",
        f"- triggers: {', '.join(f'`{trigger}`' for trigger in candidate.triggers) or '`memory`'}",
        "",
        "## Candidate Memory",
        "",
        *_wrap(candidate.memory),
        "",
        "## Evidence",
        "",
        *_wrap(candidate.evidence),
        "",
        "## Suggested Remember Command",
        "",
        "```bash",
        remember_command,
        "```",
        "",
        "## Reviewer Notes",
        "",
        "- Keep this only if it is reusable beyond the current session.",
        "- Edit before saving if it contains transient details or too much raw output.",
    ]
    return "\n".join(lines)


def _recent_session_paths(root: Path, *, limit: int) -> list[Path]:
    if not root.exists():
        return []
    paths = [path for path in root.glob("**/*.jsonl") if path.is_file()]
    paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return paths[: max(limit, 0)]


def _iter_jsonl(path: Path):
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            yield line_no, record


def _payload(record: dict[str, object]) -> dict[str, object]:
    payload = record.get("payload")
    if isinstance(payload, dict):
        return payload
    return record


def _record_candidates(
    *,
    payload: dict[str, object],
    source_path: Path,
    source_line: int,
    cwd: str | None,
) -> list[IngestCandidate]:
    source_type = _source_type(payload)
    candidates: list[IngestCandidate] = []
    command = _extract_command(payload)
    if command:
        command = _redact_secrets(command)
        exit_code = _safe_int(payload.get("exit_code"))
        text = _clean(command)
        if _interesting_command(text) or exit_code not in (None, 0):
            kind = "tool_recipe" if exit_code in (None, 0) else "pitfall"
            memory = _command_memory(text, payload=payload, exit_code=exit_code)
            evidence = _command_evidence(text, payload=payload, exit_code=exit_code)
            candidates.append(
                _candidate(
                    title=_title_from_memory(memory),
                    kind=kind,
                    memory=memory,
                    evidence=evidence,
                    source_path=source_path,
                    source_line=source_line,
                    source_type=source_type,
                    cwd=cwd,
                    command=text,
                    score=_command_score(text, exit_code),
                )
            )

    for text in _extract_texts(payload):
        clean = _clean(_redact_secrets(text))
        if not _has_lesson_signal(clean):
            continue
        memory = _text_memory(clean)
        candidates.append(
            _candidate(
                title=_title_from_memory(memory),
                kind=_text_kind(clean),
                memory=memory,
                evidence=clean,
                source_path=source_path,
                source_line=source_line,
                source_type=source_type,
                cwd=cwd,
                command=command,
                score=_text_score(clean),
            )
        )
    return candidates


def _candidate(
    *,
    title: str,
    kind: str,
    memory: str,
    evidence: str,
    source_path: Path,
    source_line: int,
    source_type: str,
    cwd: str | None,
    command: str | None,
    score: int,
) -> IngestCandidate:
    return IngestCandidate(
        index=0,
        title=title,
        kind=kind,
        memory=memory[:600],
        evidence=evidence[:900],
        triggers=tuple(_derive_triggers(f"{title} {memory} {command or ''}")),
        score=score,
        source_path=source_path,
        source_line=source_line,
        source_type=source_type,
        cwd=cwd,
        command=command,
    )


def _select_candidates(candidates: list[IngestCandidate], *, max_candidates: int) -> list[IngestCandidate]:
    seen: set[str] = set()
    selected: list[IngestCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (item.score, item.source_path.name, -item.source_line), reverse=True):
        key = _dedupe_key(candidate.memory)
        if key in seen:
            continue
        seen.add(key)
        selected.append(candidate)
        if len(selected) >= max(max_candidates, 0):
            break
    return selected


def _source_type(payload: dict[str, object]) -> str:
    raw_type = payload.get("type")
    if raw_type is None:
        return "unknown"
    return str(raw_type)


def _record_cwd(payload: dict[str, object]) -> str | None:
    raw = payload.get("cwd")
    if isinstance(raw, str) and raw:
        return raw
    git = payload.get("git")
    if isinstance(git, dict):
        root = git.get("root") or git.get("git_root")
        if isinstance(root, str) and root:
            return root
    return None


def _matches_context(cwd: str | None, context: ProjectContext) -> bool:
    if not cwd:
        return False
    cwd_text = str(Path(cwd).expanduser().resolve())
    roots = [str(context.cwd)]
    if context.git_root:
        roots.append(str(context.git_root))
    return any(cwd_text == root or cwd_text.startswith(f"{root}/") for root in roots)


def _extract_command(payload: dict[str, object]) -> str | None:
    for key in ("command", "cmd"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    arguments = payload.get("arguments")
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments if _looks_like_command(arguments) else None
        if isinstance(parsed, dict):
            for key in ("cmd", "command"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    if isinstance(arguments, dict):
        for key in ("cmd", "command"):
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _extract_texts(value: object) -> list[str]:
    texts: list[str] = []
    if isinstance(value, str):
        if len(value.strip()) >= 12:
            texts.append(value)
        return texts
    if isinstance(value, list):
        for item in value:
            texts.extend(_extract_texts(item))
        return texts
    if not isinstance(value, dict):
        return texts
    for key in ("message", "text", "summary", "output"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            texts.append(item)
    content = value.get("content")
    if isinstance(content, (list, dict, str)):
        texts.extend(_extract_texts(content))
    text_elements = value.get("text_elements")
    if isinstance(text_elements, (list, dict, str)):
        texts.extend(_extract_texts(text_elements))
    return texts


def _command_memory(command: str, *, payload: dict[str, object], exit_code: int | None) -> str:
    if exit_code not in (None, 0):
        error_line = _first_error_line(payload)
        if error_line:
            return f"Command `{command}` failed with `{error_line}`; record the failure before retrying this path."
        return f"Command `{command}` failed; treat this as a pitfall and inspect the failure before repeating it."
    if "bytedcli" in command.lower():
        return f"Reusable bytedcli recipe from Codex session: `{command}`."
    if "memagent" in command.lower():
        return f"Reusable MemAgent workflow command from Codex session: `{command}`."
    return f"Reusable command from Codex session: `{command}`."


def _command_evidence(command: str, *, payload: dict[str, object], exit_code: int | None) -> str:
    parts = [f"command: {command}"]
    if exit_code is not None:
        parts.append(f"exit_code: {exit_code}")
    error_line = _first_error_line(payload)
    if error_line:
        parts.append(f"signal: {error_line}")
    cwd = _record_cwd(payload)
    if cwd:
        parts.append(f"cwd: {cwd}")
    return "; ".join(parts)


def _text_memory(text: str) -> str:
    line = _first_sentence(text)
    return line[:600]


def _text_kind(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ("pitfall", "failed", "error", "timeout", "坑", "失败", "别", "不要")):
        return "pitfall"
    if any(word in lower for word in ("verify", "verified", "test", "验证", "自测", "通过")):
        return "verification"
    if any(word in lower for word in ("command", "recipe", "bytedcli", "curl", "命令", "用法")):
        return "tool_recipe"
    return "workflow"


def _interesting_command(command: str) -> bool:
    lower = command.lower()
    return any(
        keyword in lower
        for keyword in (
            "bytedcli",
            "memagent",
            "mcp",
            "agents-install",
            "agents-doctor",
            "trace replay",
            "trace eval",
            "handoff",
            "rds",
            "bam",
            "curl",
            "go test",
            "pytest",
            "unittest",
        )
    )


def _has_lesson_signal(text: str) -> bool:
    lower = text.lower()
    return len(text) >= 24 and any(
        keyword in lower
        for keyword in (
            "remember",
            "memory",
            "lesson",
            "pitfall",
            "next time",
            "verified",
            "reusable",
            "handoff",
            "trace replay",
            "trace eval",
            "记住",
            "沉淀",
            "下次",
            "踩坑",
            "经验",
            "验证",
            "通过",
            "复用",
            "交接",
        )
    )


def _command_score(command: str, exit_code: int | None) -> int:
    score = 40
    lower = command.lower()
    if "bytedcli" in lower:
        score += 35
    if "memagent" in lower:
        score += 25
    if "rds" in lower or "bam" in lower:
        score += 20
    if exit_code not in (None, 0):
        score += 25
    return score


def _text_score(text: str) -> int:
    score = 35
    lower = text.lower()
    for keyword in ("记住", "沉淀", "next time", "pitfall", "下次", "踩坑", "verified", "通过"):
        if keyword in lower:
            score += 12
    return min(score, 95)


def _first_error_line(payload: dict[str, object]) -> str | None:
    for key in ("stderr", "formatted_output", "aggregated_output", "output"):
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        for line in value.splitlines():
            clean = _clean(_redact_secrets(line))
            if clean:
                return clean[:180]
    return None


def _safe_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _looks_like_command(text: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9_./-]+(\s+|$)", text.strip()))


def _first_sentence(text: str) -> str:
    clean = _clean(text)
    for separator in ("。", "\n", ". "):
        if separator in clean:
            head = clean.split(separator, 1)[0].strip()
            if len(head) >= 16:
                return head + ("。" if separator == "。" else ".")
    return clean


def _title_from_memory(memory: str) -> str:
    title = re.sub(r"`([^`]+)`", r"\1", memory)
    title = _clean(title)
    return title[:72] or "Codex ingest candidate"


def _derive_triggers(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", text)
    seen: set[str] = set()
    triggers: list[str] = []
    for token in tokens:
        normalized = token.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        triggers.append(token)
        if len(triggers) >= 8:
            break
    return triggers or ["codex"]


def _dedupe_key(text: str) -> str:
    return re.sub(r"\W+", "", text.lower())[:160]


def _redact_secrets(text: str) -> str:
    patterns = [
        (r"(?i)(authorization:\s*bearer\s+)[^\s\"']+", r"\1<redacted>"),
        (r"(?i)(token=)[^\s&]+", r"\1<redacted>"),
        (r"(?i)(password=)[^\s&]+", r"\1<redacted>"),
        (r"(?i)(cookie:\s*)[^\"']+", r"\1<redacted>"),
        (r"\bsk-[A-Za-z0-9_-]{12,}\b", "<redacted-openai-key>"),
    ]
    result = text
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result)
    return result


def _clean(text: str) -> str:
    return " ".join(text.strip().split())


def _wrap(text: str) -> list[str]:
    return textwrap.wrap(text, width=88) or [""]


def _escape_table(text: str) -> str:
    return text.replace("|", "\\|")
