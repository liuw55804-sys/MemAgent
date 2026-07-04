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


def memory_fixtures() -> tuple[MemoryFixture, ...]:
    return (
        MemoryFixture(
            topic="Attribution accuracy workflow",
            kind="workflow",
            triggers=("attribution", "accuracy", "labels"),
            text=(
                "For attribution accuracy checks, compare model labels with human-reviewed labels, "
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
            topic="RDS JSON aggregation pitfall",
            kind="pitfall",
            triggers=("RDS", "JSON", "aggregation"),
            text="RDS JSON aggregation can time out; sample first and split by primary-key ranges.",
        ),
        MemoryFixture(
            topic="Skill route for owner diagnosis",
            kind="skill_route",
            triggers=("owner", "diagnosis", "skill"),
            text="For owner diagnosis tasks, use the existing task-owner-diagnose skill before manual searching.",
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
            query="attribution accuracy label mismatch",
            expected_topic="Attribution accuracy workflow",
        ),
        EvalCase(
            query="RDS JSON aggregation timeout",
            expected_topic="RDS JSON aggregation pitfall",
        ),
        EvalCase(
            query="owner diagnosis skill route",
            expected_topic="Skill route for owner diagnosis",
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
