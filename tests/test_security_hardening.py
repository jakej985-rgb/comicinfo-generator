"""
tests/test_security_hardening.py — Phase 80: Security Hardening Tests

Verifies:
1. 80.1: API keys never exposed in GET /api/config, error messages, or logs.
   - api_key_set == True when configured, False when missing.
   - Key updates preserved without leaking raw values.
2. 80.2: CORS origins are restricted to localhost/127.0.0.1 and configured cors_origins.
   - Allowed origins receive Access-Control-Allow-Origin header matching the origin.
   - Unauthorized external origins receive NO Access-Control-Allow-Origin header.
3. 80.3: Server binds safely to 127.0.0.1 by default rather than 0.0.0.0.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from config import Config, ServerConfig, load_config, DEFAULT_CONFIG_PATH
from api.handlers import ComicServerHandler, sanitize_error_text


class MockSocket:
    def __init__(self, request_bytes: bytes):
        self._rfile = io.BytesIO(request_bytes)
        self._wfile = io.BytesIO()

    def makefile(self, mode, *args, **kwargs):
        if "r" in mode:
            return self._rfile
        elif "w" in mode or "b" in mode:
            return self._wfile
        return self._rfile


class TestSecurityHardening(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="phase80_sec_")
        self.config_path = os.path.join(self.tmp, "config.yaml")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _simulate_http_request(self, method: str, path: str, headers: dict = None, body: dict = None) -> tuple:
        """Simulates an HTTP request against ComicServerHandler without opening real network sockets."""
        headers = headers or {}
        body_bytes = json.dumps(body).encode("utf-8") if body else b""

        req_lines = [f"{method} {path} HTTP/1.1", f"Host: 127.0.0.1:5005"]
        for k, v in headers.items():
            req_lines.append(f"{k}: {v}")
        if body_bytes:
            req_lines.append(f"Content-Length: {len(body_bytes)}")
            req_lines.append("Content-Type: application/json")
        req_lines.append("")
        req_lines.append("")

        raw_req = "\r\n".join(req_lines).encode("utf-8") + body_bytes
        rfile = io.BytesIO(raw_req)
        wfile = io.BytesIO()

        # Mock socket and request handling
        handler = ComicServerHandler.__new__(ComicServerHandler)
        handler.rfile = rfile
        handler.wfile = wfile
        handler.client_address = ("127.0.0.1", 54321)
        handler.server = MagicMock()
        handler.raw_requestline = rfile.readline()
        handler.parse_request()

        if method == "GET":
            handler.do_GET()
        elif method == "POST":
            handler.do_POST()
        elif method == "OPTIONS":
            handler.do_OPTIONS()

        wfile.seek(0)
        raw_resp = wfile.read().decode("utf-8", errors="replace")
        parts = raw_resp.split("\r\n\r\n", 1)
        header_part = parts[0]
        body_part = parts[1] if len(parts) > 1 else ""

        status_line = header_part.split("\r\n")[0]
        status_code = int(status_line.split(" ")[1]) if " " in status_line else 0

        resp_headers = {}
        for line in header_part.split("\r\n")[1:]:
            if ": " in line:
                hk, hv = line.split(": ", 1)
                resp_headers[hk] = hv

        resp_json = None
        if "application/json" in resp_headers.get("Content-Type", "") and body_part:
            try:
                resp_json = json.loads(body_part)
            except Exception:
                pass

        return status_code, resp_headers, resp_json, body_part

    # ------------------------------------------------------------------ #
    # 80.1: Remove API keys from /api/config & Sanitize Errors             #
    # ------------------------------------------------------------------ #
    def test_80_1_get_config_masks_api_keys(self):
        """80.1: GET /api/config must never return raw API keys and must indicate api_key_set."""
        test_cv_key = "secret_comicvine_key_12345"
        test_kap_key = "secret_kapowarr_key_67890"

        with patch("api.handlers.load_config") as mock_load:
            cfg = Config()
            cfg.comicvine.api_key = test_cv_key
            cfg.kapowarr.api_key = test_kap_key
            mock_load.return_value = cfg

            status, headers, resp_json, body_text = self._simulate_http_request("GET", "/api/config")
            self.assertEqual(status, 200)
            self.assertTrue(resp_json["success"])

            # Verify secrets are NOT in the payload
            self.assertNotIn(test_cv_key, body_text)
            self.assertNotIn(test_kap_key, body_text)

            # Verify boolean indicators
            self.assertTrue(resp_json["config"]["comicvine"]["api_key_set"])
            self.assertTrue(resp_json["config"]["kapowarr"]["api_key_set"])
            self.assertNotIn("api_key", resp_json["config"]["comicvine"])

    def test_80_1_get_config_reports_false_when_keys_missing(self):
        """80.1: api_key_set is False when keys are empty or unconfigured."""
        with patch("api.handlers.load_config") as mock_load:
            cfg = Config()
            cfg.comicvine.api_key = ""
            cfg.kapowarr.api_key = ""
            mock_load.return_value = cfg

            status, headers, resp_json, body_text = self._simulate_http_request("GET", "/api/config")
            self.assertEqual(status, 200)
            self.assertFalse(resp_json["config"]["comicvine"]["api_key_set"])
            self.assertFalse(resp_json["config"]["kapowarr"]["api_key_set"])

    def test_80_1_error_messages_sanitize_raw_secrets(self):
        """80.1: Error responses never include raw configured API keys."""
        test_cv_key = "super_secret_cv_key_abcdef"
        test_kap_key = "super_secret_kap_key_xyz123"

        with patch("api.handlers.load_config") as mock_load:
            cfg = Config()
            cfg.comicvine.api_key = test_cv_key
            cfg.kapowarr.api_key = test_kap_key
            mock_load.return_value = cfg

            raw_err = f"Failed to authenticate with key {test_cv_key} and kapowarr {test_kap_key}!"
            sanitized = sanitize_error_text(raw_err)
            self.assertNotIn(test_cv_key, sanitized)
            self.assertNotIn(test_kap_key, sanitized)
            self.assertIn("********", sanitized)

    def test_80_1_post_config_preserves_existing_keys_when_omitted(self):
        """80.1: POST /api/config preserves existing keys if omitted or empty without clear flag."""
        initial_cfg_yaml = """
comicvine:
  api_key: "existing_cv_key"
kapowarr:
  url: "http://localhost:5656"
  api_key: "existing_kap_key"
server:
  host: "127.0.0.1"
"""
        with open(self.config_path, "w") as f:
            f.write(initial_cfg_yaml)

        with patch("api.handlers.DEFAULT_CONFIG_PATH", self.config_path):
            # Update only automation workers, omit api_keys
            update_payload = {
                "config": {
                    "automation": {"workers": 8}
                }
            }
            status, _, resp_json, _ = self._simulate_http_request("POST", "/api/config", body=update_payload)
            self.assertEqual(status, 200)

            # Reload and verify keys are preserved
            reloaded = load_config(self.config_path)
            self.assertEqual(reloaded.comicvine.api_key, "existing_cv_key")
            self.assertEqual(reloaded.kapowarr.api_key, "existing_kap_key")
            self.assertEqual(reloaded.automation.workers, 8)

    # ------------------------------------------------------------------ #
    # 80.2: CORS Hardening                                               #
    # ------------------------------------------------------------------ #
    def test_80_2_cors_allowed_for_localhost(self):
        """80.2: Requests from localhost origin receive Access-Control-Allow-Origin header."""
        status, headers, _, _ = self._simulate_http_request(
            "OPTIONS", "/api/config", headers={"Origin": "http://localhost:5005"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "http://localhost:5005")

    def test_80_2_cors_allowed_for_127_0_0_1(self):
        """80.2: Requests from 127.0.0.1 origin receive Access-Control-Allow-Origin header."""
        status, headers, _, _ = self._simulate_http_request(
            "OPTIONS", "/api/config", headers={"Origin": "http://127.0.0.1:5005"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:5005")

    def test_80_2_cors_allowed_for_explicitly_configured_origin(self):
        """80.2: Requests from explicitly configured cors_origins receive allow header."""
        with patch("api.handlers.load_config") as mock_load:
            cfg = Config()
            cfg.server.cors_origins = ["https://my-comic-dashboard.internal"]
            mock_load.return_value = cfg

            status, headers, _, _ = self._simulate_http_request(
                "OPTIONS", "/api/config", headers={"Origin": "https://my-comic-dashboard.internal"}
            )
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("Access-Control-Allow-Origin"), "https://my-comic-dashboard.internal")

    def test_80_2_cors_rejected_for_unauthorized_external_origin(self):
        """80.2: Requests from untrusted external origins do NOT receive Access-Control-Allow-Origin."""
        status, headers, _, _ = self._simulate_http_request(
            "OPTIONS", "/api/config", headers={"Origin": "https://malicious-site.com"}
        )
        self.assertEqual(status, 200)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    # ------------------------------------------------------------------ #
    # 80.3: Bind safely to 127.0.0.1 by default                          #
    # ------------------------------------------------------------------ #
    def test_80_3_default_host_binding(self):
        """80.3: Server defaults to binding to 127.0.0.1 rather than 0.0.0.0."""
        cfg = Config()
        self.assertEqual(cfg.server.host, "127.0.0.1")
        self.assertEqual(cfg.server.port, 5005)

        loaded = load_config(self.config_path)
        self.assertEqual(loaded.server.host, "127.0.0.1")
        self.assertEqual(loaded.server.port, 5005)


if __name__ == "__main__":
    unittest.main()
