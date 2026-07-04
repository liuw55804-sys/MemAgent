from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from memagent.cli import main
from memagent.context import ProjectContext
from memagent.handoff import HandoffStore, project_handoff_key


def project_context(project: Path) -> ProjectContext:
    return ProjectContext(
        cwd=project,
        git_root=project,
        branch="main",
        repo_name="demo",
        recent_files=(),
        agents_files=(),
    )


class HandoffStoreTest(unittest.TestCase):
    def test_save_and_show_latest_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            project = Path(tmp) / "project"
            project.mkdir()
            context = project_context(project)
            store = HandoffStore(home)
            saved = store.save(
                context=context,
                summary="Installed AGENTS.md integration and verified recall.",
                topic="Demo handoff",
                done=["Ran agents-doctor."],
                next_steps=["Add MCP handoff tools."],
                open_questions=["Should hooks generate handoffs?"],
                memory_candidates=["Handoff should stay separate from durable memory."],
            )
            self.assertTrue(saved.latest_path.exists())
            self.assertTrue(saved.history_path.exists())
            self.assertEqual(saved.project_key, project_handoff_key(context))

            rendered = store.compose_latest(context=context, max_lines=40)
            self.assertIn("[MemAgent handoff]", rendered)
            self.assertIn("Demo handoff", rendered)
            self.assertIn("Installed AGENTS.md integration", rendered)
            self.assertIn("Add MCP handoff tools", rendered)

    def test_show_without_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            rendered = HandoffStore(Path(tmp) / "home").compose_latest(context=project_context(project))
            self.assertIn("No handoff found", rendered)

    def test_handoff_cli_save_and_show(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            project = Path(tmp) / "project"
            project.mkdir()
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--home",
                        str(home),
                        "handoff",
                        "save",
                        "--cwd",
                        str(project),
                        "--topic",
                        "CLI handoff",
                        "--done",
                        "Added tests.",
                        "--next-step",
                        "Run full validation.",
                        "CLI summary for next session.",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertIn("[MemAgent handoff saved]", stdout.getvalue())

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--home",
                        str(home),
                        "handoff",
                        "show",
                        "--cwd",
                        str(project),
                        "--max-lines",
                        "20",
                    ]
                )
            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("CLI handoff", output)
            self.assertIn("Run full validation", output)


if __name__ == "__main__":
    unittest.main()
