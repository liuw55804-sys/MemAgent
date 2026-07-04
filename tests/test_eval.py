from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from memagent.cli import main
from memagent.eval import run_recall_eval, run_trace_eval
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
                    "query": "attribution accuracy",
                    "context": {"repo_name": "demo", "cwd": str(root / "project")},
                    "total_matches": 1,
                    "matches": [
                        {
                            "title": "Demo attribution memory",
                            "matched_terms": ["attribution", "accuracy"],
                        }
                    ],
                    "pack": {"emitted_matches": 1},
                    "text": "[MemAgent recalled context]\n- Memory: Demo attribution memory",
                },
                source="test",
            )
            store.label_recall_trace(saved.identifier, rating="useful", note="Matched intended memory.")

            result = run_trace_eval(store=store, workspace=root / "trace_eval", limit=10)
            self.assertTrue(result.report_path.exists())
            self.assertIn("# MemAgent Trace Feedback Evaluation", result.report)
            self.assertIn("Demo attribution memory", result.report)
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
                    "query": "owner skill",
                    "context": {"repo_name": "demo", "cwd": str(root / "project")},
                    "total_matches": 1,
                    "matches": [{"title": "Owner skill route", "matched_terms": ["owner"]}],
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


if __name__ == "__main__":
    unittest.main()
