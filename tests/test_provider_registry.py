"""
tests/test_provider_registry.py — Phase 84: Provider Registry Tests

Verifies:
1. 84.1: ProviderRegistry registration, lookup, normalization, and lifecycle.
2. 84.2: MetadataResolver dependency on ProviderRegistry.
3. 84.3: Provider priority order configurable via Config and Environment.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from config import Config, load_config, ProvidersConfig
from pipeline.resolver import MetadataResolver
from providers.base import BaseProvider
from providers.comicvine.provider import ComicVineProvider
from providers.gcd.provider import GCPProvider
from providers.kapowarr.provider import KapowarrProvider
from providers.registry import ProviderRegistry


class DummyCustomProvider(BaseProvider):
    def get_name(self) -> str:
        return "CustomProvider"
    def search_series(self, query: str):
        return []
    def search_issue(self, query: str):
        return []
    def lookup_volume(self, volume_id: str):
        return ("", {}, [])
    def lookup_issue(self, issue_id_or_url: str):
        return None


class TestProviderRegistry(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="phase84_reg_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # 84.1: ProviderRegistry Lifecycle & Lookup                          #
    # ------------------------------------------------------------------ #
    def test_84_1_register_and_retrieve_providers(self):
        """84.1: Register and retrieve standard and custom providers with case/alias normalization."""
        registry = ProviderRegistry()
        mock_cv = MagicMock(spec=ComicVineProvider)
        mock_kap = MagicMock(spec=KapowarrProvider)
        custom_prov = DummyCustomProvider()

        registry.register("ComicVine", mock_cv)
        registry.register("Kapowarr", mock_kap)
        registry.register("custom", custom_prov)

        self.assertIs(registry.get("comicvine"), mock_cv)
        self.assertIs(registry.get("CV"), mock_cv)
        self.assertIs(registry.get("kapowarr"), mock_kap)
        self.assertIs(registry.get("custom"), custom_prov)
        self.assertTrue(registry.has_provider("comicvine"))
        self.assertFalse(registry.has_provider("nonexistent"))

        registry.unregister("custom")
        self.assertFalse(registry.has_provider("custom"))
        self.assertIsNone(registry.get("custom"))

    def test_84_1_from_config_factory(self):
        """84.1: ProviderRegistry.from_config builds registry with configured settings."""
        cfg = Config()
        cfg.comicvine.api_key = "test_key_123"
        cfg.kapowarr.url = "http://192.168.1.50:5656"

        registry = ProviderRegistry.from_config(cfg)
        self.assertTrue(registry.has_provider("kapowarr"))
        self.assertTrue(registry.has_provider("comicvine"))
        self.assertTrue(registry.has_provider("gcd"))

        kap = registry.get("kapowarr")
        self.assertEqual(kap.url, "http://192.168.1.50:5656")

    # ------------------------------------------------------------------ #
    # 84.2: MetadataResolver Depends on Registry                         #
    # ------------------------------------------------------------------ #
    def test_84_2_resolver_uses_provided_registry(self):
        """84.2: MetadataResolver delegates provider lookups and calls through ProviderRegistry."""
        registry = ProviderRegistry()
        mock_cv = MagicMock(spec=ComicVineProvider)
        mock_kap = MagicMock(spec=KapowarrProvider)
        mock_gcd = MagicMock(spec=GCPProvider)

        registry.register("comicvine", mock_cv)
        registry.register("kapowarr", mock_kap)
        registry.register("gcd", mock_gcd)

        resolver = MetadataResolver(registry=registry)
        self.assertIs(resolver.registry, registry)
        self.assertIs(resolver.kapowarr, mock_kap)
        self.assertIs(resolver.comicvine, mock_cv)
        self.assertIs(resolver.gcp, mock_gcd)

    def test_84_2_resolver_dynamic_registry_injection(self):
        """84.2: Dynamically registering a provider in resolver.registry updates resolver properties."""
        resolver = MetadataResolver()
        new_kap = MagicMock(spec=KapowarrProvider)
        resolver.registry.register("kapowarr", new_kap)
        self.assertIs(resolver.kapowarr, new_kap)

    # ------------------------------------------------------------------ #
    # 84.3: Provider Priority Configuration                              #
    # ------------------------------------------------------------------ #
    def test_84_3_provider_priority_ordering(self):
        """84.3: get_ordered_providers returns providers adhering to configured priority order."""
        registry = ProviderRegistry(priority=["comicvine", "gcd", "kapowarr"])
        mock_cv = MagicMock(spec=ComicVineProvider)
        mock_kap = MagicMock(spec=KapowarrProvider)
        mock_gcd = MagicMock(spec=GCPProvider)

        registry.register("kapowarr", mock_kap)
        registry.register("comicvine", mock_cv)
        registry.register("gcd", mock_gcd)

        ordered = registry.get_ordered_providers()
        self.assertEqual(ordered, [mock_cv, mock_gcd, mock_kap])

        # Dynamic priority change
        registry.priority = ["gcd", "kapowarr", "comicvine"]
        ordered_new = registry.get_ordered_providers()
        self.assertEqual(ordered_new, [mock_gcd, mock_kap, mock_cv])

    def test_84_3_config_loads_provider_priority_from_yaml_and_env(self):
        """84.3: Config loads providers.priority from YAML and COMICINFO_PROVIDER_PRIORITY env var."""
        yaml_content = """
providers:
  priority:
    - gcd
    - kapowarr
    - comicvine
"""
        cfg_path = os.path.join(self.tmp, "config.yaml")
        with open(cfg_path, "w") as f:
            f.write(yaml_content)

        cfg = load_config(cfg_path)
        self.assertEqual(cfg.providers.priority, ["gcd", "kapowarr", "comicvine"])

        # Environment variable override
        with patch.dict(os.environ, {"COMICINFO_PROVIDER_PRIORITY": "comicvine,kapowarr"}):
            cfg_env = load_config(cfg_path)
            self.assertEqual(cfg_env.providers.priority, ["comicvine", "kapowarr"])


if __name__ == "__main__":
    unittest.main()
