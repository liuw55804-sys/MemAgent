from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from memagent.llm import (
    LLM_DOCTOR_SCHEMA_VERSION,
    check_llm_provider,
    configure_semantic_mode,
    load_semantic_config,
    render_llm_doctor,
    sanitize_llm_text,
)


class LlmDoctorTest(unittest.TestCase):
    def test_missing_env_reports_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=True):
                result = check_llm_provider(config_path=Path(tmp) / "missing.json")

        payload = result.to_payload()
        self.assertEqual(payload["schema_version"], LLM_DOCTOR_SCHEMA_VERSION)
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["status"], "not_configured")
        self.assertIn("MEMAGENT_LLM_BASE_URL", payload["missing_env"])
        self.assertIn("MEMAGENT_LLM_API_KEY", payload["missing_env"])
        self.assertIn("MEMAGENT_LLM_MODEL", payload["missing_env"])
        self.assertIn("next: set MEMAGENT_LLM_BASE_URL", render_llm_doctor(result))

    def test_configured_without_live_check_does_not_call_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {
                    "MEMAGENT_LLM_BASE_URL": "https://api.example.test/v1",
                    "MEMAGENT_LLM_API_KEY": "test-key",
                    "MEMAGENT_LLM_MODEL": "demo-model",
                },
                clear=True,
            ):
                result = check_llm_provider(
                    check_live=False,
                    config_path=Path(tmp) / "missing.json",
                )

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
            with tempfile.TemporaryDirectory() as tmp:
                with mock.patch.dict(
                    os.environ,
                    {
                        "MEMAGENT_LLM_BASE_URL": base_url,
                        "MEMAGENT_LLM_API_KEY": "test-key",
                        "MEMAGENT_LLM_MODEL": "demo-model",
                    },
                    clear=True,
                ):
                    result = check_llm_provider(
                        check_live=True,
                        timeout_seconds=5,
                        config_path=Path(tmp) / "missing.json",
                    )
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        payload = result.to_payload()
        self.assertEqual(payload["status"], "live_ok")
        self.assertTrue(payload["live_checked"])
        self.assertTrue(payload["live_ok"])
        self.assertEqual(payload["chat_completions_url"], f"{base_url}/chat/completions")

    def test_configure_writes_environment_variable_name_not_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            saved = configure_semantic_mode(
                mode="hybrid",
                profile="local",
                base_url="http://127.0.0.1:1234/v1",
                model="local-model",
                api_key_env="LOCAL_MODEL_TOKEN",
                allow_no_key=True,
                config_path=path,
            )
            raw = saved.read_text(encoding="utf-8")
            settings = load_semantic_config(config_path=path)

        self.assertEqual(settings["semantic_mode"], "hybrid")
        self.assertEqual(settings["profiles"]["local"]["api_key_env"], "LOCAL_MODEL_TOKEN")
        self.assertNotIn("test-key", raw)
        self.assertNotIn("api_key\"", raw)

    def test_local_compatible_profile_can_run_without_a_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            configure_semantic_mode(
                mode="llm",
                base_url="http://127.0.0.1:1234/v1",
                model="local-model",
                allow_no_key=True,
                config_path=path,
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                result = check_llm_provider(config_path=path)

        self.assertTrue(result.configured)
        self.assertTrue(result.allow_no_key)
        self.assertFalse(result.api_key_set)

    def test_new_config_named_profile_is_available_to_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            configure_semantic_mode(
                mode="hybrid",
                profile="local",
                base_url="http://127.0.0.1:1234/v1",
                model="local-model",
                allow_no_key=True,
                config_path=path,
            )
            result = check_llm_provider(profile="local", config_path=path)

        self.assertTrue(result.configured)
        self.assertEqual(result.profile, "local")
        self.assertEqual(result.config_path, str(path))

    def test_doctor_reports_configured_custom_key_environment_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            configure_semantic_mode(
                mode="hybrid",
                profile="deepseek",
                base_url="https://api.example.test/v1",
                model="demo-model",
                api_key_env="DEEPSEEK_API_KEY",
                config_path=path,
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                result = check_llm_provider(config_path=path)

        payload = result.to_payload()
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["api_key_env"], "DEEPSEEK_API_KEY")
        self.assertEqual(payload["missing_env"], ["DEEPSEEK_API_KEY"])
        self.assertIn("DEEPSEEK_API_KEY", render_llm_doctor(result))

    def test_sanitize_llm_text_redacts_paths_urls_secrets_and_identifiers(self) -> None:
        sanitized = sanitize_llm_text(
            "inspect /tmp/example-project and https://example.test/x with token=example-secret-value for example_identifier_42"
        )

        self.assertNotIn("/tmp/example-project", sanitized)
        self.assertNotIn("https://example.test", sanitized)
        self.assertNotIn("example-secret-value", sanitized)
        self.assertNotIn("example_identifier_42", sanitized)
        self.assertIn("<path>", sanitized)
        self.assertIn("<url>", sanitized)
        self.assertIn("<secret>", sanitized)
        self.assertIn("<identifier>", sanitized)


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
