from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os
import re
import textwrap

from memagent.context import ProjectContext


DEFAULT_DOMAIN = "coding"
DEFAULT_KIND = "note"

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
class MemoryMatch:
    path: Path
    score: int
    title: str
    domain: str
    kind: str
    matched_terms: tuple[str, ...]
    lines: tuple[str, ...]


class MemoryStore:
    def __init__(self, home: Path) -> None:
        self.home = home.expanduser().resolve()
        self.memories_dir = self.home / "memories"
        self.memories_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_home_arg(cls, home: str | None) -> "MemoryStore":
        raw_home = home or os.environ.get("MEMAGENT_HOME") or "~/.memagent"
        return cls(Path(raw_home))

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
        now = datetime.now(timezone.utc)
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
    ) -> list[MemoryMatch]:
        terms = _tokenize(query)
        if not terms:
            return []
        matches: list[MemoryMatch] = []
        for path in sorted(self.memories_dir.glob("*.memory.yaml")):
            raw = path.read_text(encoding="utf-8", errors="replace")
            haystack = raw.lower()
            score, matched_terms = _score_terms(haystack, terms)
            if score <= 0:
                continue
            if context.repo_name and context.repo_name.lower() in haystack:
                score += 3
            matches.append(
                MemoryMatch(
                    path=path,
                    score=score,
                    title=_extract_value(raw, "topic") or path.stem,
                    domain=_extract_value(raw, "domain") or DEFAULT_DOMAIN,
                    kind=_extract_value(raw, "kind") or DEFAULT_KIND,
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
        header = "[MemAgent recalled context]"
        context_bits = [
            f"cwd: {context.cwd}",
            f"repo: {context.repo_name or 'unknown'}",
        ]
        if context.branch:
            context_bits.append(f"branch: {context.branch}")

        lines = [header, f"- Task: {query}", f"- Context: {'; '.join(context_bits)}"]
        if not matches:
            lines.append("- No related memories found.")
            return "\n".join(lines)

        remaining = max(max_lines - len(lines), 1)
        for match in matches:
            if remaining <= 0:
                break
            prefix = f"- Memory: {match.title} [{match.domain}/{match.kind}]"
            if show_sources:
                prefix += f" ({match.path.name})"
            if show_reasons:
                reason = f"score={match.score}"
                if match.matched_terms:
                    reason += f"; matched={', '.join(match.matched_terms[:8])}"
                prefix += f" | {reason}"
            lines.append(prefix)
            remaining -= 1
            for item in match.lines:
                if remaining <= 0:
                    break
                lines.append(f"  - {item}")
                remaining -= 1
        return "\n".join(lines)


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
            "  - Review the original note before turning this into a durable AGENTS.md rule.",
            "tool_recipes: []",
            "pitfalls:",
            f"  - {quote_yaml(text.strip())}",
            "next_time_prompt:",
            f"  - {quote_yaml(_next_time_prompt(text))}",
            "agents_md_suggestion:",
            "  - Keep this as MemAgent memory unless it becomes a stable project rule.",
            "sensitivity:",
            "  level: internal",
            f"  exportable: {'true' if exportable else 'false'}",
            "source_note: |",
            note_block,
            "",
        ]
    )


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
    for raw_token in re.findall(r"[\w\u4e00-\u9fff]+", text):
        token = raw_token.lower()
        candidates = [token]
        if _contains_cjk(token) and len(token) > 1:
            max_size = min(len(token), 4)
            for size in range(2, max_size + 1):
                candidates.extend(token[index : index + size] for index in range(len(token) - size + 1))
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                tokens.append(candidate)
    return tokens


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
