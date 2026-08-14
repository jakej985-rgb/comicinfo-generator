"""
tests/test_production_observability.py — Phase 92: Production Observability Tests

Verifies:
1. Structured log output format for successful job execution.
2. Fallback provider log structure.
3. Failure / rate limiting log structure with retryable classification.
4. Guaranteed sanitization and masking of API keys / secrets.
"""

import unittest
from observability.logging import ProductionJobLog, log_production_job, sanitize_log_text


class TestProductionObservability(unittest.TestCase):

    def test_92_1_standard_job_structured_log(self):
        """92.1: Emits the exact expected multi-section structured log for standard job completion."""
        job = ProductionJobLog(
            filename="/path/to/Batman #001.cbz",
            series="Batman",
            issue="1",
            year=2016,
            provider="Kapowarr",
            fallback=False,
            confidence=96.0,
            action="UPDATE ComicInfo.xml",
            archive_verified=True,
            result="COMPLETED"
        )
        formatted = job.format()

        expected = (
            "JOB START\n"
            "file=Batman #001.cbz\n\n"
            "IDENTITY\n"
            "series=Batman\n"
            "issue=1\n"
            "year=2016\n\n"
            "RESOLUTION\n"
            "provider=Kapowarr\n"
            "fallback=false\n"
            "confidence=96\n\n"
            "ACTION\n"
            "UPDATE ComicInfo.xml\n\n"
            "WRITE\n"
            "archive verified=true\n\n"
            "RESULT\n"
            "COMPLETED"
        )
        self.assertEqual(formatted, expected)

    def test_92_2_fallback_resolution_structured_log(self):
        """92.2: Emits structured log with multiple provider outcomes and fallback=true."""
        job = ProductionJobLog(
            filename="Batman #001.cbz",
            series="Batman",
            issue="1",
            year=2016,
            provider_results={
                "Kapowarr": "NOT_FOUND",
                "ComicVine": "SUCCESS"
            },
            fallback=True,
            action="UPDATE ComicInfo.xml",
            archive_verified=True,
            result="COMPLETED"
        )
        formatted = job.format()

        self.assertIn("RESOLUTION\nKapowarr=NOT_FOUND\nComicVine=SUCCESS\nfallback=true", formatted)
        self.assertIn("RESULT\nCOMPLETED", formatted)

    def test_92_3_failure_resolution_structured_log(self):
        """92.3: Emits structured log with provider failure and retryable=true."""
        job = ProductionJobLog(
            filename="Batman #001.cbz",
            series="Batman",
            issue="1",
            year=2016,
            provider_results={
                "ComicVine": "RATE_LIMITED"
            },
            retryable=True,
            action="SKIP",
            result="FAILED",
            error_message="HTTP 429 Rate Limit"
        )
        formatted = job.format()

        self.assertIn("RESOLUTION\nComicVine=RATE_LIMITED\nfallback=false\nretryable=true", formatted)
        self.assertIn("RESULT\nFAILED\nerror=HTTP 429 Rate Limit", formatted)

    def test_92_4_api_key_masking(self):
        """92.4: Ensures API keys, tokens, and secrets are never logged in plaintext."""
        raw_log = "JOB START file=Batman.cbz api_key=ab12cd34ef56gh78 https://comicvine.gamespot.com/api/?api_key=secretkey123"
        sanitized = sanitize_log_text(raw_log)

        self.assertNotIn("ab12cd34ef56gh78", sanitized)
        self.assertNotIn("secretkey123", sanitized)
        self.assertIn("api_key=***", sanitized)


if __name__ == "__main__":
    unittest.main()
