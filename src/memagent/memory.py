from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter
import math
import os
import re
import textwrap

from memagent.context import ProjectContext


DEFAULT_DOMAIN = "coding"
DEFAULT_KIND = "note"
DEFAULT_RECALL_STRATEGY = "bm25"

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
    def __init__(self, home: Path) -> None:
        self.home = home.expanduser().resolve()
        self.memories_dir = self.home / "memories"
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
        strategy: str = DEFAULT_RECALL_STRATEGY,
    ) -> list[MemoryMatch]:
        terms = _tokenize(query)
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
        lines.append(_render_pack_summary(packed=packed, total_matches=len(matches)))
        lines.extend(packed.lines)
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


def normalize_recall_strategy(value: str | None) -> str:
    normalized = (value or DEFAULT_RECALL_STRATEGY).strip().lower().replace("-", "_")
    if normalized not in ALLOWED_RECALL_STRATEGIES:
        allowed_values = ", ".join(sorted(ALLOWED_RECALL_STRATEGIES))
        raise ValueError(f"invalid recall strategy: {value}. Allowed values: {allowed_values}")
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
