"""
pipeline/dry_run.py — Phase 50: True Dry-Run Isolation

Provides DryRunContext and dry-run evaluation workflows that guarantee 100%
side-effect free execution. In dry-run mode:
- No archives are modified.
- No temporary files are created.
- No disk cache or job databases are created or altered.
- No file hashes are recorded to persistent storage.
"""
import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from unittest.mock import patch

from config import Config, load_config
from models.comic import Comic
from models.identity import ComicIdentity
from cache.db import CacheManager
from cache.jobs import JobStore
from pipeline.resolver import MetadataResolver
from pipeline.filename_parser import parse_filename_identity
from pipeline.confidence import ConfidenceDecision


@dataclass
class DryRunResult:
    file_path: str
    filename: str
    parsed_series: str
    parsed_issue: str
    parsed_year: Optional[int]
    candidate: Optional[ComicIdentity]
    decision: ConfidenceDecision
    proposed_comic: Optional[Comic]
    fields_to_change: List[str] = field(default_factory=list)
    metadata_state: str = "METADATA_NOT_FOUND"


class DryRunContext:
    """
    Phase 50 Context Manager:
    Enforces true side-effect isolation during dry-run execution by:
    1. Redirecting SQLite caching & job tracking to isolated in-memory databases.
    2. Intercepting archive embedding and conversion routines to prevent disk mutations.
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or load_config()
        self.in_memory_cache = CacheManager(":memory:")
        self.in_memory_job_store = JobStore(":memory:")
        self.resolver = MetadataResolver(self.config, cache_mgr=self.in_memory_cache)
        self.results: List[DryRunResult] = []
        self._patches = []

    def __enter__(self):
        # Patch archive write operations to be strictly side-effect free
        p_embed = patch("writers.archive.embed_comicinfo_in_cbz", side_effect=self._mock_embed)
        p_track = patch("services.processing.embed_and_track", side_effect=self._mock_embed_and_track)
        
        self._patches = [p_embed, p_track]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for p in self._patches:
            p.stop()
        self._patches.clear()

    def _mock_embed(self, archive_path: str, comic: Comic, overwrite: bool = True) -> str:
        # Return path without modifying archive or writing temp files
        return archive_path

    def _mock_embed_and_track(self, file_path: str, comic: Comic, cache_mgr=None, **kwargs):
        # Simulated embedding tracking
        return True, "DRY_RUN_PREVIEW"

    def evaluate_file(self, file_path: str) -> DryRunResult:
        """Evaluates a single comic archive without modifying disk state."""
        abs_path = os.path.abspath(file_path)
        filename = os.path.basename(abs_path)
        parsed = parse_filename_identity(abs_path)

        identity, decision = self.resolver.resolve_identity(abs_path)
        comic = None
        fields_to_change = []
        metadata_state = "METADATA_NOT_FOUND"

        if identity and decision.action != "SKIP":
            meta_res = self.resolver.retrieve_metadata_result(identity, file_path=abs_path)
            metadata_state = meta_res.state
            if meta_res.state == "METADATA_FOUND" and meta_res.comic:
                comic = meta_res.comic
                if comic.title: fields_to_change.append("Title")
                if comic.series: fields_to_change.append("Series")
                if comic.number: fields_to_change.append("Number")
                if comic.publisher: fields_to_change.append("Publisher")
                if comic.year: fields_to_change.append("Year")
                if comic.writers: fields_to_change.append("Writer")
                if comic.pencillers: fields_to_change.append("Penciller")
                if comic.characters: fields_to_change.append("Characters")

        result = DryRunResult(
            file_path=abs_path,
            filename=filename,
            parsed_series=parsed.series_name,
            parsed_issue=parsed.issue_number,
            parsed_year=parsed.year,
            candidate=identity,
            decision=decision,
            proposed_comic=comic,
            fields_to_change=fields_to_change,
            metadata_state=metadata_state
        )
        self.results.append(result)
        return result

    def evaluate_target(self, target_path: str) -> List[DryRunResult]:
        """Evaluates a single file or an entire directory in dry-run mode."""
        abs_target = os.path.abspath(target_path)
        if os.path.isfile(abs_target):
            files = [abs_target]
        elif os.path.isdir(abs_target):
            files = [
                os.path.join(abs_target, f)
                for f in sorted(os.listdir(abs_target))
                if f.lower().endswith((".cbz", ".cbr"))
            ]
        else:
            return []

        return [self.evaluate_file(f) for f in files]
