"""
Phase 71 — Production Configuration Hardening Tests

Verifies:
71.1 Separate disabled from misconfigured (DISABLED, REACHABLE, AUTH_FAILED, UNREACHABLE).
71.2 Startup configuration validation (URLs, keys, workers, log levels, db paths, conversion tools).
71.3 Safe defaults (non-destructive overwrite=False, sensible defaults).
71.4 Environment variable handling and secret masking (mask_secret, to_safe_dict).
71.5 Clear failure behavior (explicit ConfigurationError messages).
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import config
from config import (
    Config,
    ConfigurationError,
    validate_startup_config,
    mask_secret,
    check_conversion_tools,
    load_config
)
from providers.kapowarr.provider import KapowarrProvider
from providers.base import ProviderAuthenticationError, ProviderConnectionError


class TestProductionConfigHardening(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="cfg_hardening_")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_71_1_separate_disabled_from_misconfigured_states(self):
        """
        71.1: Tests that Kapowarr connection distinguishes:
        DISABLED, REACHABLE, AUTH_FAILED, and UNREACHABLE.
        """
        # 1. Disabled (empty URL)
        prov_disabled = KapowarrProvider(url="", api_key="")
        status, msg = prov_disabled.test_connection_detailed()
        self.assertEqual(status, "DISABLED")
        self.assertIn("disabled", msg.lower())

        # 2. Reachable (200 OK)
        prov_online = KapowarrProvider(url="http://localhost:5656", api_key="secret123")
        with patch.object(prov_online.client, "get", return_value=[{"id": 1, "name": "Batman"}]):
            status, msg = prov_online.test_connection_detailed()
            self.assertEqual(status, "REACHABLE")
            self.assertIn("reachable", msg.lower())

        # 3. Authentication failed (401/403)
        prov_auth_fail = KapowarrProvider(url="http://localhost:5656", api_key="invalid_key")
        with patch.object(prov_auth_fail.client, "get", side_effect=ProviderAuthenticationError("HTTP 401 Unauthorized", provider_name="Kapowarr")):
            status, msg = prov_auth_fail.test_connection_detailed()
            self.assertEqual(status, "AUTH_FAILED")
            self.assertIn("authentication failed", msg.lower())

        # 4. Unreachable (connection error / timeout)
        prov_offline = KapowarrProvider(url="http://192.0.2.1:5656", api_key="secret123")
        with patch.object(prov_offline.client, "get", side_effect=ProviderConnectionError("Connection timed out", provider_name="Kapowarr")):
            status, msg = prov_offline.test_connection_detailed()
            self.assertEqual(status, "UNREACHABLE")
            self.assertIn("unreachable", msg.lower())

    def test_71_2_startup_validation_valid_and_invalid_configurations(self):
        """
        71.2: Validates URLs, keys, workers, log levels, database paths, and conversion tools.
        """
        cfg = Config()
        cfg.cache.db_path = os.path.join(self.tmp_dir, "test.db")
        warnings = validate_startup_config(cfg)
        self.assertIsInstance(warnings, list)

        # Invalid Kapowarr URL
        cfg_bad_url = Config()
        cfg_bad_url.kapowarr.url = "localhost:5656"  # missing http:// or https://
        with self.assertRaises(ConfigurationError) as ctx:
            validate_startup_config(cfg_bad_url)
        self.assertIn("URL must begin with 'http://' or 'https://'", str(ctx.exception))

        # Invalid ComicVine API key (whitespace)
        cfg_bad_key = Config()
        cfg_bad_key.comicvine.api_key = "cv key with whitespace"
        with self.assertRaises(ConfigurationError) as ctx:
            validate_startup_config(cfg_bad_key)
        self.assertIn("ComicVine API key contains invalid whitespace", str(ctx.exception))

        # Invalid workers (< 1)
        cfg_bad_workers = Config()
        cfg_bad_workers.automation.workers = 0
        with self.assertRaises(ConfigurationError) as ctx:
            validate_startup_config(cfg_bad_workers)
        self.assertIn("workers must be >= 1", str(ctx.exception))

        # Invalid log level
        cfg_bad_log = Config()
        cfg_bad_log.logging.level = "SUPER_VERBOSE"
        with self.assertRaises(ConfigurationError) as ctx:
            validate_startup_config(cfg_bad_log)
        self.assertIn("Invalid log level", str(ctx.exception))

        # Check conversion tools
        tools = check_conversion_tools()
        self.assertIn("unrar", tools)
        self.assertIn("rar", tools)
        self.assertIn("7z", tools)

    def test_71_3_safe_defaults_guarantee(self):
        """
        71.3: Default configuration must default to non-destructive settings.
        """
        cfg = Config()
        self.assertFalse(cfg.output.overwrite, "Default overwrite MUST be False to prevent accidental overwrites")
        self.assertTrue(cfg.output.embed_xml, "Default embed_xml should be True")
        self.assertGreaterEqual(cfg.automation.workers, 1, "Default workers must be >= 1")

    def test_71_4_env_variable_resolution_and_secret_masking(self):
        """
        71.4: Tests environment variable hierarchy and ensures secrets are masked in safe dicts.
        """
        env_vars = {
            "COMICVINE_API_KEY": "cv_secret_api_key_123456789",
            "KAPOWARR_URL": "http://my-kapowarr:5656",
            "KAPOWARR_API_KEY": "kap_secret_token_987654321",
            "COMICINFO_WORKERS": "8",
            "COMICINFO_LOG_LEVEL": "DEBUG"
        }

        with patch.dict(os.environ, env_vars):
            cfg = load_config()
            self.assertEqual(cfg.comicvine.api_key, "cv_secret_api_key_123456789")
            self.assertEqual(cfg.kapowarr.url, "http://my-kapowarr:5656")
            self.assertEqual(cfg.kapowarr.api_key, "kap_secret_token_987654321")
            self.assertEqual(cfg.automation.workers, 8)
            self.assertEqual(cfg.logging.level, "DEBUG")

            # Verify secrets are masked in to_safe_dict()
            safe_dict = cfg.to_safe_dict()
            self.assertNotIn("cv_secret_api_key_123456789", safe_dict["comicvine"]["api_key"])
            self.assertIn("...", safe_dict["comicvine"]["api_key"])
            self.assertNotIn("kap_secret_token_987654321", safe_dict["kapowarr"]["api_key"])
            self.assertIn("...", safe_dict["kapowarr"]["api_key"])

        # Test mask_secret helper directly
        self.assertEqual(mask_secret(""), "<not set>")
        self.assertEqual(mask_secret("short"), "********")
        masked = mask_secret("1234567890abcdef")
        self.assertEqual(masked, "1234...cdef")

    def test_71_5_explicit_configuration_error_messages(self):
        """
        71.5: Verifies clear, actionable failure explanations on bad configuration.
        """
        cfg = Config()
        cfg.kapowarr.url = "invalid_scheme_url"
        try:
            validate_startup_config(cfg)
            self.fail("Expected ConfigurationError for invalid scheme URL")
        except ConfigurationError as ce:
            self.assertIn("Configuration error: Kapowarr is enabled but URL is invalid", str(ce))


if __name__ == "__main__":
    unittest.main()
