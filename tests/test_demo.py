from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from memagent.agents import MEMAGENT_BLOCK_START
from memagent.cli import main
from memagent.demo import run_demo


class DemoRunTest(unittest.TestCase):
    def test_run_demo_writes_transcript_and_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "demo"
            result = run_demo(
                workspace=workspace,
                memagent_root=Path("/tmp/memagent"),
                reset=False,
            )
            self.assertTrue(result.transcript_path.exists())
            self.assertTrue((result.project_dir / "AGENTS.md").exists())
            self.assertIn(MEMAGENT_BLOCK_START, (result.project_dir / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertEqual(len(list((result.memory_home / "memories").glob("*.memory.yaml"))), 2)
            self.assertIn("Status: ready", result.transcript)
            self.assertIn("Demo attribution accuracy entrypoint", result.transcript)
            self.assertIn("Demo continuation handoff", result.transcript)
            self.assertIn("Promote handoff memory candidate", result.transcript)
            self.assertTrue((result.memory_home / "handoffs").exists())
            self.assertIn("[User task]", result.transcript)

    def test_demo_run_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "demo"
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "demo-run",
                        "--workspace",
                        str(workspace),
                        "--memagent-root",
                        "/tmp/memagent",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertIn("[MemAgent demo-run]", stdout.getvalue())
            self.assertTrue((workspace / "transcript.md").exists())


if __name__ == "__main__":
    unittest.main()
