from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from memagent.cli import main
from memagent.eval import run_recall_eval


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


if __name__ == "__main__":
    unittest.main()
