from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from memagent.cli import main
from memagent.context import ProjectContext
from memagent.handoff import (
    HandoffStore,
    draft_handoff_from_text,
    memory_candidates_from_handoff,
    project_handoff_key,
)


def project_context(project: Path) -> ProjectContext:
    return ProjectContext(
        cwd=project,
        git_root=project,
        branch="main",
        repo_name=project.name,
        recent_files=(),
        agents_files=(),
    )


class HandoffStoreTest(unittest.TestCase):
    def test_draft_handoff_from_markdown_sections(self) -> None:
        draft = draft_handoff_from_text(
            "\n".join(
                [
                    "# Session Notes",
                    "",
                    "## Summary",
                    "Wired AGENTS.md and verified explainable recall.",
                    "",
                    "## Done",
                    "- Added handoff draft command.",
                    "- Verified tests passed.",
                    "",
                    "## Next Steps",
                    "- Add MCP draft tool.",
                    "",
                    "## Open Questions",
                    "- Should LLM extraction replace this rule parser?",
                    "",
                    "## Memory Candidates",
                    "- Handoff draft should stay reviewable before save.",
                ]
            ),
            topic=None,
        )
        self.assertEqual(draft.topic, "Wired AGENTS.md and verified explainable recall.")
        self.assertIn("Added handoff draft command.", draft.done)
        self.assertIn("Add MCP draft tool.", draft.next_steps)
        self.assertIn("Should LLM extraction replace this rule parser?", draft.open_questions)
        self.assertIn("Handoff draft should stay reviewable before save.", draft.memory_candidates)

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

            candidates = memory_candidates_from_handoff(saved.latest_path.read_text(encoding="utf-8"))
            self.assertEqual(candidates, ("Handoff should stay separate from durable memory.",))

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

    def test_handoff_cli_draft_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            project = Path(tmp) / "project"
            project.mkdir()
            source = Path(tmp) / "notes.md"
            source.write_text(
                "\n".join(
                    [
                        "## Summary",
                        "Drafted handoff from notes.",
                        "",
                        "## Done",
                        "- Added CLI draft path.",
                        "",
                        "## Next Steps",
                        "- Document the draft flow.",
                    ]
                ),
                encoding="utf-8",
            )
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--home",
                        str(home),
                        "handoff",
                        "draft",
                        "--cwd",
                        str(project),
                        "--from-file",
                        str(source),
                        "--save",
                    ]
                )
            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("[MemAgent handoff draft]", output)
            self.assertIn("Added CLI draft path.", output)
            self.assertIn("[MemAgent handoff saved]", output)
            self.assertTrue(any((home / "handoffs").glob("*/latest.md")))

    def test_handoff_cli_promote_preview_and_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            project = Path(tmp) / "project"
            project.mkdir()
            context = project_context(project)
            store = HandoffStore(home)
            store.save(
                context=context,
                summary="Ready to promote a candidate.",
                topic="Promotion handoff",
                done=[],
                next_steps=[],
                open_questions=[],
                memory_candidates=["Promote this lesson into durable memory."],
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--home",
                        str(home),
                        "handoff",
                        "promote",
                        "--cwd",
                        str(project),
                        "--index",
                        "1",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertIn("preview only", stdout.getvalue())
            self.assertEqual(list((home / "memories").glob("*.memory.yaml")), [])

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--home",
                        str(home),
                        "handoff",
                        "promote",
                        "--cwd",
                        str(project),
                        "--index",
                        "1",
                        "--write",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertIn("Status: promoted", stdout.getvalue())
            cards = list((home / "memories").glob("*.memory.yaml"))
            self.assertEqual(len(cards), 1)
            self.assertIn("Promote this lesson", cards[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
