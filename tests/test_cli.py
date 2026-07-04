from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import os
import tempfile
import unittest

from memagent.cli import main


class CliTest(unittest.TestCase):
    def test_draft_memory_json_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "draft",
                        "memory",
                        "这个 bytedcli 查 live schema 的入口下次别忘了：bytedcli rds db table schema demo_db demo_table --region cn。",
                        "--cwd",
                        str(project),
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["schema_version"], "memagent.memory_draft.v1")
            self.assertEqual(payload["kind"], "data_entrypoint")
            self.assertEqual(payload["quality_label"], "keep")
            self.assertTrue(payload["requires_confirmation"])
            self.assertEqual(payload["context"]["repo_name"], "project")

    def test_route_json_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "route",
                        "帮我排查 audit_rule_lib 的 owner 问题，先按你觉得最省时间的方式来。",
                        "--cwd",
                        str(project),
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["schema_version"], "memagent.route.v1")
            self.assertEqual(payload["action"], "recall")
            self.assertEqual(payload["context"]["repo_name"], "project")

    def test_recall_json_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            project = root / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(project)
                remember_stdout = StringIO()
                with redirect_stdout(remember_stdout):
                    remember_code = main(
                        [
                            "--home",
                            str(home),
                            "remember",
                            "--topic",
                            "RDS timeout pitfall",
                            "--kind",
                            "pitfall",
                            "--trigger",
                            "RDS",
                            "Use id ranges before RDS JSON grouping.",
                        ]
                    )
                self.assertEqual(remember_code, 0)

                recall_stdout = StringIO()
                with redirect_stdout(recall_stdout):
                    recall_code = main(
                        [
                            "--home",
                            str(home),
                            "recall",
                            "RDS JSON timeout",
                            "--show-sources",
                            "--show-reasons",
                            "--json",
                        ]
                    )
                self.assertEqual(recall_code, 0)
            finally:
                os.chdir(previous_cwd)

            payload = json.loads(recall_stdout.getvalue())
            self.assertEqual(payload["schema_version"], "memagent.recall.v1")
            self.assertEqual(payload["query"], "RDS JSON timeout")
            self.assertEqual(payload["context"]["repo_name"], "project")
            self.assertEqual(payload["matches"][0]["title"], "RDS timeout pitfall")
            self.assertEqual(payload["matches"][0]["kind"], "pitfall")
            self.assertIn("Pack:", payload["text"])
            self.assertFalse(payload["pack"]["truncated"])

    def test_recall_trace_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            project = root / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(project)
                with redirect_stdout(StringIO()):
                    self.assertEqual(
                        main(
                            [
                                "--home",
                                str(home),
                                "remember",
                                "--topic",
                                "Owner skill route",
                                "--kind",
                                "skill_route",
                                "Use task-owner-diagnose before manual owner tracing.",
                            ]
                        ),
                        0,
                    )

                recall_stdout = StringIO()
                with redirect_stdout(recall_stdout):
                    recall_code = main(
                        [
                            "--home",
                            str(home),
                            "recall",
                            "owner tracing",
                            "--trace",
                        ]
                    )
                self.assertEqual(recall_code, 0)
                self.assertIn("[MemAgent recall trace saved]", recall_stdout.getvalue())

                list_stdout = StringIO()
                with redirect_stdout(list_stdout):
                    list_code = main(["--home", str(home), "trace", "list"])
                self.assertEqual(list_code, 0)
                self.assertIn("Owner skill route", list_stdout.getvalue())

                show_stdout = StringIO()
                with redirect_stdout(show_stdout):
                    show_code = main(["--home", str(home), "trace", "show", "--json"])
                self.assertEqual(show_code, 0)

                label_stdout = StringIO()
                with redirect_stdout(label_stdout):
                    label_code = main(
                        [
                            "--home",
                            str(home),
                            "trace",
                            "label",
                            "--rating",
                            "useful",
                            "--note",
                            "Correct route.",
                        ]
                    )
                self.assertEqual(label_code, 0)
                self.assertIn("[MemAgent recall trace labeled]", label_stdout.getvalue())

                report_stdout = StringIO()
                with redirect_stdout(report_stdout):
                    report_code = main(["--home", str(home), "trace", "report"])
                self.assertEqual(report_code, 0)
                self.assertIn("- useful_rate: 1.00", report_stdout.getvalue())

                trace_eval_workspace = root / "trace_eval"
                trace_eval_stdout = StringIO()
                with redirect_stdout(trace_eval_stdout):
                    trace_eval_code = main(
                        [
                            "--home",
                            str(home),
                            "trace",
                            "eval",
                            "--workspace",
                            str(trace_eval_workspace),
                        ]
                    )
                self.assertEqual(trace_eval_code, 0)
                self.assertIn("[MemAgent trace-eval]", trace_eval_stdout.getvalue())
                self.assertTrue((trace_eval_workspace / "report.md").exists())

                trace_replay_workspace = root / "trace_replay"
                trace_replay_stdout = StringIO()
                with redirect_stdout(trace_replay_stdout):
                    trace_replay_code = main(
                        [
                            "--home",
                            str(home),
                            "trace",
                            "replay",
                            "--workspace",
                            str(trace_replay_workspace),
                        ]
                    )
                self.assertEqual(trace_replay_code, 0)
                self.assertIn("[MemAgent trace-replay]", trace_replay_stdout.getvalue())
                self.assertTrue((trace_replay_workspace / "report.md").exists())
            finally:
                os.chdir(previous_cwd)

            payload = json.loads(show_stdout.getvalue())
            self.assertEqual(payload["schema_version"], "memagent.recall.v1")
            self.assertEqual(payload["trace"]["source"], "cli")
            self.assertEqual(payload["matches"][0]["title"], "Owner skill route")


if __name__ == "__main__":
    unittest.main()
