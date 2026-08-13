import os
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict, Tuple
from models.comic import Comic
from models.identity import ComicIdentity
from config import Config
from cache.db import CacheManager
from providers.kapowarr import KapowarrProvider
from providers.comicvine import ComicVineProvider
from providers.gcp import GCPProvider

from writers.comicinfo import ComicInfoParser
from pipeline.filename_parser import parse_filename_identity
from pipeline.identity import extract_identity_candidates
from pipeline.confidence import (
    evaluate_confidence,
    evaluate_candidate_pool_decision,
    ConfidenceDecision,
    LEVEL_AUTO_ACCEPT,
    LEVEL_ACCEPT_WITH_WARNING,
    LEVEL_UNRESOLVED
)

from pipeline.existing_metadata import (
    inspect_existing_comicinfo,
    STATE_MISSING,
    STATE_VALID,
    STATE_PARTIAL,
    STATE_MALFORMED,
    STATE_CONFLICTING
)

STATE_METADATA_FOUND = "METADATA_FOUND"
STATE_METADATA_PARTIAL = "METADATA_PARTIAL"
STATE_METADATA_NOT_FOUND = "METADATA_NOT_FOUND"
STATE_METADATA_PROVIDER_ERROR = "METADATA_PROVIDER_ERROR"
STATE_METADATA_INVALID = "METADATA_INVALID"

from dataclasses import dataclass

@dataclass
class MetadataRetrievalResult:
    """Explicit state model for metadata retrieval results (Phase 56)."""
    state: str = STATE_METADATA_NOT_FOUND
    comic: Optional[Comic] = None
    identity: Optional[ComicIdentity] = None
    error_message: str = ""
    is_complete: bool = False
    source: str = ""

def read_existing_comicinfo(cbz_path: str) -> Optional[Comic]:
    """Reads existing ComicInfo.xml from a .cbz archive if present and valid."""
    report = inspect_existing_comicinfo(cbz_path)
    return report.comic

import logging
from observability.retry import classify_provider_error, sanitize_log_url

_logger = logging.getLogger("comicinfo.resolver")

class MetadataResolver:
    """
    Two-Phase Metadata Resolver Architecture (Phase 9 & Phase 56):
    Strictly separates Identity Resolution (resolve_identity) from Metadata Retrieval (retrieve_metadata).
    """

    def __init__(self, config: Optional[Config] = None, cache_mgr: Optional[CacheManager] = None):
        self.config = config
        self.cache_mgr = cache_mgr or (CacheManager(config.cache.db_path) if config and hasattr(config, "cache") else CacheManager())
        self.cache = self.cache_mgr
        self.kapowarr = KapowarrProvider(
            url=self.config.kapowarr.url if self.config and hasattr(self.config, "kapowarr") else "http://localhost:5656",
            api_key=self.config.kapowarr.api_key if self.config and hasattr(self.config, "kapowarr") else ""
        )
        self.comicvine = ComicVineProvider(api_key=self.config.comicvine.api_key if self.config and hasattr(self.config, "comicvine") else "")
        self.gcp = GCPProvider()

    def resolve_identity(self, file_path: str, url_override: str = "") -> Tuple[Optional[ComicIdentity], ConfidenceDecision]:
        """
        Phase 9 Step 1: Resolves and verifies the canonical ComicIdentity from filename, directory hints,
        existing metadata, and remote providers. Evaluates candidate pool via Central Candidate Decision Policy.
        """
        # 1. URL Override (Phase 28)
        if url_override:
            m_cv = re.search(r"4000-(\d+)", url_override)
            if m_cv or "comicvine" in url_override:
                identity = ComicIdentity(
                    provider="ComicVine",
                    issue_id=f"4000-{m_cv.group(1)}" if m_cv else url_override,
                    issue_provider="ComicVine",
                    url=url_override
                )
                return identity, ConfidenceDecision(score=100.0, level=LEVEL_AUTO_ACCEPT, action="UPDATE")
            identity = ComicIdentity(provider="URLOverride", issue_id=url_override, url=url_override)
            return identity, ConfidenceDecision(score=100.0, level=LEVEL_AUTO_ACCEPT, action="UPDATE")

        parsed = parse_filename_identity(file_path)

        # 2. Existing Embedded XML Authority & State Inspection (Phase 45)
        existing_report = inspect_existing_comicinfo(file_path, parsed=parsed)
        existing = existing_report.comic

        # 3. Gather local identity candidates (filename + directory + existing XML)
        local_candidates = extract_identity_candidates(file_path)
        if existing_report.candidate_identity and not any(c.provider == "ExistingXML" for c in local_candidates):
            local_candidates.append(existing_report.candidate_identity)

        # 4. Search Providers for Candidate Identity Signals
        fname = os.path.basename(file_path)
        provider_candidates: List[ComicIdentity] = []

        # Kapowarr
        if self.kapowarr.test_connection():
            try:
                searches = self.kapowarr.search_issue(fname)
                if not searches:
                    _logger.debug("PROVIDER_NOT_FOUND provider=Kapowarr operation=search_issue query=%s", fname)
                for s in searches:
                    if s.get("id"):
                        s_year = int(s.get("year") or s.get("volume_year") or 0) if (s.get("year") or s.get("volume_year")) else 0
                        s_series = s.get("series") or (s.get("title", "").split(" #")[0] if s.get("title") else parsed.series_name)
                        s_pub = s.get("publisher", "") or s.get("pub", "")
                        s_num = str(s.get("issue_number") or s.get("number") or parsed.issue_number)
                        provider_candidates.append(ComicIdentity(
                            provider="Kapowarr",
                            issue_id=str(s["id"]),
                            issue_provider="Kapowarr",
                            series_name=s_series,
                            issue_number=s_num,
                            publication_year=s_year,
                            publisher=s_pub
                        ))
            except Exception as e:
                classify_provider_error(e, provider="Kapowarr", operation="search_issue", query_or_url=fname)
        else:
            _logger.info("PROVIDER_OFFLINE provider=Kapowarr operation=test_connection")

        # ComicVine
        try:
            cv_results = self.comicvine.search_issue(fname)
            if not cv_results:
                _logger.debug("PROVIDER_NOT_FOUND provider=ComicVine operation=search_issue query=%s", fname)
            for r in cv_results:
                if r.get("url"):
                    m_cv = re.search(r"4000-(\d+)", r["url"])
                    r_year = int(r.get("year") or r.get("volume_year") or 0) if (r.get("year") or r.get("volume_year")) else 0
                    r_series = r.get("series") or (r.get("title", "").split(" #")[0] if r.get("title") else parsed.series_name)
                    r_pub = r.get("publisher", "") or r.get("pub", "")
                    r_num = str(r.get("issue_number") or r.get("number") or parsed.issue_number)
                    provider_candidates.append(ComicIdentity(
                        provider="ComicVine",
                        issue_id=f"4000-{m_cv.group(1)}" if m_cv else r["url"],
                        issue_provider="ComicVine",
                        series_name=r_series,
                        issue_number=r_num,
                        publication_year=r_year,
                        publisher=r_pub
                    ))
        except Exception as e:
            classify_provider_error(e, provider="ComicVine", operation="search_issue", query_or_url=fname)

        # GCP (Grand Comics Database)
        if hasattr(self, "gcp") and self.gcp:
            try:
                gcp_results = self.gcp.search_issue(fname)
                if not gcp_results:
                    _logger.debug("PROVIDER_NOT_FOUND provider=GCP operation=search_issue query=%s", fname)
                for g in gcp_results:
                    if g.get("url") or g.get("id"):
                        g_year = int(g.get("year") or g.get("volume_year") or 0) if (g.get("year") or g.get("volume_year")) else 0
                        g_series = g.get("series") or (g.get("title", "").split(" #")[0] if g.get("title") else parsed.series_name)
                        g_pub = g.get("publisher", "") or g.get("pub", "")
                        g_num = str(g.get("issue_number") or g.get("number") or parsed.issue_number)
                        provider_candidates.append(ComicIdentity(
                            provider="GCP",
                            issue_id=str(g.get("id") or g.get("url")),
                            issue_provider="GCP",
                            series_name=g_series,
                            issue_number=g_num,
                            publication_year=g_year,
                            publisher=g_pub
                        ))
            except Exception as e:
                classify_provider_error(e, provider="GCP", operation="search_issue", query_or_url=fname)

        # If no provider candidates and no existing XML, filename alone is not sufficient proof of identity
        has_existing_xml = any(c.provider == "ExistingXML" for c in local_candidates)
        if not provider_candidates and not has_existing_xml:
            return None, ConfidenceDecision(score=0.0, level=LEVEL_UNRESOLVED, action="SKIP")

        all_candidates = local_candidates + provider_candidates
        if not all_candidates:
            empty_cand = ComicIdentity(series_name=parsed.series_name, issue_number=parsed.issue_number)
            return None, ConfidenceDecision(score=0.0, level=LEVEL_UNRESOLVED, action="SKIP")

        # 5. Evaluate Candidate Pool Decision via Central Decision Policy (Phase 44)
        return evaluate_candidate_pool_decision(
            all_candidates,
            parsed,
            min_margin=10.0,
            existing_comic=existing
        )

    def retrieve_metadata_result(self, identity: ComicIdentity, file_path: str = "") -> MetadataRetrievalResult:
        """
        Phase 56: Retrieves full Comic metadata details for a resolved ComicIdentity and produces an explicit state.
        Separates identity resolution from metadata success.
        """
        if not identity:
            return MetadataRetrievalResult(state=STATE_METADATA_NOT_FOUND, is_complete=False)

        comic: Optional[Comic] = None
        error_msg = ""
        is_error = False

        if identity.provider == "ExistingXML":
            if file_path and os.path.exists(file_path) and file_path.lower().endswith(".cbz"):
                comic = read_existing_comicinfo(file_path)
            if comic:
                comic.identity = identity
                comic.metadata_complete = True
                return MetadataRetrievalResult(
                    state=STATE_METADATA_FOUND,
                    comic=comic,
                    identity=identity,
                    is_complete=True,
                    source="ExistingXML"
                )
            return MetadataRetrievalResult(
                state=STATE_METADATA_NOT_FOUND,
                identity=identity,
                is_complete=False,
                source="ExistingXML"
            )

        elif identity.provider == "Kapowarr" and identity.issue_id:
            try:
                comic = self.kapowarr.lookup_issue(identity.issue_id)
            except Exception as e:
                classify_provider_error(e, provider="Kapowarr", operation="lookup_issue", query_or_url=str(identity.issue_id))
                error_msg = str(e)
                is_error = True

        elif identity.provider == "ComicVine" and identity.issue_id:
            cv_url = f"https://comicvine.gamespot.com/issue/{identity.issue_id}/" if not identity.issue_id.startswith("http") else identity.issue_id
            try:
                comic = self.comicvine.lookup_issue(cv_url)
            except Exception as e:
                classify_provider_error(e, provider="ComicVine", operation="lookup_issue", query_or_url=cv_url)
                error_msg = str(e)
                is_error = True

        elif identity.provider == "GCP" and identity.issue_id:
            try:
                comic = self.gcp.lookup_issue(identity.issue_id)
            except Exception as e:
                classify_provider_error(e, provider="GCP", operation="lookup_issue", query_or_url=str(identity.issue_id))
                error_msg = str(e)
                is_error = True

        if is_error:
            return MetadataRetrievalResult(
                state=STATE_METADATA_PROVIDER_ERROR,
                identity=identity,
                error_message=error_msg,
                is_complete=False,
                source=identity.provider or "Provider"
            )

        if not comic:
            return MetadataRetrievalResult(
                state=STATE_METADATA_NOT_FOUND,
                identity=identity,
                is_complete=False,
                source=identity.provider or "Provider"
            )

        if not comic.series and not comic.title:
            return MetadataRetrievalResult(
                state=STATE_METADATA_INVALID,
                identity=identity,
                error_message="Retrieved comic payload missing series name and title",
                is_complete=False,
                source=identity.provider or "Provider"
            )

        comic.identity = identity
        comic.metadata_complete = True
        return MetadataRetrievalResult(
            state=STATE_METADATA_FOUND,
            comic=comic,
            identity=identity,
            is_complete=True,
            source=identity.provider or "Provider"
        )

    def retrieve_metadata(self, identity: ComicIdentity, file_path: str = "") -> Optional[Comic]:
        """
        Phase 9 Step 2 & Phase 56: Retrieves full Comic metadata details for a resolved ComicIdentity.
        Returns Comic if metadata retrieval succeeded with valid complete data, else None.
        """
        res = self.retrieve_metadata_result(identity, file_path=file_path)
        if res.state == STATE_METADATA_FOUND:
            return res.comic
        return None

    def resolve_file_metadata(self, file_path: str, url_override: str = "", force_overwrite: bool = False) -> Tuple[Optional[Comic], str]:
        """
        Pipeline entry point chaining resolve_identity() and retrieve_metadata(identity).
        Returns (Comic_object, provider_name_used).
        """
        identity, decision = self.resolve_identity(file_path, url_override=url_override)
        if identity and decision.action != "SKIP":
            meta_res = self.retrieve_metadata_result(identity, file_path=file_path)
            if meta_res.state == STATE_METADATA_FOUND and meta_res.comic:
                return meta_res.comic, identity.provider or "Resolver"

        return None, "None"
