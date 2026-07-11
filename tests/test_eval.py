from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from memagent.cli import main
from memagent.eval import run_recall_eval, run_trace_eval, run_trace_replay
from memagent.memory import MemoryStore


class RecallEvalTest(unittest.TestCase):
    def test_run_recall_eval_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_recall_eval(workspace=Path(tmp) / "eval")
            self.assertTrue(result.report_path.exists())
            self.assertIn("# MemAgent Recall Evaluation", result.report)
            self.assertIn("| Strategy | Hit@1 | MRR |", result.report)
            self.assertIn("Attribution accuracy workflow", result.report)
            by_strategy = {item.strategy: item for item in result.strategy_results}
            self.assertIn("bm25", by_strategy)
            self.assertIn("keyword", by_strategy)
            self.assertGreaterEqual(by_strategy["bm25"].hit_at_1, by_strategy["keyword"].hit_at_1)
            self.assertGreaterEqual(by_strategy["bm25"].mrr, by_strategy["keyword"].mrr)

    def test_recall_eval_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "eval"
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["recall-eval", "--workspace", str(workspace)])
            self.assertEqual(exit_code, 0)
            self.assertTrue((workspace / "report.md").exists())
            self.assertIn("[MemAgent recall-eval]", stdout.getvalue())
            self.assertIn("bm25: hit@1=", stdout.getvalue())

    def test_run_trace_eval_writes_report_from_labeled_traces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            saved = store.save_recall_trace(
                {
                    "schema_version": "memagent.recall.v1",
                    "query": "validation accuracy",
                    "context": {"repo_name": "demo", "cwd": str(root / "project")},
                    "total_matches": 1,
                    "matches": [
                        {
                            "title": "Demo validation memory",
                            "matched_terms": ["validation", "accuracy"],
                        }
                    ],
                    "pack": {"emitted_matches": 1},
                    "text": "[MemAgent recalled context]\n- Memory: Demo validation memory",
                },
                source="test",
            )
            store.label_recall_trace(saved.identifier, rating="useful", note="Matched intended memory.")

            result = run_trace_eval(store=store, workspace=root / "trace_eval", limit=10)
            self.assertTrue(result.report_path.exists())
            self.assertIn("# MemAgent Trace Feedback Evaluation", result.report)
            self.assertIn("Demo validation memory", result.report)
            self.assertIn("| useful | 1 |", result.report)
            self.assertEqual(result.labeled, 1)
            self.assertEqual(result.useful_rate, 1.0)

    def test_trace_eval_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            store = MemoryStore(home)
            saved = store.save_recall_trace(
                {
                    "schema_version": "memagent.recall.v1",
                    "query": "maintainer skill",
                    "context": {"repo_name": "demo", "cwd": str(root / "project")},
                    "total_matches": 1,
                    "matches": [{"title": "Owner skill route", "matched_terms": ["maintainer"]}],
                    "pack": {"emitted_matches": 1},
                    "text": "[MemAgent recalled context]\n- Memory: Owner skill route",
                },
                source="test",
            )
            store.label_recall_trace(saved.identifier, rating="useful", note="Correct route.")
            workspace = root / "trace_eval"

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--home",
                        str(home),
                        "trace",
                        "eval",
                        "--workspace",
                        str(workspace),
                        "--limit",
                        "5",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertTrue((workspace / "report.md").exists())
            self.assertIn("[MemAgent trace-eval]", stdout.getvalue())
            self.assertIn("useful_rate: 1.00", stdout.getvalue())

    def test_run_trace_replay_writes_strategy_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root / "home")
            store.remember(
                text="Use the maintainer diagnosis skill before manual maintainer tracing.",
                topic="Owner skill route",
                domain="coding",
                kind="skill_route",
                repo="demo",
                module=None,
                triggers=["maintainer", "skill"],
                exportable=True,
            )
            context = {"repo_name": "demo", "cwd": str(root / "project")}
            saved = store.save_recall_trace(
                {
                    "schema_version": "memagent.recall.v1",
                    "query": "maintainer skill",
                    "context": context,
                    "total_matches": 1,
                    "matches": [{"title": "Owner skill route", "matched_terms": ["maintainer", "skill"]}],
                    "pack": {"emitted_matches": 1},
                    "text": "[MemAgent recalled context]\n- Memory: Owner skill route",
                },
                source="test",
            )
            store.label_recall_trace(saved.identifier, rating="useful", note="Correct route.")

            result = run_trace_replay(store=store, workspace=root / "trace_replay", limit=5)
            self.assertTrue(result.report_path.exists())
            self.assertIn("# MemAgent Trace Replay Evaluation", result.report)
            self.assertIn("Owner skill route", result.report)
            self.assertIn("| bm25 |", result.report)
            by_strategy = {item.strategy: item for item in result.strategy_results}
            self.assertEqual(by_strategy["bm25"].top_stability, 1.0)
            self.assertEqual(by_strategy["bm25"].useful_top_stability, 1.0)

    def test_trace_replay_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            store = MemoryStore(home)
            store.remember(
                text="Use id ranges before database JSON grouping.",
                topic="database timeout pitfall",
                domain="coding",
                kind="pitfall",
                repo="demo",
                module=None,
                triggers=["database", "JSON"],
                exportable=True,
            )
            saved = store.save_recall_trace(
                {
                    "schema_version": "memagent.recall.v1",
                    "query": "database JSON timeout",
                    "context": {"repo_name": "demo", "cwd": str(root / "project")},
                    "total_matches": 1,
                    "matches": [{"title": "database timeout pitfall", "matched_terms": ["database", "json"]}],
                    "pack": {"emitted_matches": 1},
                    "text": "[MemAgent recalled context]\n- Memory: database timeout pitfall",
                },
                source="test",
            )
            store.label_recall_trace(saved.identifier, rating="useful", note="Correct route.")
            workspace = root / "trace_replay"

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--home",
                        str(home),
                        "trace",
                        "replay",
                        "--workspace",
                        str(workspace),
                        "--limit",
                        "5",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertTrue((workspace / "report.md").exists())
            self.assertIn("[MemAgent trace-replay]", stdout.getvalue())
            self.assertIn("top_stability=1.00", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
