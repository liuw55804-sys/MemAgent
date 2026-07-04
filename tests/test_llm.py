from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from memagent.llm import LLM_DOCTOR_SCHEMA_VERSION, check_llm_provider, render_llm_doctor


class LlmDoctorTest(unittest.TestCase):
    def test_missing_env_reports_not_configured(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            result = check_llm_provider()

        payload = result.to_payload()
        self.assertEqual(payload["schema_version"], LLM_DOCTOR_SCHEMA_VERSION)
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["status"], "not_configured")
        self.assertIn("MEMAGENT_LLM_BASE_URL", payload["missing_env"])
        self.assertIn("MEMAGENT_LLM_API_KEY", payload["missing_env"])
        self.assertIn("MEMAGENT_LLM_MODEL", payload["missing_env"])
        self.assertIn("Set these environment variables", render_llm_doctor(result))

    def test_configured_without_live_check_does_not_call_api(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "MEMAGENT_LLM_BASE_URL": "https://api.example.test/v1",
                "MEMAGENT_LLM_API_KEY": "test-key",
                "MEMAGENT_LLM_MODEL": "demo-model",
            },
            clear=True,
        ):
            result = check_llm_provider(check_live=False)

        payload = result.to_payload()
        self.assertTrue(payload["configured"])
        self.assertEqual(payload["status"], "configured")
        self.assertFalse(payload["live_checked"])
        self.assertEqual(payload["chat_completions_url"], "https://api.example.test/v1/chat/completions")
        self.assertTrue(payload["api_key_set"])
        self.assertNotIn("test-key", render_llm_doctor(result))

    def test_profile_config_without_live_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "llm_profiles.json"
            with self.subTest("profile"):
                config_path.write_text(
                    json.dumps(
                        {
                            "profiles": {
                                "demo": {
                                    "provider": "openai-compatible",
                                    "base_url": "https://api.example.test/v1",
                                    "api_key": "test-key",
                                    "model": "demo-model",
                                }
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                result = check_llm_provider(profile="demo", config_path=config_path)

        payload = result.to_payload()
        self.assertTrue(payload["configured"])
        self.assertEqual(payload["profile"], "demo")
        self.assertEqual(payload["config_path"], str(config_path))
        self.assertNotIn("test-key", render_llm_doctor(result))

    def test_live_check_with_local_openai_compatible_server(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), _FakeOpenAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_port}/v1"
            with mock.patch.dict(
                os.environ,
                {
                    "MEMAGENT_LLM_BASE_URL": base_url,
                    "MEMAGENT_LLM_API_KEY": "test-key",
                    "MEMAGENT_LLM_MODEL": "demo-model",
                },
                clear=True,
            ):
                result = check_llm_provider(check_live=True, timeout_seconds=5)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        payload = result.to_payload()
        self.assertEqual(payload["status"], "live_ok")
        self.assertTrue(payload["live_checked"])
        self.assertTrue(payload["live_ok"])
        self.assertEqual(payload["chat_completions_url"], f"{base_url}/chat/completions")


class _FakeOpenAIHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        payload = json.loads(body)
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        if payload.get("model") != "demo-model":
            self.send_response(400)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "memagent-ok",
                            }
                        }
                    ]
                }
            ).encode("utf-8")
        )

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    unittest.main()
