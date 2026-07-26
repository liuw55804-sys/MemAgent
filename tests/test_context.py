from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from memagent.context import context_payload, detect_context, matches_project_context


class ProjectContextIdentityTest(unittest.TestCase):
    def test_main_checkout_and_worktree_share_canonical_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "service"
            worktree = root / "worktree"
            _init_repo(main)
            _git(main, "worktree", "add", "--detach", str(worktree))

            main_context = detect_context(main)
            worktree_context = detect_context(worktree)

            self.assertIsNotNone(main_context.canonical_repo_id)
            self.assertEqual(main_context.canonical_repo_id, worktree_context.canonical_repo_id)
            self.assertFalse(main_context.is_worktree)
            self.assertTrue(worktree_context.is_worktree)
            self.assertTrue(
                matches_project_context(
                    context_payload(worktree_context),
                    main_context,
                )
            )

    def test_same_named_independent_repositories_do_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as left_tmp, tempfile.TemporaryDirectory() as right_tmp:
            left = Path(left_tmp) / "service"
            right = Path(right_tmp) / "service"
            _init_repo(left)
            _init_repo(right)
            left_context = detect_context(left)
            right_context = detect_context(right)

            self.assertEqual(left_context.repo_name, right_context.repo_name)
            self.assertNotEqual(left_context.canonical_repo_id, right_context.canonical_repo_id)
            self.assertFalse(
                matches_project_context(
                    context_payload(left_context),
                    right_context,
                )
            )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init")
    _git(path, "config", "user.email", "memagent@example.test")
    _git(path, "config", "user.name", "MemAgent Test")
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial")


def _git(path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    unittest.main()
