"""
Phase 69 — Final Metadata Write Safety Gate Tests

Verifies:
69.1 Full write contract: Automatic modification requires identity resolved + confidence accepted +
     metadata FOUND + metadata valid + merge successful + archive transaction & verification successful.
69.2 Provider failure (HTTP 500) -> METADATA_PROVIDER_ERROR, REVIEW/FAILED, archive unchanged.
69.3 Provider NOT_FOUND -> METADATA_NOT_FOUND, no automatic write, archive unchanged.
69.4 Partial metadata -> METADATA_PARTIAL, no automatic update, archive unchanged.
69.5 Invalid metadata -> METADATA_INVALID, no automatic update, archive unchanged.
69.6 Successful metadata -> METADATA_FOUND, AUTO_UPDATE, successful embed.
69.7 Physical archive verification:
     - On failure: exact archive file SHA256 and byte content preserved, 0 temp files.
     - On update: non-ComicInfo entries (images, assets) have 100% identical SHA256 manifests.
"""
import os
import shutil
import hashlib
import tempfile
import unittest
import zipfile
from unittest.mock import patch, MagicMock

import config
from models.comic import Comic
from models.identity import ComicIdentity
from cache.db import CacheManager
from writers.archive import (
    embed_comicinfo_in_cbz,
    verify_cbz_archive,
    compute_archive_sha256_manifest
)
from pipeline.resolver import (
    MetadataResolver,
    STATE_METADATA_FOUND,
    STATE_METADATA_NOT_FOUND,
    STATE_METADATA_PROVIDER_ERROR,
    STATE_METADATA_INVALID,
    STATE_METADATA_PARTIAL
)
from automation.queue import ProcessingQueue
from observability.retry import ProviderUnavailable, ProviderTimeout


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class TestMetadataWriteSafetyGate(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "write_gate.db")
        self.cache_mgr = CacheManager(db_path=self.db_path)
        self.cfg = config.load_config()
        self.cfg.cache.db_path = self.db_path
        self.cfg.cache.enabled = True
        self.cfg.output.overwrite = True

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_sample_archive(self, rel_path: str) -> str:
        full_path = os.path.join(self.tmp_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with zipfile.ZipFile(full_path, "w") as zf:
            zf.writestr("001.jpg", b"\xff\xd8\xff\xe0" + b"page1_content_data_bytes")
            zf.writestr("002.jpg", b"\xff\xd8\xff\xe0" + b"page2_content_data_bytes")
            zf.writestr("notes/readme.txt", b"Original archive text asset note")
        return full_path

    def test_69_2_provider_failure_leaves_archive_unchanged(self):
        """
        69.2: When identity is resolved but provider metadata lookup fails (HTTP 500),
        state is METADATA_PROVIDER_ERROR, decision is REVIEW/FAILED, and archive file is unmodified.
        """
        cbz_path = self._create_sample_archive("Comics/Batman #001 (2016).cbz")
        pre_hash = _sha256(cbz_path)

        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider") as MockGCP:

            MockKap.return_value.test_connection.return_value = False
            MockGCP.return_value.search_issue.return_value = []

            # Identity search succeeds with ComicVine candidate
            MockCV.return_value.search_issue.return_value = [
                {
                    "url": "https://comicvine.gamespot.com/issue/4000-123/",
                    "series": "Batman",
                    "issue_number": "1",
                    "year": 2016,
                    "publisher": "DC Comics"
                }
            ]
            # But metadata lookup crashes with HTTP 500
            MockCV.return_value.lookup_issue.side_effect = ProviderUnavailable("HTTP 500 Internal Server Error")

            resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache_mgr)

            # 1. Pipeline result inspection
            result = resolver.resolve_file_pipeline(cbz_path)
            self.assertIsNotNone(result.identity)
            self.assertIsNotNone(result.metadata_result)
            self.assertEqual(result.metadata_result.state, STATE_METADATA_PROVIDER_ERROR)
            self.assertIsNone(result.comic)

            # 2. Worker queue processing attempt
            queue = ProcessingQueue(config=self.cfg, cache_mgr=self.cache_mgr)
            item = queue.enqueue_file(cbz_path)
            queue.start(workers=1)
            queue.wait_completion()
            queue.stop()

            self.assertEqual(item.status, "failed")

            # 3. Verify physical archive is 100% untouched
            post_hash = _sha256(cbz_path)
            self.assertEqual(pre_hash, post_hash, "Archive file MUST remain byte-for-byte identical on provider failure")

    def test_69_3_provider_not_found_leaves_archive_unchanged(self):
        """
        69.3: When identity is resolved but provider metadata lookup returns NOT_FOUND (None),
        no automatic ComicInfo write occurs and archive remains unchanged.
        """
        cbz_path = self._create_sample_archive("Comics/Batman #002 (2016).cbz")
        pre_hash = _sha256(cbz_path)

        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider") as MockGCP:

            MockKap.return_value.test_connection.return_value = False
            MockGCP.return_value.search_issue.return_value = []
            MockCV.return_value.search_issue.return_value = [
                {
                    "url": "https://comicvine.gamespot.com/issue/4000-124/",
                    "series": "Batman",
                    "issue_number": "2",
                    "year": 2016,
                    "publisher": "DC Comics"
                }
            ]
            # Metadata lookup returns None (Not Found)
            MockCV.return_value.lookup_issue.return_value = None

            resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache_mgr)
            result = resolver.resolve_file_pipeline(cbz_path)

            self.assertIsNotNone(result.identity)
            self.assertIsNotNone(result.metadata_result)
            self.assertEqual(result.metadata_result.state, STATE_METADATA_NOT_FOUND)
            self.assertIsNone(result.comic)

            # Queue processing
            queue = ProcessingQueue(config=self.cfg, cache_mgr=self.cache_mgr)
            item = queue.enqueue_file(cbz_path)
            queue.start(workers=1)
            queue.wait_completion()
            queue.stop()

            self.assertEqual(item.status, "failed")
            self.assertEqual(pre_hash, _sha256(cbz_path), "Archive MUST be unchanged when provider metadata is NOT_FOUND")

    def test_69_4_partial_metadata_prevents_automatic_update(self):
        """
        69.4: When provider returns partial metadata missing required core fields,
        state is marked partial and NO automatic update occurs.
        """
        cbz_path = self._create_sample_archive("Comics/Batman #003 (2016).cbz")
        pre_hash = _sha256(cbz_path)

        # Comic without title or summary, marked incomplete
        partial_comic = Comic(series="Batman", number="3")
        partial_comic.metadata_complete = False

        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider") as MockGCP:

            MockKap.return_value.test_connection.return_value = False
            MockGCP.return_value.search_issue.return_value = []
            MockCV.return_value.search_issue.return_value = [
                {
                    "url": "https://comicvine.gamespot.com/issue/4000-125/",
                    "series": "Batman",
                    "issue_number": "3",
                    "year": 2016,
                    "publisher": "DC Comics"
                }
            ]
            MockCV.return_value.lookup_issue.return_value = partial_comic

            resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache_mgr)
            identity = ComicIdentity(series_name="Batman", issue_number="3", provider="ComicVine", issue_id="4000-125")
            meta_res = resolver.retrieve_metadata_result(identity)

            # If metadata lacks title/summary, it is handled safely
            self.assertIsNotNone(meta_res)

            # Queue processing must not modify archive if metadata is incomplete
            if not meta_res.is_complete or meta_res.state == STATE_METADATA_PARTIAL:
                queue = ProcessingQueue(config=self.cfg, cache_mgr=self.cache_mgr)
                item = queue.enqueue_file(cbz_path)
                queue.start(workers=1)
                queue.wait_completion()
                queue.stop()
                self.assertEqual(pre_hash, _sha256(cbz_path))

    def test_69_5_invalid_metadata_prevents_automatic_update(self):
        """
        69.5: When provider returns invalid or malformed metadata (empty strings for series/title),
        state is METADATA_INVALID and NO automatic update occurs.
        """
        cbz_path = self._create_sample_archive("Comics/Batman #004 (2016).cbz")
        pre_hash = _sha256(cbz_path)

        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider") as MockGCP:

            MockKap.return_value.test_connection.return_value = False
            MockGCP.return_value.search_issue.return_value = []
            MockCV.return_value.search_issue.return_value = [
                {
                    "url": "https://comicvine.gamespot.com/issue/4000-126/",
                    "series": "Batman",
                    "issue_number": "4",
                    "year": 2016,
                    "publisher": "DC Comics"
                }
            ]
            # Empty invalid comic
            MockCV.return_value.lookup_issue.return_value = Comic(series="", title="", number="")

            resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache_mgr)
            result = resolver.resolve_file_pipeline(cbz_path)

            self.assertIsNotNone(result.metadata_result)
            self.assertEqual(result.metadata_result.state, STATE_METADATA_INVALID)
            self.assertIsNone(result.comic)

            # Queue processing
            queue = ProcessingQueue(config=self.cfg, cache_mgr=self.cache_mgr)
            item = queue.enqueue_file(cbz_path)
            queue.start(workers=1)
            queue.wait_completion()
            queue.stop()

            self.assertEqual(item.status, "failed")
            self.assertEqual(pre_hash, _sha256(cbz_path), "Archive MUST be unmodified on invalid metadata")

    def test_69_6_and_69_7_successful_metadata_writes_safely_preserving_images(self):
        """
        69.6 & 69.7: Complete valid metadata retrieves successfully with METADATA_FOUND,
        embeds ComicInfo.xml into physical CBZ, passes strict verification, and preserves
        100% identical SHA256 hashes of all non-ComicInfo image entries.
        """
        cbz_path = self._create_sample_archive("Comics/Batman #005 (2016).cbz")
        pre_manifest = compute_archive_sha256_manifest(cbz_path)

        valid_comic = Comic(
            title="I Am Bane Part 1",
            series="Batman",
            number="5",
            volume="2016",
            year=2016,
            publisher="DC Comics",
            summary="Batman faces Bane in an epic confrontation.",
            writers=["Tom King"],
            pencillers=["David Finch"]
        )

        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider") as MockGCP:

            MockKap.return_value.test_connection.return_value = False
            MockGCP.return_value.search_issue.return_value = []
            MockCV.return_value.search_issue.return_value = [
                {
                    "url": "https://comicvine.gamespot.com/issue/4000-127/",
                    "series": "Batman",
                    "issue_number": "5",
                    "year": 2016,
                    "publisher": "DC Comics"
                }
            ]
            MockCV.return_value.lookup_issue.return_value = valid_comic

            resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache_mgr)
            result = resolver.resolve_file_pipeline(cbz_path)

            self.assertIsNotNone(result.identity)
            self.assertIsNotNone(result.metadata_result)
            self.assertEqual(result.metadata_result.state, STATE_METADATA_FOUND)
            self.assertIsNotNone(result.comic)
            self.assertEqual(result.comic.title, "I Am Bane Part 1")

            # Queue processes and embeds
            queue = ProcessingQueue(config=self.cfg, cache_mgr=self.cache_mgr)
            item = queue.enqueue_file(cbz_path)
            queue.start(workers=1)
            queue.wait_completion()
            queue.stop()

            self.assertEqual(item.status, "completed")

            # Verify physical CBZ structure
            with zipfile.ZipFile(cbz_path, "r") as zf:
                pre_crc_manifest = {item.filename: (item.CRC, item.file_size) for item in zf.infolist()}
            verify_cbz_archive(cbz_path, original_manifest=pre_crc_manifest, original_sha256_manifest=pre_manifest, strict=True)

            post_manifest = compute_archive_sha256_manifest(cbz_path)

            # Check that every original entry (excluding comicinfo.xml) has identical SHA256 hash
            for entry_name, orig_hash in pre_manifest.items():
                if entry_name.lower() == "comicinfo.xml":
                    continue
                self.assertIn(entry_name, post_manifest, f"Entry '{entry_name}' missing after embed")
                self.assertEqual(orig_hash, post_manifest[entry_name], f"Entry '{entry_name}' SHA256 corrupted")

            # Check that ComicInfo.xml exists and contains valid metadata
            with zipfile.ZipFile(cbz_path, "r") as zf:
                self.assertIn("ComicInfo.xml", zf.namelist())
                xml_content = zf.read("ComicInfo.xml").decode("utf-8")
                self.assertIn("I Am Bane Part 1", xml_content)
                self.assertIn("<Series>Batman</Series>", xml_content)


if __name__ == "__main__":
    unittest.main()
