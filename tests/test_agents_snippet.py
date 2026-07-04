from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from memagent.agents import (
    MEMAGENT_BLOCK_END,
    MEMAGENT_BLOCK_START,
    build_agents_doctor_report,
    build_agents_install_plan,
    build_agents_snippet,
    write_agents_install_plan,
)
from memagent.cli import main
from memagent.context import ProjectContext


class AgentsSnippetTest(unittest.TestCase):
    def test_build_agents_snippet(self) -> None:
        root = Path("/tmp/memagent").resolve()
        snippet = build_agents_snippet(root)
        self.assertIn("## MemAgent Natural Language Signals", snippet)
        self.assertIn("not a", snippet)
        self.assertIn("hard trigger-word list", snippet)
        self.assertIn(MEMAGENT_BLOCK_START, snippet)
        self.assertIn(MEMAGENT_BLOCK_END, snippet)
        self.assertIn("The user does not need to", snippet)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli process", snippet)
        self.assertIn("LLM Provider Readiness", snippet)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli llm doctor", snippet)
        self.assertIn("--profile", snippet)
        self.assertIn("--check-live", snippet)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli route", snippet)
        self.assertIn("Task-Start Memory Check", snippet)
        self.assertIn("继续排查 audit_rule_lib", snippet)
        self.assertIn("先按你觉得最省时间的方式来", snippet)
        self.assertIn("沉淀一下", snippet)
        self.assertIn("这个入口下次别忘了", snippet)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli draft memory", snippet)
        self.assertIn("Ask the user to confirm before saving", snippet)
        self.assertIn("上次做到哪", snippet)
        self.assertIn("交接一下", snippet)
        self.assertIn("换个会话继续", snippet)
        self.assertIn("handoff draft", snippet)
        self.assertIn("ingest codex", snippet)
        self.assertIn("memory candidates", snippet)
        self.assertIn("promote handoff candidate", snippet)
        self.assertIn("Feedback From Ordinary Language", snippet)
        self.assertIn("这个有用", snippet)
        self.assertIn("Do not ask the user to say the word \"trace\"", snippet)
        self.assertIn("trace label", snippet)
        self.assertIn("trace report", snippet)
        self.assertIn("trace eval", snippet)
        self.assertIn("trace replay", snippet)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli recall", snippet)
        self.assertIn("--trace", snippet)
        self.assertIn("--show-sources --show-reasons", snippet)
        self.assertIn("--strategy bm25", snippet)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli remember", snippet)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli handoff", snippet)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli ingest", snippet)
        self.assertIn(f"PYTHONPATH={root / 'src'} python -m memagent.cli trace", snippet)
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
            self.assertIn("继续排查 audit_rule_lib", report)
            self.assertIn("explainable recall: yes", report)
            self.assertIn("BM25 strategy: yes", report)
            self.assertIn("handoff command: yes", report)
            self.assertIn("trace command: yes", report)

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
            self.assertIn("handoff command: no", report)
            self.assertIn("trace command: no", report)
            self.assertIn("BM25 strategy: no", report)
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

    def test_agents_install_plan_create(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            context = ProjectContext(
                cwd=project,
                git_root=None,
                branch=None,
                repo_name="demo",
                recent_files=(),
                agents_files=(),
            )
            plan = build_agents_install_plan(
                context=context,
                target=None,
                memagent_root=Path("/tmp/memagent"),
            )
            self.assertEqual(plan.action, "create")
            self.assertTrue(plan.changed)
            self.assertFalse(plan.blocked)
            self.assertEqual(plan.target, (project / "AGENTS.md").resolve())
            self.assertIn(MEMAGENT_BLOCK_START, plan.next_content)

    def test_agents_install_plan_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            target = project / "AGENTS.md"
            target.write_text("# Project rules\n", encoding="utf-8")
            context = ProjectContext(
                cwd=project,
                git_root=None,
                branch=None,
                repo_name="demo",
                recent_files=(),
                agents_files=(target,),
            )
            plan = build_agents_install_plan(
                context=context,
                target=target,
                memagent_root=Path("/tmp/memagent"),
            )
            self.assertEqual(plan.action, "append")
            self.assertIn("# Project rules", plan.next_content)
            self.assertIn(MEMAGENT_BLOCK_START, plan.next_content)

    def test_agents_install_plan_replace_marked_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            target = project / "AGENTS.md"
            target.write_text(
                "\n".join(
                    [
                        "# Project rules",
                        MEMAGENT_BLOCK_START,
                        "old content",
                        MEMAGENT_BLOCK_END,
                        "## Other rules",
                    ]
                ),
                encoding="utf-8",
            )
            context = ProjectContext(
                cwd=project,
                git_root=None,
                branch=None,
                repo_name="demo",
                recent_files=(),
                agents_files=(target,),
            )
            plan = build_agents_install_plan(
                context=context,
                target=target,
                memagent_root=Path("/tmp/memagent"),
            )
            self.assertEqual(plan.action, "replace-marked")
            self.assertNotIn("old content", plan.next_content)
            self.assertIn("## Other rules", plan.next_content)

    def test_agents_install_plan_blocks_unmarked_existing_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            target = project / "AGENTS.md"
            target.write_text("## MemAgent Natural Language Signals\nold content\n", encoding="utf-8")
            context = ProjectContext(
                cwd=project,
                git_root=None,
                branch=None,
                repo_name="demo",
                recent_files=(),
                agents_files=(target,),
            )
            plan = build_agents_install_plan(
                context=context,
                target=target,
                memagent_root=Path("/tmp/memagent"),
            )
            self.assertEqual(plan.action, "blocked")
            self.assertTrue(plan.blocked)

    def test_agents_install_write_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "agents-install",
                        "--cwd",
                        str(project),
                        "--memagent-root",
                        "/tmp/memagent",
                        "--write",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertIn("Status: written", stdout.getvalue())
            self.assertIn(MEMAGENT_BLOCK_START, (project / "AGENTS.md").read_text(encoding="utf-8"))

    def test_write_agents_install_plan_skips_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            target = project / "AGENTS.md"
            target.write_text("## MemAgent Natural Language Signals\nold content\n", encoding="utf-8")
            context = ProjectContext(
                cwd=project,
                git_root=None,
                branch=None,
                repo_name="demo",
                recent_files=(),
                agents_files=(target,),
            )
            plan = build_agents_install_plan(
                context=context,
                target=target,
                memagent_root=Path("/tmp/memagent"),
            )
            write_agents_install_plan(plan)
            self.assertEqual(target.read_text(encoding="utf-8"), "## MemAgent Natural Language Signals\nold content\n")

    def test_agents_install_plan_recognizes_legacy_trigger_heading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            target = project / "AGENTS.md"
            target.write_text("## MemAgent Natural Language Triggers\nold content\n", encoding="utf-8")
            context = ProjectContext(
                cwd=project,
                git_root=None,
                branch=None,
                repo_name="demo",
                recent_files=(),
                agents_files=(target,),
            )
            plan = build_agents_install_plan(
                context=context,
                target=target,
                memagent_root=Path("/tmp/memagent"),
            )
            self.assertEqual(plan.action, "blocked")
            self.assertTrue(plan.blocked)


if __name__ == "__main__":
    unittest.main()
