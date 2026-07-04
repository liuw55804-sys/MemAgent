from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from memagent.context import ProjectContext
from memagent.memory import MemoryStore


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
            self.assertIn("split by id ranges", rendered)

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


if __name__ == "__main__":
    unittest.main()
