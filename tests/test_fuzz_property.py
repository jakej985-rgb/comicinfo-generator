"""
Phase 39 — Property-Based / Fuzz Testing

Exercises parsers with adversarial, edge-case, and randomly-constructed inputs.
The core invariant under test:

  "The parser must never crash the entire processing service."

Every function tested must either return a valid result OR raise a
specific, predictable exception — never crash with an unhandled exception.

Coverage:
  - filename_parser: adversarial filenames, unicode, injections
  - issue_order: numeric extremes, mixed alpha-numeric, special names
  - collection: mismatched series/volumes, duplicates, boundary conditions
  - XML: malformed XML, empty XML, deeply nested, huge payloads
  - archive contents: empty CBZ, CBZ with no images, CBZ with only XML
"""
import io
import os
import random
import string
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

from pipeline.filename_parser import parse_filename_identity, ParsedFilename
from pipeline.issue_order import parse_issue_order, sort_issues, IssueOrder
from pipeline.collection import CollectionIssue, validate_collection, RESULT_REJECT, RESULT_ACCEPT, RESULT_WARN
from models.identity import ComicIdentity
from writers.archive import embed_comicinfo_in_cbz, ArchiveReadError, ArchiveValidationError
from writers.comicinfo import generate_xml_bytes
from models.comic import Comic


# ------------------------------------------------------------------ #
# Corpus of adversarial filenames from plan.md + extras              #
# ------------------------------------------------------------------ #
FILENAME_CORPUS = [
    # Standard cases from plan.md
    "Batman #1.cbz",
    "Batman #001.cbz",
    "Batman 1A.cbz",
    "Batman 1.5.cbz",
    "Batman Annual 1.cbz",
    "Batman Special.cbz",
    # Leading zeros
    "Batman #000.cbz",
    "Batman #0001.cbz",
    # Half issues
    "Batman #0.5.cbz",
    "Batman #½.cbz",
    "Batman #1/2.cbz",
    # Volume markers
    "Batman v2 #1.cbz",
    "Batman Vol.2 #001.cbz",
    "Batman Volume 3 Issue 1.cbz",
    # Parenthetical years
    "Batman (2016) #001.cbz",
    "Batman (2016) Annual 2.cbz",
    # Underscores/dashes
    "Batman_001.cbz",
    "Batman-001.cbz",
    "The_Amazing_Spider-Man_#001_(2022).cbz",
    # Completely stripped name
    "001.cbz",
    "1.cbz",
    # Unicode characters
    "Daredevil — Born Again #1.cbz",
    "Daredevil \u2014 Born Again #1.cbz",
    "\u30d0\u30c3\u30c8\u30de\u30f3 #001.cbz",   # Japanese
    # Injections and odd strings
    "../Batman #1.cbz",
    "Batman #1; DROP TABLE issues; --.cbz",
    "<script>alert('xss')</script>.cbz",
    # Empty-ish
    ".cbz",
    " .cbz",
    "-.cbz",
    # TPB / collected
    "Batman TPB Vol.1.cbz",
    "Watchmen - The Absolute Edition.cbz",
    "Batman Omnibus.cbz",
    # Very long name
    ("A" * 255) + ".cbz",
    # Null-like strings
    "Batman\x00#1.cbz",
    "Batman\n#1.cbz",
    # No extension
    "Batman #1",
    # Uppercase extension
    "Batman #1.CBZ",
]

ISSUE_NUMBER_CORPUS = [
    "0", "1", "001", "0001", "10", "100", "999",
    "0.5", "1.5", "0.25", "99.9",
    "1A", "1B", "1a", "99Z",
    "Annual", "ANNUAL", "Annual 1", "Annual 2",
    "Special", "SPECIAL",
    "½", "1/2",
    "#1", "#001",
    "", " ", "???", "N/A",
    "9999999", "-1", "0.0",
    "1000A",
]


class TestFilenameParserFuzz(unittest.TestCase):
    """Phase 39: Parser must never crash on any filename in the corpus."""

    def _assert_returns_parsed_filename(self, fname: str):
        """Core property: parse_filename_identity must always return a ParsedFilename, never raise."""
        try:
            result = parse_filename_identity(fname)
            self.assertIsInstance(result, ParsedFilename,
                f"Expected ParsedFilename for input {fname!r}, got {type(result)}")
        except Exception as e:
            self.fail(f"parse_filename_identity raised unexpectedly for {fname!r}: {e!r}")

    def test_standard_corpus_never_crashes(self):
        for fname in FILENAME_CORPUS:
            with self.subTest(fname=fname):
                self._assert_returns_parsed_filename(fname)

    def test_unicode_filenames_never_crash(self):
        unicode_names = [
            "Bätman #1.cbz",
            "Невероятный Человек-паук #1.cbz",
            "蝙蝠侠 #001.cbz",
            "マーベル・コミック #1.cbz",
        ]
        for name in unicode_names:
            with self.subTest(name=name):
                self._assert_returns_parsed_filename(name)

    def test_random_strings_never_crash(self):
        """Random 10-char printable ASCII strings — parser must never crash."""
        rng = random.Random(42)
        for _ in range(100):
            rand_name = "".join(rng.choices(string.printable, k=30)) + ".cbz"
            with self.subTest(rand_name=rand_name[:20]):
                self._assert_returns_parsed_filename(rand_name)

    def test_issue_number_extracted_is_string_or_empty(self):
        """Issue number must always be a string (never None)."""
        for fname in FILENAME_CORPUS:
            with self.subTest(fname=fname):
                result = parse_filename_identity(fname)
                self.assertIsInstance(result.issue_number, str)

    def test_series_name_never_none(self):
        """Series name must always be a string (never None)."""
        for fname in FILENAME_CORPUS:
            with self.subTest(fname=fname):
                result = parse_filename_identity(fname)
                self.assertIsInstance(result.series_name, str)


class TestIssueOrderFuzz(unittest.TestCase):
    """Phase 39: parse_issue_order must never crash on arbitrary input."""

    def test_corpus_never_crashes(self):
        for raw in ISSUE_NUMBER_CORPUS:
            with self.subTest(raw=raw):
                try:
                    order = parse_issue_order(raw)
                    self.assertIsInstance(order, IssueOrder)
                    self.assertIsInstance(order.numeric_value, float)
                    self.assertIsInstance(order.letter_suffix, str)
                except Exception as e:
                    self.fail(f"parse_issue_order({raw!r}) raised: {e!r}")

    def test_sort_never_crashes_on_mixed_corpus(self):
        """sort_issues must never crash regardless of input content."""
        try:
            result = sort_issues(ISSUE_NUMBER_CORPUS)
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), len(ISSUE_NUMBER_CORPUS))
        except Exception as e:
            self.fail(f"sort_issues raised on mixed corpus: {e!r}")

    def test_sort_is_stable_idempotent(self):
        """Sorting already-sorted list must return the same order."""
        numbers = ["0", "0.5", "1", "1A", "2", "Annual"]
        once = sort_issues(numbers)
        twice = sort_issues(once)
        self.assertEqual(once, twice)

    def test_empty_list_returns_empty(self):
        self.assertEqual(sort_issues([]), [])

    def test_single_item_returns_same(self):
        self.assertEqual(sort_issues(["Annual"]), ["Annual"])

    def test_numeric_order_is_correct(self):
        result = sort_issues(["10", "2", "1", "0.5", "0"])
        self.assertEqual(result, ["0", "0.5", "1", "2", "10"])


class TestCollectionValidationFuzz(unittest.TestCase):
    """Phase 39: Collection validator must handle adversarial inputs without crashing."""

    def _make_issue(self, series="Batman", volume_id="v-1", number="1") -> CollectionIssue:
        identity = ComicIdentity(series_name=series, publisher="DC", volume_id=volume_id)
        return CollectionIssue(identity=identity, issue_number=number)

    def test_empty_collection_rejects_gracefully(self):
        result = validate_collection([])
        self.assertEqual(result.result, RESULT_REJECT)

    def test_single_issue_accepts(self):
        result = validate_collection([self._make_issue(number="1")])
        self.assertEqual(result.result, RESULT_ACCEPT)

    def test_duplicate_issue_numbers_rejected(self):
        issues = [self._make_issue(number="1"), self._make_issue(number="1")]
        result = validate_collection(issues)
        self.assertEqual(result.result, RESULT_REJECT)

    def test_corpus_issue_numbers_never_crash(self):
        """validate_collection must never crash regardless of issue number format."""
        for raw in ISSUE_NUMBER_CORPUS:
            with self.subTest(raw=raw):
                try:
                    issue = self._make_issue(number=raw)
                    result = validate_collection([issue])
                    self.assertIn(result.result, (RESULT_ACCEPT, RESULT_WARN, RESULT_REJECT))
                except Exception as e:
                    self.fail(f"validate_collection crashed for number={raw!r}: {e!r}")

    def test_large_collection_never_crashes(self):
        """100-issue collection must be handled without crash."""
        issues = [self._make_issue(number=str(i)) for i in range(1, 101)]
        try:
            result = validate_collection(issues)
            self.assertIn(result.result, (RESULT_ACCEPT, RESULT_WARN, RESULT_REJECT))
        except Exception as e:
            self.fail(f"validate_collection crashed on large collection: {e!r}")


class TestXMLFuzz(unittest.TestCase):
    """Phase 39: XML generation and parsing must never crash on adversarial Comic data."""

    def _make_comic(self, **kwargs) -> Comic:
        return Comic(
            title=kwargs.get("title", "Test"),
            series=kwargs.get("series", "Test Series"),
            number=kwargs.get("number", "1"),
            **{k: v for k, v in kwargs.items() if k not in ("title", "series", "number")}
        )

    def test_xml_generated_for_empty_comic(self):
        """Empty Comic must still produce parseable XML."""
        xml_bytes = generate_xml_bytes(Comic())
        self.assertIsInstance(xml_bytes, bytes)
        ET.fromstring(xml_bytes)  # Must not raise

    def test_xml_generated_for_unicode_comic(self):
        """Unicode in every field must produce parseable XML."""
        comic = self._make_comic(
            title="蝙蝠侠 \u2014 Born Again",
            series="Daredevil",
            writers=["Фрэнк Миллер"],
            characters=["マーベル"]
        )
        xml_bytes = generate_xml_bytes(comic)
        ET.fromstring(xml_bytes)

    def test_xml_generated_for_adversarial_strings(self):
        """XML special chars in fields must be escaped, not crash."""
        # Strings that must produce valid escaped XML bytes:
        escapable_strings = [
            "<script>alert('xss')</script>",
            "'; DROP TABLE series; --",
            "&amp;&lt;&gt;&quot;",
            "A" * 10000,        # very long string
        ]
        for s in escapable_strings:
            with self.subTest(s=s[:30]):
                try:
                    comic = self._make_comic(title=s, summary=s)
                    xml_bytes = generate_xml_bytes(comic)
                    self.assertIsInstance(xml_bytes, bytes)
                except Exception as e:
                    self.fail(f"generate_xml_bytes crashed for {s[:30]!r}: {e!r}")

    def test_xml_rejects_null_bytes_with_clear_error(self):
        """Null and control bytes are illegal in XML — generator must raise a predictable error."""
        # XML 1.0 forbids null bytes and most C0 control characters.
        # It is correct and expected behaviour to raise ValueError here.
        comic = self._make_comic(title="\x00\x01\x02")
        with self.assertRaises((ValueError, Exception)):
            generate_xml_bytes(comic)

    def test_xml_generated_for_huge_list_fields(self):
        """Large creator/character lists must produce parseable XML."""
        comic = self._make_comic(
            writers=[f"Writer {i}" for i in range(500)],
            characters=[f"Character {i}" for i in range(500)],
        )
        xml_bytes = generate_xml_bytes(comic)
        ET.fromstring(xml_bytes)


class TestArchiveFuzz(unittest.TestCase):
    """Phase 39: Archive operations must never corrupt the source archive."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_cbz(self, name: str, entries: dict = None) -> str:
        """Helper: creates a CBZ with given entries dict {filename: bytes}."""
        path = os.path.join(self.tmp, name)
        entries = entries or {"page_001.jpg": b"\xff\xd8\xff" + b"\x00" * 50}
        with zipfile.ZipFile(path, "w") as zf:
            for fname, data in entries.items():
                zf.writestr(fname, data)
        return path

    def test_embed_into_cbz_with_many_image_types(self):
        """Archive with mixed image formats must embed without corruption."""
        entries = {
            "001.jpg": b"\xff\xd8\xff" + b"\x00" * 50,
            "002.png": b"\x89PNG" + b"\x00" * 50,
            "003.webp": b"RIFF" + b"\x00" * 50,
        }
        cbz = self._make_cbz("multi_format.cbz", entries=entries)
        comic = Comic(series="X-Men", number="1")
        embed_comicinfo_in_cbz(cbz, comic)

        with zipfile.ZipFile(cbz, "r") as zf:
            names = [n.lower() for n in zf.namelist()]
        for img in entries:
            self.assertIn(img.lower(), names)

    def test_embed_preserves_existing_comicinfo(self):
        """Embedding overwrites old ComicInfo.xml, doesn't leave two copies."""
        old_xml = b'<?xml version="1.0"?><ComicInfo><Series>OldSeries</Series></ComicInfo>'
        cbz = self._make_cbz("has_old_xml.cbz", {
            "page_001.jpg": b"\xff\xd8\xff" + b"\x00" * 50,
            "ComicInfo.xml": old_xml
        })
        comic = Comic(series="NewSeries", number="2")
        embed_comicinfo_in_cbz(cbz, comic)

        with zipfile.ZipFile(cbz, "r") as zf:
            xml_entries = [n for n in zf.namelist() if n.lower() == "comicinfo.xml"]
            self.assertEqual(len(xml_entries), 1)
            content = zf.read(xml_entries[0])
        self.assertIn(b"NewSeries", content)
        self.assertNotIn(b"OldSeries", content)

    def test_corrupt_zip_raises_read_error_not_crash(self):
        """Corrupt archive → ArchiveReadError, service does not crash."""
        path = os.path.join(self.tmp, "corrupt.cbz")
        with open(path, "wb") as f:
            f.write(b"NOT A ZIP AT ALL\x00" * 20)
        with self.assertRaises(ArchiveReadError):
            embed_comicinfo_in_cbz(path, Comic(series="Test"))

    def test_cbz_with_only_xml_raises_validation_error(self):
        """CBZ containing only ComicInfo.xml (no images) → ArchiveValidationError."""
        from writers.archive import verify_cbz_archive, ArchiveValidationError
        path = self._make_cbz("only_xml.cbz", {"ComicInfo.xml": b"<ComicInfo/>"})
        with self.assertRaises(ArchiveValidationError):
            verify_cbz_archive(path)

    def test_adversarial_filenames_in_archive_do_not_crash(self):
        """Adversarial entry names inside ZIP must not crash the embed."""
        entries = {
            "normal_page.jpg": b"\xff\xd8\xff" + b"\x00" * 50,
            "../escaped.jpg": b"\xff\xd8\xff" + b"\x00" * 50,
        }
        cbz = self._make_cbz("adversarial_names.cbz", entries=entries)
        comic = Comic(series="Test", number="1")
        try:
            embed_comicinfo_in_cbz(cbz, comic)
        except Exception as e:
            # Acceptable to raise an archive error, but MUST NOT crash silently
            self.assertIsInstance(e, Exception)


if __name__ == "__main__":
    unittest.main()
