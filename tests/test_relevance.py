from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from memagent.context import ProjectContext
from memagent.memory import MemoryMatch, MemoryStore
from memagent.relevance import select_relevant_memories


def project_context(repo_name: str = "example_service") -> ProjectContext:
    root = Path("/tmp") / repo_name
    return ProjectContext(root, root, "main", repo_name, (), ())


class RelevanceSelectionTest(unittest.TestCase):
    def test_public_precision_fixture(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "precision_recall_cases.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            context = project_context()
            for memory in fixture["memories"]:
                store.remember(
                    text=memory["text"],
                    topic=memory["topic"],
                    domain="coding",
                    kind=memory["kind"],
                    repo=context.repo_name,
                    module=None,
                    triggers=memory["triggers"],
                    exportable=True,
                )
            for case in fixture["cases"]:
                candidates = store.recall(case["query"], context=context, limit=5)
                selection = select_relevant_memories(
                    case["query"],
                    matches=candidates,
                    context=context,
                    semantic_mode="heuristic",
                )
                actual = selection.emitted[0].title if selection.emitted else None
                self.assertEqual(actual, case["expected_topic"], case["query"])

    def test_generic_only_query_abstains_before_candidate_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            store.remember(
                text="Inspect the live schema before debugging a maintainer lookup.",
                topic="Live schema entrypoint",
                domain="coding",
                kind="data_entrypoint",
                repo="example_service",
                module=None,
                triggers=["schema", "maintainer"],
                exportable=False,
            )
            context = project_context()
            candidates = store.recall("排查这个需求问题", context=context, limit=5)
            selection = select_relevant_memories(
                "排查这个需求问题",
                matches=candidates,
                context=context,
                semantic_mode="heuristic",
            )

            self.assertEqual(candidates, [])
            self.assertTrue(selection.abstained)
            self.assertEqual(selection.emitted, ())

    def test_long_business_identifier_does_not_create_relevance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            store.remember(
                text="Use a focused validation command after changing the parser.",
                topic="Parser validation",
                domain="coding",
                kind="verification",
                repo="example_service",
                module=None,
                triggers=["validation"],
                exportable=False,
            )
            context = project_context()
            candidates = store.recall("任务 123456789012345678 排查问题", context=context, limit=5)
            self.assertEqual(candidates, [])

    def test_specific_merge_memory_outranks_adjacent_project_preference(self) -> None:
        context = project_context()
        matches = [
            _match(
                "project-boundary",
                score=18.0,
                title="Keep changes inside the task-center boundary",
                kind="preference",
                terms=("task-center",),
            ),
            _match(
                "merge-checks",
                score=12.0,
                title="merge conflict verification workflow",
                kind="preference",
                terms=("merge", "conflict", "master"),
            ),
        ]
        selection = select_relevant_memories(
            "Resolve the merge conflict from master and keep the focused verification workflow.",
            matches=matches,
            context=context,
            semantic_mode="heuristic",
        )

        self.assertFalse(selection.abstained)
        self.assertEqual(len(selection.emitted), 1)
        self.assertEqual(selection.emitted[0].path.name, "merge-checks.memory.yaml")

    def test_docs_tasks_pair_selects_project_preference(self) -> None:
        context = project_context()
        match = _match(
            "repo-preference",
            score=5.0,
            title="Do not add docs or tasks unless requested",
            kind="preference",
            terms=("docs", "tasks"),
        )
        selection = select_relevant_memories(
            "Only change implementation code; do not add docs or tasks.",
            matches=[match],
            context=context,
            semantic_mode="heuristic",
        )

        self.assertEqual(selection.emitted, (match,))

    def test_specific_task_memory_outranks_single_term_online_preference(self) -> None:
        context = project_context()
        task_memory = _match(
            "strategy-panel",
            score=4.27,
            title="策略面板自动移交实现口径",
            kind="pitfall",
            terms=("策略面板",),
        )
        online_preference = _match(
            "online-urgency",
            score=4.25,
            title="长期偏好：线上排障前先询问用户是否紧急",
            kind="workflow",
            terms=("线上",),
        )

        selection = select_relevant_memories(
            "线上任务没有结束，是不是策略面板没有选择同时结束任务？",
            matches=[task_memory, online_preference],
            context=context,
            semantic_mode="heuristic",
        )

        self.assertEqual(selection.emitted, (task_memory,))
        assessments = {item.memory_id: item for item in selection.assessments}
        self.assertEqual(assessments["strategy-panel"].role, "task")
        self.assertTrue(assessments["strategy-panel"].task_specific)
        self.assertEqual(assessments["online-urgency"].role, "constraint")

    def test_single_online_term_does_not_make_constraint_high_confidence(self) -> None:
        context = project_context()
        online_preference = _match(
            "online-urgency",
            score=4.25,
            title="长期偏好：线上排障前先询问用户是否紧急",
            kind="workflow",
            terms=("线上",),
        )

        selection = select_relevant_memories(
            "线上任务为什么没有结束？",
            matches=[online_preference],
            context=context,
            semantic_mode="heuristic",
        )

        self.assertTrue(selection.abstained)

    def test_incidental_cjk_fragments_do_not_select_task_memory(self) -> None:
        match = _match(
            "sql-pitfall",
            score=4.0,
            title="编写业务 SQL 前核对项目常量和实际过滤条件",
            kind="pitfall",
            terms=("的实际", "项目"),
        )

        selection = select_relevant_memories(
            "研究另一个项目中的实际代码",
            matches=[match],
            context=project_context(),
            semantic_mode="heuristic",
        )

        self.assertTrue(selection.abstained)

    def test_hybrid_gate_can_select_one_ambiguous_candidate(self) -> None:
        context = project_context()
        match = _match(
            "git-workflow",
            score=3.5,
            title="Focused git reconciliation workflow",
            kind="preference",
            terms=("git",),
        )
        with tempfile.TemporaryDirectory() as tmp:
            config = _profile(Path(tmp))
            with mock.patch("memagent.relevance.chat_completion") as completion:
                completion.return_value = json.dumps(
                    {
                        "decisions": [
                            {"id": "git-workflow", "relevant": True, "reason": "Same reconciliation workflow."}
                        ],
                        "selected_id": "git-workflow",
                    }
                )
                selection = select_relevant_memories(
                    "git pull reports divergent branches",
                    matches=[match],
                    context=context,
                    semantic_mode="hybrid",
                    llm_profile="test",
                    llm_config_path=config,
                )

            self.assertEqual(selection.emitted, (match,))
            self.assertTrue(selection.gate.attempted)
            self.assertTrue(selection.gate.selected)
            prompt = completion.call_args.kwargs["messages"][1]["content"]
            self.assertNotIn("/tmp/example_service", prompt)
            self.assertEqual(completion.call_args.kwargs["config"].timeout_seconds, 3)

    def test_hybrid_gate_sanitizes_task_and_candidate_summary(self) -> None:
        context = project_context()
        match = MemoryMatch(
            path=Path("/tmp/memories/private.memory.yaml"),
            score=3.5,
            title="Git workflow for /private/company/repo token=secret-value",
            domain="coding",
            kind="preference",
            strategy="bm25",
            matched_terms=("git",),
            lines=("Use https://internal.example.test/path with token=secret-value",),
        )
        with tempfile.TemporaryDirectory() as tmp:
            config = _profile(Path(tmp))
            with mock.patch("memagent.relevance.chat_completion") as completion:
                completion.return_value = json.dumps(
                    {"decisions": [{"id": "private", "relevant": False, "reason": "Adjacent."}], "selected_id": None}
                )
                select_relevant_memories(
                    "git pull /private/company/repo token=secret-value",
                    matches=[match],
                    context=context,
                    semantic_mode="hybrid",
                    llm_profile="test",
                    llm_config_path=config,
                )
            prompt = completion.call_args.kwargs["messages"][1]["content"]
            self.assertNotIn("/private/company/repo", prompt)
            self.assertNotIn("secret-value", prompt)
            self.assertNotIn("internal.example.test", prompt)

    def test_hybrid_gate_failure_uses_precision_fallback(self) -> None:
        context = project_context()
        match = _match(
            "git-workflow",
            score=3.5,
            title="Focused git reconciliation workflow",
            kind="preference",
            terms=("git",),
        )
        with mock.patch("memagent.relevance.OpenAICompatibleConfig.from_default_profile", side_effect=ValueError("missing profile")):
            selection = select_relevant_memories(
                "git pull reports divergent branches",
                matches=[match],
                context=context,
                semantic_mode="hybrid",
            )

        self.assertTrue(selection.abstained)
        self.assertTrue(selection.gate.attempted)
        self.assertTrue(selection.gate.fallback)

    def test_two_timeouts_enter_cooldown_and_skip_third_gate_call(self) -> None:
        context = project_context()
        match = _match(
            "git-workflow",
            score=3.5,
            title="Focused git reconciliation workflow",
            kind="preference",
            terms=("git",),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _profile(root)
            with mock.patch(
                "memagent.relevance.chat_completion",
                side_effect=ValueError("LLM provider request failed: The read operation timed out"),
            ) as completion:
                first = select_relevant_memories(
                    "git pull reports divergent branches",
                    matches=[match],
                    context=context,
                    semantic_mode="hybrid",
                    llm_profile="test",
                    llm_config_path=config,
                    state_home=root,
                )
                second = select_relevant_memories(
                    "git pull reports divergent branches",
                    matches=[match],
                    context=context,
                    semantic_mode="hybrid",
                    llm_profile="test",
                    llm_config_path=config,
                    state_home=root,
                )
                third = select_relevant_memories(
                    "git pull reports divergent branches",
                    matches=[match],
                    context=context,
                    semantic_mode="hybrid",
                    llm_profile="test",
                    llm_config_path=config,
                    state_home=root,
                )

            self.assertEqual(completion.call_count, 2)
            self.assertEqual(first.gate.failure_kind, "timeout")
            self.assertIsNone(first.gate.cooldown_until)
            self.assertIsNotNone(second.gate.cooldown_until)
            self.assertTrue(third.gate.skipped_due_to_cooldown)
            self.assertFalse(third.gate.attempted)

    def test_rate_limit_enters_cooldown_immediately(self) -> None:
        context = project_context()
        match = _match(
            "git-workflow",
            score=3.5,
            title="Focused git reconciliation workflow",
            kind="preference",
            terms=("git",),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _profile(root)
            with mock.patch(
                "memagent.relevance.chat_completion",
                side_effect=ValueError("LLM provider request failed: HTTP 429: rate limit"),
            ):
                selection = select_relevant_memories(
                    "git pull reports divergent branches",
                    matches=[match],
                    context=context,
                    semantic_mode="hybrid",
                    llm_profile="test",
                    llm_config_path=config,
                    state_home=root,
                )

            self.assertEqual(selection.gate.failure_kind, "rate_limited")
            self.assertIsNotNone(selection.gate.cooldown_until)


def _match(
    identifier: str,
    *,
    score: float,
    title: str,
    kind: str,
    terms: tuple[str, ...],
) -> MemoryMatch:
    return MemoryMatch(
        path=Path("/tmp/memories") / f"{identifier}.memory.yaml",
        score=score,
        title=title,
        domain="coding",
        kind=kind,
        strategy="bm25",
        matched_terms=terms,
        lines=(title,),
    )


def _profile(root: Path) -> Path:
    path = root / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "profiles": {
                    "test": {
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.test/v1",
                        "api_key": "test-key",
                        "model": "test-model",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
