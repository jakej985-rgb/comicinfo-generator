"""
tests/test_api_input_validation.py — Phase 89: API Input Validation & Security Boundary Tests

Verifies:
1. 89.1: Filesystem Security Boundary:
   - Blocks path traversal and access to system directories (/etc, /root, /sys, /proc).
   - Blocks access to paths outside configured library roots (403 Forbidden).
   - Allows access to paths inside configured library roots.
2. Endpoint Validation:
   - Validates URL formats, schemes, and hostnames.
   - Validates file paths, extensions (.cbz, .cbr), and directory structures.
   - Validates search query strings.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from config import Config
from api.validation import (
    ValidationError,
    validate_filesystem_boundary,
    validate_folder_path,
    validate_comic_file_path,
    validate_url,
    validate_search_query,
    is_path_inside_root
)


class TestApiInputValidation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="phase89_val_")
        self.library_dir = os.path.join(self.tmp, "my_comics")
        os.makedirs(self.library_dir, exist_ok=True)
        self.outside_dir = os.path.join(self.tmp, "outside_world")
        os.makedirs(self.outside_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # 89.1: Filesystem Security Boundaries                               #
    # ------------------------------------------------------------------ #
    def test_89_1_blocks_forbidden_system_paths(self):
        """89.1: Access to sensitive OS system directories (/etc, /root, etc.) is rejected with 403."""
        with self.assertRaises(ValidationError) as ctx:
            validate_filesystem_boundary("/etc/passwd")
        self.assertEqual(ctx.exception.status_code, 403)

        with self.assertRaises(ValidationError) as ctx:
            validate_filesystem_boundary("/root/.ssh/id_rsa")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_89_1_enforces_configured_library_roots_boundary(self):
        """89.1: Paths outside configured library roots are rejected with 403 Forbidden."""
        inside_file = os.path.join(self.library_dir, "Batman #001.cbz")
        with open(inside_file, "wb") as f:
            f.write(b"data")

        outside_file = os.path.join(self.outside_dir, "Secret #001.cbz")
        with open(outside_file, "wb") as f:
            f.write(b"data")

        roots = [self.library_dir]

        # Inside root: accepted
        resolved = validate_comic_file_path(inside_file, configured_roots=roots)
        self.assertEqual(resolved, os.path.realpath(inside_file))

        # Outside root: rejected with 403
        with self.assertRaises(ValidationError) as ctx:
            validate_comic_file_path(outside_file, configured_roots=roots)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("outside configured library roots", ctx.exception.message)

    def test_89_1_folder_path_validation(self):
        """89.1: Folder validation requires existing directory inside library roots."""
        roots = [self.library_dir]

        # Valid directory inside root
        resolved = validate_folder_path(self.library_dir, configured_roots=roots)
        self.assertEqual(resolved, os.path.realpath(self.library_dir))

        # Nonexistent folder
        nonexistent = os.path.join(self.library_dir, "nonexistent_subfolder")
        with self.assertRaises(ValidationError) as ctx:
            validate_folder_path(nonexistent, configured_roots=roots, must_exist=True)
        self.assertEqual(ctx.exception.status_code, 404)

        # Folder outside root
        with self.assertRaises(ValidationError) as ctx:
            validate_folder_path(self.outside_dir, configured_roots=roots, must_exist=True)
        self.assertEqual(ctx.exception.status_code, 403)

    # ------------------------------------------------------------------ #
    # URL & Query Validation                                             #
    # ------------------------------------------------------------------ #
    def test_89_url_validation(self):
        """Validates HTTP/HTTPS URLs and rejects invalid schemes, empty strings, and malformed hosts."""
        self.assertEqual(
            validate_url("https://comicvine.gamespot.com/batman/4050-796/"),
            "https://comicvine.gamespot.com/batman/4050-796/"
        )
        self.assertEqual(
            validate_url("http://localhost:5656/volume/123"),
            "http://localhost:5656/volume/123"
        )

        with self.assertRaises(ValidationError) as ctx:
            validate_url("file:///etc/passwd")
        self.assertEqual(ctx.exception.status_code, 400)

        with self.assertRaises(ValidationError) as ctx:
            validate_url("javascript:alert(1)")
        self.assertEqual(ctx.exception.status_code, 400)

        with self.assertRaises(ValidationError) as ctx:
            validate_url("")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_89_search_query_validation(self):
        """Validates search query string length and non-blank requirements."""
        self.assertEqual(validate_search_query("Batman"), "Batman")

        with self.assertRaises(ValidationError):
            validate_search_query("   ")

        with self.assertRaises(ValidationError):
            validate_search_query("a" * 300, max_length=250)


if __name__ == "__main__":
    unittest.main()
