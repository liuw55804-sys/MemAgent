from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from memagent.context import ProjectContext
from memagent.memory import MemoryMatch, MemoryStore


def project_context(repo_name: str = "walle") -> ProjectContext:
    return ProjectContext(
        cwd=Path(f"/tmp/{repo_name}"),
        git_root=Path(f"/tmp/{repo_name}"),
        branch="main",
        repo_name=repo_name,
        recent_files=(),
        agents_files=(),
    )


class MemoryStoreTest(unittest.TestCase):
    def test_remember_and_recall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            saved = store.remember(
                text="RDS JSON aggregation timed out; split by id ranges before grouping.",
                topic="RDS query pitfall",
                domain=None,
                kind=None,
                repo="walle",
                module="machine_attribution",
                triggers=["RDS", "JSON", "accuracy"],
                exportable=False,
            )
            self.assertTrue(saved.path.exists())
            raw = saved.path.read_text(encoding="utf-8")
            self.assertIn('domain: "coding"', raw)
            self.assertIn('kind: "note"', raw)

            context = project_context()
            matches = store.recall("how to avoid RDS JSON timeout", context=context, limit=3)
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].domain, "coding")
            self.assertEqual(matches[0].kind, "note")
            self.assertIn("rds", matches[0].matched_terms)
            self.assertIn("json", matches[0].matched_terms)
            rendered = store.compose_context(
                query="how to avoid RDS JSON timeout",
                context=context,
                matches=matches,
                max_lines=8,
                show_sources=True,
                show_reasons=True,
            )
            self.assertIn("RDS query pitfall [coding/note]", rendered)
            self.assertIn("score=", rendered)
            self.assertIn("matched=", rendered)
            self.assertIn("- Pack:", rendered)
            self.assertIn("split by id ranges", rendered)
            payload = store.build_recall_payload(
                query="how to avoid RDS JSON timeout",
                context=context,
                matches=matches,
                max_lines=8,
                show_sources=True,
                show_reasons=True,
            )
            self.assertEqual(payload["schema_version"], "memagent.recall.v1")
            self.assertEqual(payload["total_matches"], 1)
            self.assertIn("text", payload)
            self.assertEqual(payload["context"]["repo_name"], "walle")
            self.assertEqual(payload["matches"][0]["title"], "RDS query pitfall")
            self.assertEqual(payload["pack"]["emitted_matches"], 1)
            self.assertFalse(payload["pack"]["truncated"])

    def test_remember_with_explicit_domain_and_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            saved = store.remember(
                text="When choosing apartments, commute and sound insulation outrank size.",
                topic="Apartment preference",
                domain="life",
                kind="preference",
                repo="personal",
                module=None,
                triggers=["apartment", "rent"],
                exportable=False,
            )
            raw = saved.path.read_text(encoding="utf-8")
            self.assertIn('domain: "life"', raw)
            self.assertIn('kind: "preference"', raw)

            matches = store.recall("rent apartment preference", context=project_context("personal"), limit=3)
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].domain, "life")
            self.assertEqual(matches[0].kind, "preference")

    def test_domain_and_kind_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            saved = store.remember(
                text="Use the existing skill before searching manually.",
                topic="Skill route",
                domain=" Coding ",
                kind="Skill-Route",
                repo="walle",
                module=None,
                triggers=["skill"],
                exportable=False,
            )
            raw = saved.path.read_text(encoding="utf-8")
            self.assertIn('domain: "coding"', raw)
            self.assertIn('kind: "skill_route"', raw)

    def test_invalid_domain_and_kind_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            with self.assertRaisesRegex(ValueError, "invalid domain"):
                store.remember(
                    text="bad domain",
                    topic=None,
                    domain="unknown-domain",
                    kind=None,
                    repo="walle",
                    module=None,
                    triggers=[],
                    exportable=False,
                )
            with self.assertRaisesRegex(ValueError, "invalid kind"):
                store.remember(
                    text="bad kind",
                    topic=None,
                    domain=None,
                    kind="unknown-kind",
                    repo="walle",
                    module=None,
                    triggers=[],
                    exportable=False,
                )

    def test_recall_older_card_without_domain_and_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            old_card = store.memories_dir / "old.memory.yaml"
            old_card.write_text(
                "\n".join(
                    [
                        'id: "old"',
                        'topic: "Legacy RDS note"',
                        "scope:",
                        '  repo: "walle"',
                        "triggers:",
                        '  - "RDS"',
                        "pitfalls:",
                        '  - "Legacy cards should still recall."',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            matches = store.recall("RDS legacy", context=project_context(), limit=3)
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].domain, "coding")
            self.assertEqual(matches[0].kind, "note")

    def test_recall_chinese_phrase_with_partial_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            store.remember(
                text="租房决策里通勤和隔音优先级高于面积。",
                topic="租房偏好",
                domain="life",
                kind="preference",
                repo="personal",
                module=None,
                triggers=["租房"],
                exportable=False,
            )
            matches = store.recall("帮我判断租房偏好", context=project_context("personal"), limit=3)
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].title, "租房偏好")
            self.assertEqual(matches[0].domain, "life")
            self.assertEqual(matches[0].kind, "preference")

    def test_bm25_prefers_multi_term_match_over_repeated_single_term(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            store.remember(
                text="accuracy " * 30,
                topic="Repeated accuracy note",
                domain="coding",
                kind="note",
                repo="demo",
                module=None,
                triggers=["accuracy"],
                exportable=False,
            )
            store.remember(
                text="For attribution accuracy checks, compare model labels with reviewed labels.",
                topic="Attribution accuracy workflow",
                domain="coding",
                kind="workflow",
                repo="demo",
                module=None,
                triggers=["attribution", "accuracy"],
                exportable=False,
            )
            matches = store.recall("attribution accuracy", context=project_context("demo"), limit=2, strategy="bm25")
            self.assertGreaterEqual(len(matches), 2)
            self.assertEqual(matches[0].title, "Attribution accuracy workflow")
            self.assertEqual(matches[0].strategy, "bm25")

    def test_invalid_recall_strategy_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            with self.assertRaisesRegex(ValueError, "invalid recall strategy"):
                store.recall("anything", context=project_context("demo"), limit=1, strategy="vector")

    def test_compose_context_dedupes_repeated_memory_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            matches = [
                MemoryMatch(
                    path=Path(tmp) / "one.memory.yaml",
                    score=3.0,
                    title="First route",
                    domain="coding",
                    kind="tool_recipe",
                    strategy="bm25",
                    matched_terms=("rds",),
                    lines=("Use id ranges before grouping.", "Check owner config first."),
                ),
                MemoryMatch(
                    path=Path(tmp) / "two.memory.yaml",
                    score=2.0,
                    title="Second route",
                    domain="coding",
                    kind="pitfall",
                    strategy="bm25",
                    matched_terms=("rds",),
                    lines=("Use id ranges before grouping.", "Avoid full-table aggregation."),
                ),
            ]
            rendered = store.compose_context(
                query="RDS owner query",
                context=project_context(),
                matches=matches,
                max_lines=10,
                show_sources=False,
                show_reasons=False,
            )
            self.assertEqual(rendered.count("Use id ranges before grouping."), 1)
            self.assertIn("deduped=1", rendered)
            self.assertIn("truncated=no", rendered)

    def test_compose_context_marks_budget_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            matches = [
                MemoryMatch(
                    path=Path(tmp) / f"{index}.memory.yaml",
                    score=float(10 - index),
                    title=f"Memory {index}",
                    domain="coding",
                    kind="workflow",
                    strategy="bm25",
                    matched_terms=("demo",),
                    lines=(f"Important step {index}", f"Validation step {index}"),
                )
                for index in range(5)
            ]
            rendered = store.compose_context(
                query="demo workflow",
                context=project_context("demo"),
                matches=matches,
                max_lines=6,
                show_sources=True,
                show_reasons=True,
            )
            self.assertLessEqual(len(rendered.splitlines()), 6)
            self.assertIn("truncated=yes", rendered)
            self.assertIn("budget=2 memory lines", rendered)


if __name__ == "__main__":
    unittest.main()
