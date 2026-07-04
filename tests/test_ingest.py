from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import tempfile
import unittest

from memagent.cli import main
from memagent.context import detect_context
from memagent.ingest import run_codex_ingest


class CodexIngestTest(unittest.TestCase):
    def test_run_codex_ingest_writes_candidate_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            sessions = root / "sessions" / "2026" / "07" / "04"
            workspace = root / "ingest"
            project.mkdir()
            sessions.mkdir(parents=True)
            (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            _write_mock_codex_session(sessions / "rollout-demo.jsonl", project)

            result = run_codex_ingest(
                sessions_root=root / "sessions",
                workspace=workspace,
                context=detect_context(project),
                limit=5,
                max_candidates=5,
                project_only=True,
            )

            self.assertEqual(result.sessions_scanned, 1)
            self.assertGreaterEqual(result.records_scanned, 4)
            self.assertGreaterEqual(len(result.candidates), 3)
            self.assertTrue(result.report_path.exists())
            self.assertTrue((result.candidates_dir / "candidate_001.md").exists())
            report = result.report_path.read_text(encoding="utf-8")
            self.assertIn("# MemAgent Codex Transcript Ingest", report)
            self.assertIn("review-only", report)
            joined = "\n".join(candidate.memory for candidate in result.candidates)
            self.assertIn("bytedcli", joined)
            self.assertIn("trace replay", joined)
            self.assertIn("<redacted>", joined)

    def test_codex_ingest_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            sessions = root / "sessions"
            workspace = root / "workspace"
            project.mkdir()
            (sessions / "2026").mkdir(parents=True)
            (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            _write_mock_codex_session(sessions / "2026" / "rollout-demo.jsonl", project)

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "ingest",
                        "codex",
                        "--sessions-root",
                        str(sessions),
                        "--workspace",
                        str(workspace),
                        "--cwd",
                        str(project),
                        "--project-only",
                        "--max-candidates",
                        "4",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("[MemAgent codex ingest]", stdout.getvalue())
            self.assertIn("mode: review-only", stdout.getvalue())
            self.assertTrue((workspace / "report.md").exists())
            self.assertTrue((workspace / "candidates" / "candidate_001.md").exists())


def _write_mock_codex_session(path: Path, project: Path) -> None:
    records = [
        {
            "type": "session_meta",
            "timestamp": "2026-07-04T00:00:00Z",
            "payload": {
                "type": "session_meta",
                "id": "demo-session",
                "cwd": str(project),
                "git": {"root": str(project)},
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-07-04T00:01:00Z",
            "payload": {
                "type": "exec_command",
                "cwd": str(project),
                "command": "bytedcli rds query --db demo_owner --sql 'select owner from task_owner' --token=abc123",
                "exit_code": 0,
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-07-04T00:02:00Z",
            "payload": {
                "type": "exec_command",
                "cwd": str(project),
                "command": "PYTHONPATH=src python -m memagent.cli trace replay --limit 10",
                "exit_code": 0,
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-07-04T00:03:00Z",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "沉淀一下：下次查 owner 问题先看 task-owner-diagnose skill，再决定是否手查 RDS。",
                    }
                ],
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-07-04T00:04:00Z",
            "payload": {
                "type": "exec_command",
                "cwd": str(project),
                "command": "curl https://example.invalid/api",
                "stderr": "error: missing Authorization: Bearer secret-token",
                "exit_code": 7,
            },
        },
    ]
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
