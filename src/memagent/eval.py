from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from memagent.context import ProjectContext
from memagent.memory import MemoryStore


STRATEGIES = ("bm25", "keyword")


@dataclass(frozen=True)
class MemoryFixture:
    topic: str
    text: str
    kind: str
    triggers: tuple[str, ...]


@dataclass(frozen=True)
class EvalCase:
    query: str
    expected_topic: str


@dataclass(frozen=True)
class EvalCaseResult:
    query: str
    expected_topic: str
    top_topic: str | None
    rank: int | None
    reciprocal_rank: float
    top_score: float
    matched_terms: tuple[str, ...]

    @property
    def hit_at_1(self) -> bool:
        return self.rank == 1


@dataclass(frozen=True)
class EvalStrategyResult:
    strategy: str
    cases: tuple[EvalCaseResult, ...]

    @property
    def hit_at_1(self) -> float:
        if not self.cases:
            return 0.0
        return sum(1 for case in self.cases if case.hit_at_1) / len(self.cases)

    @property
    def mrr(self) -> float:
        if not self.cases:
            return 0.0
        return sum(case.reciprocal_rank for case in self.cases) / len(self.cases)


@dataclass(frozen=True)
class RecallEvalResult:
    workspace: Path
    project_dir: Path
    memory_home: Path
    report_path: Path
    report: str
    strategy_results: tuple[EvalStrategyResult, ...]


@dataclass(frozen=True)
class TraceEvalCase:
    identifier: str
    created_at: str
    query: str
    repo_name: str | None
    top_match: str | None
    feedback_rating: str | None
    feedback_note: str
    total_matches: int
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class TraceEvalResult:
    workspace: Path
    memory_home: Path
    report_path: Path
    report: str
    cases: tuple[TraceEvalCase, ...]
    useful: int
    not_useful: int
    neutral: int
    unlabeled: int

    @property
    def traces_inspected(self) -> int:
        return len(self.cases)

    @property
    def labeled(self) -> int:
        return self.useful + self.not_useful + self.neutral

    @property
    def useful_rate(self) -> float:
        if not self.labeled:
            return 0.0
        return self.useful / self.labeled


@dataclass(frozen=True)
class TraceReplayCase:
    identifier: str
    query: str
    repo_name: str | None
    feedback_rating: str | None
    original_top: str | None
    strategy: str
    replay_top: str | None
    replay_score: float
    matched_terms: tuple[str, ...]
    same_top: bool


@dataclass(frozen=True)
class TraceReplayStrategyResult:
    strategy: str
    cases: tuple[TraceReplayCase, ...]

    @property
    def top_stability(self) -> float:
        if not self.cases:
            return 0.0
        return sum(1 for case in self.cases if case.same_top) / len(self.cases)

    @property
    def useful_top_stability(self) -> float:
        useful_cases = [case for case in self.cases if case.feedback_rating == "useful"]
        if not useful_cases:
            return 0.0
        return sum(1 for case in useful_cases if case.same_top) / len(useful_cases)


@dataclass(frozen=True)
class TraceReplayResult:
    workspace: Path
    memory_home: Path
    report_path: Path
    report: str
    strategy_results: tuple[TraceReplayStrategyResult, ...]

    @property
    def traces_inspected(self) -> int:
        if not self.strategy_results:
            return 0
        return len(self.strategy_results[0].cases)


def run_recall_eval(*, workspace: Path) -> RecallEvalResult:
    workspace = workspace.expanduser().resolve()
    if workspace.exists():
        shutil.rmtree(workspace)
    project_dir = workspace / "project"
    memory_home = workspace / "memagent_home"
    project_dir.mkdir(parents=True, exist_ok=True)
    memory_home.mkdir(parents=True, exist_ok=True)
    (project_dir / "pyproject.toml").write_text("[project]\nname = \"eval-demo\"\n", encoding="utf-8")

    store = MemoryStore(memory_home)
    for fixture in memory_fixtures():
        store.remember(
            text=fixture.text,
            topic=fixture.topic,
            domain="coding",
            kind=fixture.kind,
            repo="eval_demo",
            module=None,
            triggers=list(fixture.triggers),
            exportable=True,
        )

    context = ProjectContext(
        cwd=project_dir,
        git_root=project_dir,
        branch="main",
        repo_name="eval_demo",
        recent_files=(),
        agents_files=(),
    )
    results = tuple(_evaluate_strategy(store, context, strategy) for strategy in STRATEGIES)
    report_path = workspace / "report.md"
    report = render_recall_eval_report(
        workspace=workspace,
        project_dir=project_dir,
        memory_home=memory_home,
        strategy_results=results,
    )
    report_path.write_text(report, encoding="utf-8")
    return RecallEvalResult(
        workspace=workspace,
        project_dir=project_dir,
        memory_home=memory_home,
        report_path=report_path,
        report=report,
        strategy_results=results,
    )


def run_trace_eval(*, store: MemoryStore, workspace: Path, limit: int = 50) -> TraceEvalResult:
    workspace = workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    summaries = store.list_recall_traces(limit=limit)
    cases = tuple(_trace_eval_case(store.load_recall_trace(summary.identifier)) for summary in summaries)
    useful = sum(1 for case in cases if case.feedback_rating == "useful")
    not_useful = sum(1 for case in cases if case.feedback_rating == "not_useful")
    neutral = sum(1 for case in cases if case.feedback_rating == "neutral")
    unlabeled = len(cases) - useful - not_useful - neutral
    report = render_trace_eval_report(
        workspace=workspace,
        memory_home=store.home,
        cases=cases,
        useful=useful,
        not_useful=not_useful,
        neutral=neutral,
        unlabeled=unlabeled,
    )
    report_path = workspace / "report.md"
    report_path.write_text(report, encoding="utf-8")
    return TraceEvalResult(
        workspace=workspace,
        memory_home=store.home,
        report_path=report_path,
        report=report,
        cases=cases,
        useful=useful,
        not_useful=not_useful,
        neutral=neutral,
        unlabeled=unlabeled,
    )


def run_trace_replay(
    *,
    store: MemoryStore,
    workspace: Path,
    limit: int = 50,
    strategies: tuple[str, ...] = STRATEGIES,
) -> TraceReplayResult:
    workspace = workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    summaries = store.list_recall_traces(limit=limit)
    payloads = tuple(store.load_recall_trace(summary.identifier) for summary in summaries)
    strategy_results = tuple(_replay_strategy(store, payloads, strategy) for strategy in strategies)
    report = render_trace_replay_report(
        workspace=workspace,
        memory_home=store.home,
        strategy_results=strategy_results,
    )
    report_path = workspace / "report.md"
    report_path.write_text(report, encoding="utf-8")
    return TraceReplayResult(
        workspace=workspace,
        memory_home=store.home,
        report_path=report_path,
        report=report,
        strategy_results=strategy_results,
    )


def memory_fixtures() -> tuple[MemoryFixture, ...]:
    return (
        MemoryFixture(
            topic="Attribution accuracy workflow",
            kind="workflow",
            triggers=("validation", "accuracy", "labels"),
            text=(
                "For validation accuracy checks, compare model labels with human-reviewed labels, "
                "then sample mismatches by primary-key ranges."
            ),
        ),
        MemoryFixture(
            topic="Repeated accuracy noise",
            kind="note",
            triggers=("accuracy",),
            text="accuracy " * 40,
        ),
        MemoryFixture(
            topic="database JSON aggregation pitfall",
            kind="pitfall",
            triggers=("database", "JSON", "aggregation"),
            text="database JSON aggregation can time out; sample first and split by primary-key ranges.",
        ),
        MemoryFixture(
            topic="Skill route for maintainer diagnosis",
            kind="skill_route",
            triggers=("maintainer", "diagnosis", "skill"),
            text="For maintainer diagnosis tasks, use the existing diagnostics helper skill before manual searching.",
        ),
        MemoryFixture(
            topic="AGENTS install workflow",
            kind="verification",
            triggers=("AGENTS", "doctor", "install"),
            text="Use agents-install --write, then agents-doctor, before relying on natural-language triggers.",
        ),
    )


def eval_cases() -> tuple[EvalCase, ...]:
    return (
        EvalCase(
            query="validation accuracy label mismatch",
            expected_topic="Attribution accuracy workflow",
        ),
        EvalCase(
            query="database JSON aggregation timeout",
            expected_topic="database JSON aggregation pitfall",
        ),
        EvalCase(
            query="maintainer diagnosis skill route",
            expected_topic="Skill route for maintainer diagnosis",
        ),
        EvalCase(
            query="AGENTS install doctor ready",
            expected_topic="AGENTS install workflow",
        ),
    )


def render_recall_eval_report(
    *,
    workspace: Path,
    project_dir: Path,
    memory_home: Path,
    strategy_results: tuple[EvalStrategyResult, ...],
) -> str:
    lines = [
        "# MemAgent Recall Evaluation",
        "",
        "This report is generated from export-safe mock memories.",
        "",
        f"- Workspace: `{workspace}`",
        f"- Project: `{project_dir}`",
        f"- Memory home: `{memory_home}`",
        f"- Memories: `{len(memory_fixtures())}`",
        f"- Queries: `{len(eval_cases())}`",
        "",
        "## Summary",
        "",
        "| Strategy | Hit@1 | MRR |",
        "|---|---:|---:|",
    ]
    for result in strategy_results:
        lines.append(f"| {result.strategy} | {result.hit_at_1:.2f} | {result.mrr:.2f} |")

    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Strategy | Query | Expected | Top | Rank | Score | Matched |",
            "|---|---|---|---|---:|---:|---|",
        ]
    )
    for result in strategy_results:
        for case in result.cases:
            rank = "-" if case.rank is None else str(case.rank)
            top = case.top_topic or "-"
            matched = ", ".join(case.matched_terms) if case.matched_terms else "-"
            lines.append(
                "| "
                f"{result.strategy} | {case.query} | {case.expected_topic} | {top} | "
                f"{rank} | {case.top_score:.2f} | {matched} |"
            )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `hit@1` measures whether the expected memory is ranked first.",
            "- `MRR` is mean reciprocal rank across all mock queries.",
            "- `keyword` is retained as a transparent baseline; `bm25` is the default retriever.",
            "",
        ]
    )
    return "\n".join(lines)


def render_trace_replay_report(
    *,
    workspace: Path,
    memory_home: Path,
    strategy_results: tuple[TraceReplayStrategyResult, ...],
) -> str:
    traces_inspected = len(strategy_results[0].cases) if strategy_results else 0
    lines = [
        "# MemAgent Trace Replay Evaluation",
        "",
        "This report replays saved recall trace queries against the current memory store.",
        "It compares each replayed top match with the top match saved in the original trace.",
        "",
        f"- Workspace: `{workspace}`",
        f"- Memory home: `{memory_home}`",
        f"- Traces inspected: `{traces_inspected}`",
        "",
        "## Summary",
        "",
        "| Strategy | Top Stability | Useful Top Stability | Cases |",
        "|---|---:|---:|---:|",
    ]
    for result in strategy_results:
        lines.append(
            "| "
            f"{result.strategy} | {result.top_stability:.2f} | "
            f"{result.useful_top_stability:.2f} | {len(result.cases)} |"
        )

    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Strategy | Trace | Query | Repo | Rating | Original Top | Replay Top | Same Top | Score | Matched |",
            "|---|---|---|---|---|---|---|---|---:|---|",
        ]
    )
    if not strategy_results or not strategy_results[0].cases:
        lines.append("| - | - | - | - | - | - | - | - | 0.00 | - |")
    for result in strategy_results:
        for case in result.cases:
            matched = ", ".join(case.matched_terms) if case.matched_terms else "-"
            lines.append(
                "| "
                f"{result.strategy} | "
                f"{_md_cell(case.identifier)} | "
                f"{_md_cell(_clip(case.query, 80))} | "
                f"{_md_cell(case.repo_name or 'unknown')} | "
                f"{_md_cell(case.feedback_rating or 'unlabeled')} | "
                f"{_md_cell(case.original_top or '-')} | "
                f"{_md_cell(case.replay_top or '-')} | "
                f"{'yes' if case.same_top else 'no'} | "
                f"{case.replay_score:.2f} | "
                f"{_md_cell(matched)} |"
            )

    lines.extend(
        [
            "",
            "## Reading This Report",
            "",
            "- `top_stability` measures whether the replayed top memory matches the original trace top memory.",
            "- `useful_top_stability` applies the same check only to traces labeled `useful`.",
            "- This is a regression signal for retriever and context-packing changes; it is not a human relevance label by itself.",
            "",
        ]
    )
    return "\n".join(lines)


def render_trace_eval_report(
    *,
    workspace: Path,
    memory_home: Path,
    cases: tuple[TraceEvalCase, ...],
    useful: int,
    not_useful: int,
    neutral: int,
    unlabeled: int,
) -> str:
    labeled = useful + not_useful + neutral
    useful_rate = useful / labeled if labeled else 0.0
    lines = [
        "# MemAgent Trace Feedback Evaluation",
        "",
        "This report is generated from local recall trace metadata.",
        "It does not copy full recalled context, memory card bodies, or raw trace JSON.",
        "",
        f"- Workspace: `{workspace}`",
        f"- Memory home: `{memory_home}`",
        f"- Traces inspected: `{len(cases)}`",
        f"- Labeled: `{labeled}`",
        f"- Useful: `{useful}`",
        f"- Not useful: `{not_useful}`",
        f"- Neutral: `{neutral}`",
        f"- Unlabeled: `{unlabeled}`",
        f"- Useful rate: `{useful_rate:.2f}`",
        "",
        "## Summary",
        "",
        "| Rating | Count |",
        "|---|---:|",
        f"| useful | {useful} |",
        f"| not_useful | {not_useful} |",
        f"| neutral | {neutral} |",
        f"| unlabeled | {unlabeled} |",
        "",
        "## Cases",
        "",
        "| Trace | Query | Repo | Top Match | Matches | Rating | Note | Matched Terms |",
        "|---|---|---|---|---:|---|---|---|",
    ]
    if not cases:
        lines.append("| - | - | - | - | 0 | unlabeled | - | - |")
    for case in cases:
        rating = case.feedback_rating or "unlabeled"
        matched_terms = ", ".join(case.matched_terms) if case.matched_terms else "-"
        lines.append(
            "| "
            f"{_md_cell(case.identifier)} | "
            f"{_md_cell(_clip(case.query, 80))} | "
            f"{_md_cell(case.repo_name or 'unknown')} | "
            f"{_md_cell(case.top_match or '-')} | "
            f"{case.total_matches} | "
            f"{_md_cell(rating)} | "
            f"{_md_cell(_clip(case.feedback_note, 80) or '-')} | "
            f"{_md_cell(matched_terms)} |"
        )

    lines.extend(
        [
            "",
            "## Reading This Report",
            "",
            "- `useful_rate` is based only on labeled traces.",
            "- Unlabeled traces are the review backlog for future feedback.",
            "- This complements `recall-eval`: mock eval checks known-answer retrieval, while trace eval checks real session feedback.",
            "",
        ]
    )
    return "\n".join(lines)


def _evaluate_strategy(store: MemoryStore, context: ProjectContext, strategy: str) -> EvalStrategyResult:
    case_results = []
    for case in eval_cases():
        matches = store.recall(case.query, context=context, limit=5, strategy=strategy)
        rank = None
        for index, match in enumerate(matches, start=1):
            if match.title == case.expected_topic:
                rank = index
                break
        top = matches[0] if matches else None
        case_results.append(
            EvalCaseResult(
                query=case.query,
                expected_topic=case.expected_topic,
                top_topic=top.title if top else None,
                rank=rank,
                reciprocal_rank=0.0 if rank is None else 1.0 / rank,
                top_score=top.score if top else 0.0,
                matched_terms=top.matched_terms if top else (),
            )
        )
    return EvalStrategyResult(strategy=strategy, cases=tuple(case_results))


def _replay_strategy(
    store: MemoryStore,
    payloads: tuple[dict[str, object], ...],
    strategy: str,
) -> TraceReplayStrategyResult:
    cases = tuple(_trace_replay_case(store, payload, strategy) for payload in payloads)
    return TraceReplayStrategyResult(strategy=strategy, cases=cases)


def _trace_replay_case(store: MemoryStore, payload: dict[str, object], strategy: str) -> TraceReplayCase:
    query = str(payload.get("query") or "")
    context = _trace_project_context(payload)
    matches = store.recall(query, context=context, limit=5, strategy=strategy) if query else []
    top = matches[0] if matches else None
    original_top = _trace_original_top(payload)
    feedback = payload.get("feedback") if isinstance(payload.get("feedback"), dict) else {}
    trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
    return TraceReplayCase(
        identifier=str(trace.get("id") or ""),
        query=query,
        repo_name=context.repo_name,
        feedback_rating=str(feedback.get("rating")) if feedback.get("rating") is not None else None,
        original_top=original_top,
        strategy=strategy,
        replay_top=top.title if top else None,
        replay_score=top.score if top else 0.0,
        matched_terms=top.matched_terms if top else (),
        same_top=bool(original_top and top and original_top == top.title),
    )


def _trace_eval_case(payload: dict[str, object]) -> TraceEvalCase:
    trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    feedback = payload.get("feedback") if isinstance(payload.get("feedback"), dict) else {}
    matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
    top_match = matches[0] if matches and isinstance(matches[0], dict) else {}
    raw_matched_terms = top_match.get("matched_terms") if isinstance(top_match, dict) else []
    matched_terms = raw_matched_terms if isinstance(raw_matched_terms, list) else []
    return TraceEvalCase(
        identifier=str(trace.get("id") or ""),
        created_at=str(trace.get("created_at") or ""),
        query=str(payload.get("query") or ""),
        repo_name=str(context.get("repo_name")) if context.get("repo_name") is not None else None,
        top_match=str(top_match.get("title")) if isinstance(top_match.get("title"), str) else None,
        feedback_rating=str(feedback.get("rating")) if feedback.get("rating") is not None else None,
        feedback_note=str(feedback.get("note") or ""),
        total_matches=payload.get("total_matches") if isinstance(payload.get("total_matches"), int) else 0,
        matched_terms=tuple(str(term) for term in matched_terms if isinstance(term, str)),
    )


def _trace_original_top(payload: dict[str, object]) -> str | None:
    matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
    top_match = matches[0] if matches and isinstance(matches[0], dict) else {}
    return str(top_match.get("title")) if isinstance(top_match.get("title"), str) else None


def _trace_project_context(payload: dict[str, object]) -> ProjectContext:
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    cwd = Path(str(context.get("cwd") or ".")).expanduser().resolve()
    raw_git_root = context.get("git_root")
    git_root = Path(str(raw_git_root)).expanduser().resolve() if raw_git_root else None
    recent_files = context.get("recent_files") if isinstance(context.get("recent_files"), list) else []
    agents_files = context.get("agents_files") if isinstance(context.get("agents_files"), list) else []
    return ProjectContext(
        cwd=cwd,
        git_root=git_root,
        branch=str(context.get("branch")) if context.get("branch") is not None else None,
        repo_name=str(context.get("repo_name")) if context.get("repo_name") is not None else None,
        recent_files=tuple(str(path) for path in recent_files),
        agents_files=tuple(Path(str(path)).expanduser().resolve() for path in agents_files),
    )


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _clip(value: str, max_chars: int) -> str:
    clean = " ".join(value.split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 3].rstrip() + "..."
