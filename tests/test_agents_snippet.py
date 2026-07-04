from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from memagent.agents import build_agents_doctor_report, build_agents_snippet
from memagent.cli import main
from memagent.context import ProjectContext


class AgentsSnippetTest(unittest.TestCase):
    def test_build_agents_snippet(self) -> None:
        root = Path("/tmp/memagent").resolve()
        snippet = build_agents_snippet(root)
        self.assertIn("## MemAgent Natural Language Triggers", snippet)
        self.assertIn("召回一下相关记忆", snippet)
        self.assertIn("沉淀一下", snippet)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli recall", snippet)
        self.assertIn("--show-sources --show-reasons", snippet)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli remember", snippet)
        self.assertIn("Treat recalled memories as hints", snippet)
        self.assertIn("Never store tokens", snippet)

    def test_agents_snippet_cli(self) -> None:
        root = Path("/tmp/memagent").resolve()
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = main(["agents-snippet", "--memagent-root", "/tmp/memagent"])
        self.assertEqual(exit_code, 0)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli", stdout.getvalue())

    def test_agents_doctor_report_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            agents_file = project / "AGENTS.md"
            agents_file.write_text(build_agents_snippet(Path("/tmp/memagent")), encoding="utf-8")
            context = ProjectContext(
                cwd=project,
                git_root=None,
                branch=None,
                repo_name="demo",
                recent_files=(),
                agents_files=(agents_file,),
            )
            report = build_agents_doctor_report(
                context=context,
                memory_home=project / ".memagent",
                memory_count=2,
                memagent_root=Path("/tmp/memagent"),
            )
            self.assertIn("[MemAgent AGENTS.md doctor]", report)
            self.assertIn("Status: ready", report)
            self.assertIn("memory cards: 2", report)
            self.assertIn("explainable recall: yes", report)

    def test_agents_doctor_report_setup_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            agents_file = project / "AGENTS.md"
            agents_file.write_text("# Project rules\n", encoding="utf-8")
            context = ProjectContext(
                cwd=project,
                git_root=None,
                branch=None,
                repo_name="demo",
                recent_files=(),
                agents_files=(agents_file,),
            )
            report = build_agents_doctor_report(
                context=context,
                memory_home=project / ".memagent",
                memory_count=0,
                memagent_root=Path("/tmp/memagent"),
            )
            self.assertIn("Status: setup needed", report)
            self.assertIn("MemAgent section: no", report)
            self.assertIn("agents-snippet", report)

    def test_agents_doctor_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            home = project / ".memagent"
            (project / "AGENTS.md").write_text(build_agents_snippet(Path("/tmp/memagent")), encoding="utf-8")
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--home",
                        str(home),
                        "agents-doctor",
                        "--cwd",
                        str(project),
                        "--memagent-root",
                        "/tmp/memagent",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertIn("Status: ready", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
