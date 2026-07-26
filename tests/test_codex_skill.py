from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from memagent.cli import main
from memagent.codex_skill import (
    MANAGED_MARKER,
    build_user_codex_skill_plan,
    uninstall_user_codex_skill,
    write_user_codex_skill_plan,
    write_user_codex_skill_uninstall,
)


class UserCodexSkillTest(unittest.TestCase):
    def test_install_plan_writes_only_user_skill_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "codex" / "skills" / "memagent" / "SKILL.md"
            plan = build_user_codex_skill_plan(target=target)

            self.assertEqual(plan.action, "create")
            self.assertFalse(target.exists())
            write_user_codex_skill_plan(plan)

            content = target.read_text(encoding="utf-8")
            self.assertIn(MANAGED_MARKER, content)
            self.assertIn("memagent process", content)
            self.assertIn("memagent suggest", content)
            self.assertIn("memagent trace adopt", content)
            self.assertIn("at most one memory", content)
            self.assertNotIn("PYTHON" + "PATH=", content)
            self.assertNotIn("AGENTS.md", str(target.parent))

    def test_install_blocks_unmanaged_existing_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "SKILL.md"
            target.write_text("---\nname: memagent\n---\ncustom\n", encoding="utf-8")

            plan = build_user_codex_skill_plan(target=target)

            self.assertTrue(plan.blocked)
            self.assertEqual(plan.action, "blocked")

    def test_uninstall_removes_only_managed_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "SKILL.md"
            install = build_user_codex_skill_plan(target=target)
            write_user_codex_skill_plan(install)

            plan = uninstall_user_codex_skill(target=target)
            write_user_codex_skill_uninstall(plan)

            self.assertEqual(plan.action, "remove")
            self.assertFalse(target.exists())

    def test_install_user_codex_cli_dry_run_and_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "skills" / "memagent" / "SKILL.md"
            dry_run = StringIO()
            with redirect_stdout(dry_run):
                dry_code = main(["install-user-codex", "--target", str(target)])
            self.assertEqual(dry_code, 0)
            self.assertIn("business repo changes: none", dry_run.getvalue())
            self.assertFalse(target.exists())

            write_run = StringIO()
            with redirect_stdout(write_run):
                write_code = main(["install-user-codex", "--target", str(target), "--write"])
            self.assertEqual(write_code, 0)
            self.assertTrue(target.exists())
            self.assertIn("status: written", write_run.getvalue())


if __name__ == "__main__":
    unittest.main()
