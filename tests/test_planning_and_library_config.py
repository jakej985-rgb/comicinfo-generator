"""
tests/test_planning_and_library_config.py — Phase 87 & Phase 88 Tests

Verifies:
1. Phase 87.1: Separate Planning from Execution (ProcessingPlan dataclass, plan_archive).
2. Phase 87.2: Dry-Run executes Planning Only without write side-effects.
3. Phase 88.1: Library configuration with multiple roots, recursive discovery, and ENV/YAML support.
"""

import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from config import Config, load_config, LibraryConfig, discover_library_files
from models.comic import Comic
from cache.db import CacheManager
from pipeline.resolver import MetadataResolver
from pipeline.planner import ProcessingPlan, plan_archive
from pipeline.dry_run import DryRunContext


class TestPlanningAndLibraryConfig(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="phase87_88_")
        self.cache_path = os.path.join(self.tmp, "cache.db")
        self.cache_mgr = CacheManager(self.cache_path)
        self.cfg = Config()
        self.cfg.cache.db_path = self.cache_path
        self.resolver = MetadataResolver(self.cfg, cache_mgr=self.cache_mgr)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_sample_cbz(self, name: str, dir_path: str = None) -> str:
        base = dir_path or self.tmp
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, name)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("001.jpg", b"sample_page_data")
        return path

    # ------------------------------------------------------------------ #
    # Phase 87.1: Separate Planning from Execution                       #
    # ------------------------------------------------------------------ #
    def test_87_1_plan_archive_new_comic(self):
        """87.1: plan_archive produces EMBED action with proposed fields for untagged comic."""
        cbz = self._create_sample_cbz("Batman #001 (2016).cbz")

        mock_comic = Comic(series="Batman", number="1", year=2016, publisher="DC Comics", title="I Am Gotham Part 1")
        self.resolver.resolve_identity = MagicMock(return_value=(
            MagicMock(provider="ComicVine", provider_id="4000-12345", series_name="Batman", issue_number="1"),
            MagicMock(action="EMBED", confidence=95.0)
        ))
        self.resolver.retrieve_metadata_result = MagicMock(return_value=MagicMock(
            state="METADATA_FOUND",
            comic=mock_comic,
            error_message=""
        ))

        plan = plan_archive(cbz, self.resolver)
        self.assertEqual(plan.action, "EMBED")
        self.assertEqual(plan.provider, "ComicVine")
        self.assertEqual(plan.confidence, 95.0)
        self.assertIn("Title", plan.fields)
        self.assertIn("Series", plan.fields)
        self.assertEqual(plan.proposed_comic.title, "I Am Gotham Part 1")
        self.assertFalse(plan.is_cbr)

    def test_87_1_plan_archive_skip_on_low_confidence(self):
        """87.1: plan_archive produces SKIP action when confidence is below threshold."""
        cbz = self._create_sample_cbz("Unknown_001.cbz")
        self.resolver.resolve_identity = MagicMock(return_value=(
            None,
            MagicMock(action="SKIP", confidence=30.0)
        ))

        plan = plan_archive(cbz, self.resolver)
        self.assertEqual(plan.action, "SKIP")
        self.assertEqual(plan.confidence, 30.0)
        self.assertIsNone(plan.proposed_comic)

    # ------------------------------------------------------------------ #
    # Phase 87.2: Dry-Run Executes Planning Only                         #
    # ------------------------------------------------------------------ #
    def test_87_2_dry_run_executes_planning_only(self):
        """87.2: Dry-Run context executes planning without writing to target archives."""
        cbz = self._create_sample_cbz("Batman #002 (2016).cbz")
        mtime_before = os.path.getmtime(cbz)
        size_before = os.path.getsize(cbz)

        mock_comic = Comic(series="Batman", number="2", year=2016, publisher="DC Comics")
        with DryRunContext(self.cfg) as ctx:
            ctx.resolver.resolve_identity = MagicMock(return_value=(
                MagicMock(provider="ComicVine", provider_id="4000-2", series_name="Batman", issue_number="2"),
                MagicMock(action="EMBED", confidence=90.0)
            ))
            ctx.resolver.retrieve_metadata_result = MagicMock(return_value=MagicMock(
                state="METADATA_FOUND",
                comic=mock_comic,
                error_message=""
            ))

            result = ctx.evaluate_file(cbz)
            self.assertIsNotNone(result.plan)
            self.assertEqual(result.plan.action, "EMBED")
            self.assertEqual(result.plan.provider, "ComicVine")

        # Confirm file on disk was 100% untouched
        self.assertEqual(os.path.getmtime(cbz), mtime_before)
        self.assertEqual(os.path.getsize(cbz), size_before)

    # ------------------------------------------------------------------ #
    # Phase 88.1: Library Configuration & Discovery                      #
    # ------------------------------------------------------------------ #
    def test_88_1_library_config_multiple_roots_and_recursion(self):
        """88.1: discover_library_files discovers archives across multiple roots recursively."""
        root_a = os.path.join(self.tmp, "root_a", "dc")
        root_b = os.path.join(self.tmp, "root_b", "marvel")
        
        file_a1 = self._create_sample_cbz("Batman_01.cbz", dir_path=root_a)
        file_a2 = self._create_sample_cbz("Batman_02.cbr", dir_path=root_a)
        file_b1 = self._create_sample_cbz("SpiderMan_01.cbz", dir_path=root_b)

        cfg = Config()
        cfg.library.roots = [os.path.join(self.tmp, "root_a"), os.path.join(self.tmp, "root_b")]
        cfg.library.recursive = True

        discovered = discover_library_files(cfg)
        self.assertEqual(len(discovered), 3)
        self.assertIn(os.path.abspath(file_a1), discovered)
        self.assertIn(os.path.abspath(file_a2), discovered)
        self.assertIn(os.path.abspath(file_b1), discovered)

    def test_88_1_library_config_loads_from_yaml_and_env(self):
        """88.1: Config loads library.roots and recursive flag from YAML and COMICINFO_LIBRARY_ROOTS."""
        yaml_content = f"""
library:
  roots:
    - {self.tmp}/folder1
    - {self.tmp}/folder2
  recursive: false
"""
        cfg_path = os.path.join(self.tmp, "config.yaml")
        with open(cfg_path, "w") as f:
            f.write(yaml_content)

        cfg = load_config(cfg_path)
        self.assertEqual(cfg.library.roots, [f"{self.tmp}/folder1", f"{self.tmp}/folder2"])
        self.assertFalse(cfg.library.recursive)

        # Environment variable override
        with patch.dict(os.environ, {"COMICINFO_LIBRARY_ROOTS": f"{self.tmp}/env_folder1,{self.tmp}/env_folder2"}):
            cfg_env = load_config(cfg_path)
            self.assertEqual(cfg_env.library.roots, [f"{self.tmp}/env_folder1", f"{self.tmp}/env_folder2"])


if __name__ == "__main__":
    unittest.main()
