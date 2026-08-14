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

from dataclasses import dataclass, field

@dataclass
class ProviderOperationResult:
    """Explicit state model for provider operation execution (Phase 57)."""
    provider: str
    operation: str
    status: str  # SUCCESS, NOT_FOUND, OFFLINE, TIMEOUT, RATE_LIMITED, SERVER_ERROR, AUTH_FAILED, PARSE_ERROR, INVALID_RESPONSE
    error_type: str = ""
    retryable: bool = False
    message: str = ""

@dataclass
class MetadataRetrievalResult:
    """Explicit state model for metadata retrieval results (Phase 56)."""
    state: str = STATE_METADATA_NOT_FOUND
    comic: Optional[Comic] = None
    identity: Optional[ComicIdentity] = None
    error_message: str = ""
    is_complete: bool = False
    source: str = ""

@dataclass
class ResolutionResult:
    """Full comprehensive result of identity and metadata resolution (Phase 57 & Phase 82)."""
    identity: Optional[ComicIdentity] = None
    confidence: float = 0.0
    decision: Optional[ConfidenceDecision] = None
    provider_results: Dict[str, ProviderOperationResult] = field(default_factory=dict)
    conflicts: List[str] = field(default_factory=list)
    metadata_result: Optional[MetadataRetrievalResult] = None
    comic: Optional[Comic] = None
    resolution_source: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""

def read_existing_comicinfo(cbz_path: str) -> Optional[Comic]:
    """Reads existing ComicInfo.xml from a .cbz archive if present and valid."""
    report = inspect_existing_comicinfo(cbz_path)
    return report.comic

import logging
from observability.retry import classify_provider_error, sanitize_log_url

_logger = logging.getLogger("comicinfo.resolver")

class MetadataResolver:
    """
    Two-Phase Metadata Resolver Architecture (Phase 9 & Phase 56 & Phase 57):
    Strictly separates Identity Resolution (resolve_identity) from Metadata Retrieval (retrieve_metadata).
    Preserves provider operation states across the entire resolution pipeline.
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        cache_mgr: Optional[CacheManager] = None,
        kapowarr: Optional[KapowarrProvider] = None,
        comicvine: Optional[ComicVineProvider] = None,
        gcp: Optional[GCPProvider] = None
    ):
        self.config = config
        self.cache_mgr = cache_mgr or (CacheManager(config.cache.db_path) if config and hasattr(config, "cache") else CacheManager())
        self.cache = self.cache_mgr
        self.kapowarr = kapowarr or KapowarrProvider(
            url=self.config.kapowarr.url if self.config and hasattr(self.config, "kapowarr") else "http://localhost:5656",
            api_key=self.config.kapowarr.api_key if self.config and hasattr(self.config, "kapowarr") else ""
        )
        self.comicvine = comicvine or ComicVineProvider(api_key=self.config.comicvine.api_key if self.config and hasattr(self.config, "comicvine") else "")
        self.gcp = gcp or GCPProvider()

    def resolve_identity(self, file_path: str, url_override: str = "") -> Tuple[Optional[ComicIdentity], ConfidenceDecision]:
        """
        Phase 82: Authoritative Resolution Order:
        1. Explicit URL / explicit provider ID
        2. Existing ComicInfo.xml (validated complete, consistent, trusted)
        3. Persistent cache lookup (before calling network providers)
        4. Local filename / folder identity
        5. Kapowarr-First (if configured and reachable)
        6. ComicVine Fallback (only if Kapowarr fails or yields low confidence)
        7. GCD Fallback (only if previous stages fail)
        8. REVIEW / unresolved
        """
        provider_results: Dict[str, ProviderOperationResult] = {}
        fname = os.path.basename(file_path) if file_path else ""

        # --- Stage 1: Explicit URL / explicit provider ID (Phase 28) ---
        if url_override:
            m_cv = re.search(r"4000-(\d+)", url_override)
            if m_cv or "comicvine" in url_override:
                identity = ComicIdentity(
                    provider="ComicVine",
                    issue_id=f"4000-{m_cv.group(1)}" if m_cv else url_override,
                    issue_provider="ComicVine",
                    resolution_source="url_override",
                    fallback_used=False
                )
                provider_results["ComicVine"] = ProviderOperationResult(provider="ComicVine", operation="url_override", status="SUCCESS")
                dec = ConfidenceDecision(
                    score=100.0, level=LEVEL_AUTO_ACCEPT, action="UPDATE",
                    provider_results=provider_results, resolution_source="url_override", fallback_used=False
                )
                return identity, dec
            identity = ComicIdentity(
                provider="URLOverride", issue_id=url_override,
                resolution_source="url_override", fallback_used=False
            )
            provider_results["URLOverride"] = ProviderOperationResult(provider="URLOverride", operation="url_override", status="SUCCESS")
            dec = ConfidenceDecision(
                score=100.0, level=LEVEL_AUTO_ACCEPT, action="UPDATE",
                provider_results=provider_results, resolution_source="url_override", fallback_used=False
            )
            return identity, dec

        parsed = parse_filename_identity(file_path) if file_path else None
        if not parsed:
            dec = ConfidenceDecision(score=0.0, level=LEVEL_UNRESOLVED, action="SKIP", provider_results=provider_results)
            return None, dec

        # --- Stage 2: Existing ComicInfo.xml validation (Phase 82.2) ---
        existing_report = inspect_existing_comicinfo(file_path, parsed=parsed)
        existing = existing_report.comic

        # If existing ComicInfo contains verified provider ID (trusted provenance) and matches parsed filename
        if existing_report.state == STATE_VALID and existing_report.candidate_identity:
            cand = existing_report.candidate_identity
            if cand.issue_id:
                cand_dec = evaluate_confidence(cand, parsed)
                if not cand_dec.has_critical_conflict and cand_dec.score >= 80.0:
                    cand.resolution_source = "existing_comicinfo"
                    cand.fallback_used = False
                    cand_dec.resolution_source = "existing_comicinfo"
                    cand_dec.fallback_used = False
                    cand_dec.provider_results = provider_results
                    return cand, cand_dec

        # --- Stage 3: Persistent Cache Lookup before Network (Phase 82.3) ---
        if self.cache and parsed.series_name:
            query_key = fname.lower()
            cached_search = self.cache.get_cached_search("Kapowarr", "issue", query_key) or \
                            self.cache.get_cached_search("ComicVine", "issue", query_key)
            if cached_search and isinstance(cached_search, list):
                cache_candidates = []
                for item in cached_search:
                    if isinstance(item, dict) and item.get("series_name"):
                        cache_candidates.append(ComicIdentity(
                            provider=item.get("provider", "Cache"),
                            issue_id=str(item.get("issue_id", "")),
                            series_name=item.get("series_name", ""),
                            issue_number=str(item.get("issue_number", "")),
                            publication_year=int(item.get("publication_year", 0)),
                            publisher=item.get("publisher", ""),
                            resolution_source="persistent_cache",
                            fallback_used=False
                        ))
                if cache_candidates:
                    best_cached, cached_dec = evaluate_candidate_pool_decision(
                        cache_candidates, parsed, min_margin=10.0, existing_comic=existing
                    )
                    if best_cached and cached_dec.score >= 80.0 and not cached_dec.has_critical_conflict:
                        best_cached.resolution_source = "persistent_cache"
                        best_cached.fallback_used = False
                        cached_dec.resolution_source = "persistent_cache"
                        cached_dec.fallback_used = False
                        cached_dec.provider_results = provider_results
                        return best_cached, cached_dec

        # --- Stage 4: Local filename & folder identity ---
        local_candidates = extract_identity_candidates(file_path)
        if existing_report.candidate_identity and not any(c.provider == "ExistingXML" for c in local_candidates):
            local_candidates.append(existing_report.candidate_identity)

        # --- Stage 5: Kapowarr-First Resolution (Phase 82.4) ---
        kapowarr_candidates: List[ComicIdentity] = []
        kapowarr_fail_reason = ""

        if self.kapowarr.test_connection():
            try:
                searches = self.kapowarr.search_issue(fname)
                if searches:
                    provider_results["Kapowarr"] = ProviderOperationResult(provider="Kapowarr", operation="search_issue", status="SUCCESS")
                    for s in searches:
                        if isinstance(s, ComicIdentity):
                            s.resolution_source = "kapowarr"
                            s.fallback_used = False
                            kapowarr_candidates.append(s)
                        elif isinstance(s, dict) and s.get("id"):
                            s_year = int(s.get("year") or s.get("volume_year") or 0) if (s.get("year") or s.get("volume_year")) else 0
                            s_series = s.get("series") or (s.get("title", "").split(" #")[0] if s.get("title") else parsed.series_name)
                            s_pub = s.get("publisher", "") or s.get("pub", "")
                            s_num = str(s.get("issue_number") or s.get("number") or parsed.issue_number)
                            kapowarr_candidates.append(ComicIdentity(
                                provider="Kapowarr",
                                issue_id=str(s["id"]),
                                issue_provider="Kapowarr",
                                series_name=s_series,
                                issue_number=s_num,
                                publication_year=s_year,
                                publisher=s_pub,
                                resolution_source="kapowarr",
                                fallback_used=False
                            ))
                else:
                    _logger.debug("PROVIDER_NOT_FOUND provider=Kapowarr operation=search_issue query=%s", fname)
                    provider_results["Kapowarr"] = ProviderOperationResult(provider="Kapowarr", operation="search_issue", status="NOT_FOUND")
                    kapowarr_fail_reason = "Kapowarr returned no match"
            except Exception as e:
                state, retryable = classify_provider_error(e, provider="Kapowarr", operation="search_issue", query_or_url=fname)
                provider_results["Kapowarr"] = ProviderOperationResult(
                    provider="Kapowarr",
                    operation="search_issue",
                    status=state,
                    error_type=type(e).__name__,
                    retryable=retryable,
                    message=str(e)
                )
                kapowarr_fail_reason = f"Kapowarr error: {e}"
        else:
            _logger.info("PROVIDER_OFFLINE provider=Kapowarr operation=test_connection")
            provider_results["Kapowarr"] = ProviderOperationResult(
                provider="Kapowarr",
                operation="test_connection",
                status="OFFLINE",
                retryable=True,
                message="Kapowarr service is offline or unreachable"
            )
            kapowarr_fail_reason = "Kapowarr offline or unreachable"

        # Check if Kapowarr resolved it with high confidence (>= 70)
        if kapowarr_candidates:
            pool = local_candidates + kapowarr_candidates
            best_kap, kap_dec = evaluate_candidate_pool_decision(pool, parsed, min_margin=10.0, existing_comic=existing)
            if best_kap and kap_dec.score >= 70.0 and not kap_dec.has_critical_conflict:
                best_kap.resolution_source = "kapowarr"
                best_kap.fallback_used = False
                kap_dec.resolution_source = "kapowarr"
                kap_dec.fallback_used = False
                kap_dec.provider_results = provider_results
                return best_kap, kap_dec
            else:
                kapowarr_fail_reason = f"Kapowarr candidate confidence {kap_dec.score:.1f} < 70"

        # --- Stage 6: ComicVine Fallback (Phase 82.5 — Only if Kapowarr failed or low confidence) ---
        cv_candidates: List[ComicIdentity] = []
        cv_fail_reason = ""
        fallback_reason = kapowarr_fail_reason or "Kapowarr unavailable or insufficient"

        try:
            cv_results = self.comicvine.search_issue(fname)
            if cv_results:
                provider_results["ComicVine"] = ProviderOperationResult(provider="ComicVine", operation="search_issue", status="SUCCESS")
                for r in cv_results:
                    if isinstance(r, ComicIdentity):
                        r.resolution_source = "comicvine_fallback"
                        r.fallback_used = True
                        r.fallback_reason = fallback_reason
                        cv_candidates.append(r)
                    elif isinstance(r, dict) and r.get("url"):
                        m_cv = re.search(r"4000-(\d+)", r["url"])
                        r_year = int(r.get("year") or r.get("volume_year") or 0) if (r.get("year") or r.get("volume_year")) else 0
                        r_series = r.get("series") or (r.get("title", "").split(" #")[0] if r.get("title") else parsed.series_name)
                        r_pub = r.get("publisher", "") or r.get("pub", "")
                        r_num = str(r.get("issue_number") or r.get("number") or parsed.issue_number)
                        cv_candidates.append(ComicIdentity(
                            provider="ComicVine",
                            issue_id=f"4000-{m_cv.group(1)}" if m_cv else r["url"],
                            issue_provider="ComicVine",
                            series_name=r_series,
                            issue_number=r_num,
                            publication_year=r_year,
                            publisher=r_pub,
                            resolution_source="comicvine_fallback",
                            fallback_used=True,
                            fallback_reason=fallback_reason
                        ))
            else:
                _logger.debug("PROVIDER_NOT_FOUND provider=ComicVine operation=search_issue query=%s", fname)
                provider_results["ComicVine"] = ProviderOperationResult(provider="ComicVine", operation="search_issue", status="NOT_FOUND")
                cv_fail_reason = "ComicVine returned no match"
        except Exception as e:
            state, retryable = classify_provider_error(e, provider="ComicVine", operation="search_issue", query_or_url=fname)
            provider_results["ComicVine"] = ProviderOperationResult(
                provider="ComicVine",
                operation="search_issue",
                status=state,
                error_type=type(e).__name__,
                retryable=retryable,
                message=str(e)
            )
            cv_fail_reason = f"ComicVine error: {e}"

        if cv_candidates:
            pool = local_candidates + kapowarr_candidates + cv_candidates
            best_cv, cv_dec = evaluate_candidate_pool_decision(pool, parsed, min_margin=10.0, existing_comic=existing)
            if best_cv and cv_dec.score >= 70.0 and not cv_dec.has_critical_conflict:
                best_cv.resolution_source = "comicvine_fallback"
                best_cv.fallback_used = True
                best_cv.fallback_reason = fallback_reason
                cv_dec.resolution_source = "comicvine_fallback"
                cv_dec.fallback_used = True
                cv_dec.fallback_reason = fallback_reason
                cv_dec.provider_results = provider_results
                return best_cv, cv_dec
            else:
                cv_fail_reason = f"ComicVine candidate confidence {cv_dec.score:.1f} < 70"

        # --- Stage 7: GCD Fallback (Phase 82.6 — Only if previous stages fail) ---
        gcp_candidates: List[ComicIdentity] = []
        gcd_fallback_reason = cv_fail_reason or fallback_reason

        if hasattr(self, "gcp") and self.gcp:
            try:
                gcp_results = self.gcp.search_issue(fname)
                if gcp_results:
                    provider_results["GCP"] = ProviderOperationResult(provider="GCP", operation="search_issue", status="SUCCESS")
                    for g in gcp_results:
                        if isinstance(g, ComicIdentity):
                            g.resolution_source = "gcd_fallback"
                            g.fallback_used = True
                            g.fallback_reason = gcd_fallback_reason
                            gcp_candidates.append(g)
                        elif isinstance(g, dict) and (g.get("url") or g.get("id")):
                            g_year = int(g.get("year") or g.get("volume_year") or 0) if (g.get("year") or g.get("volume_year")) else 0
                            g_series = g.get("series") or (g.get("title", "").split(" #")[0] if g.get("title") else parsed.series_name)
                            g_pub = g.get("publisher", "") or g.get("pub", "")
                            g_num = str(g.get("issue_number") or g.get("number") or parsed.issue_number)
                            gcp_candidates.append(ComicIdentity(
                                provider="GCP",
                                issue_id=str(g.get("id") or g.get("url")),
                                issue_provider="GCP",
                                series_name=g_series,
                                issue_number=g_num,
                                publication_year=g_year,
                                publisher=g_pub,
                                resolution_source="gcd_fallback",
                                fallback_used=True,
                                fallback_reason=gcd_fallback_reason
                            ))
                else:
                    _logger.debug("PROVIDER_NOT_FOUND provider=GCP operation=search_issue query=%s", fname)
                    provider_results["GCP"] = ProviderOperationResult(provider="GCP", operation="search_issue", status="NOT_FOUND")
            except Exception as e:
                state, retryable = classify_provider_error(e, provider="GCP", operation="search_issue", query_or_url=fname)
                provider_results["GCP"] = ProviderOperationResult(
                    provider="GCP",
                    operation="search_issue",
                    status=state,
                    error_type=type(e).__name__,
                    retryable=retryable,
                    message=str(e)
                )

        # --- Stage 8: Evaluate Candidate Pool / Unresolved ---
        all_candidates = local_candidates + kapowarr_candidates + cv_candidates + gcp_candidates
        has_existing_xml = any(c.provider == "ExistingXML" for c in local_candidates)
        if not (kapowarr_candidates or cv_candidates or gcp_candidates) and not has_existing_xml:
            dec = ConfidenceDecision(score=0.0, level=LEVEL_UNRESOLVED, action="SKIP", provider_results=provider_results)
            return None, dec

        if not all_candidates:
            dec = ConfidenceDecision(score=0.0, level=LEVEL_UNRESOLVED, action="SKIP", provider_results=provider_results)
            return None, dec

        best_cand, decision = evaluate_candidate_pool_decision(
            all_candidates,
            parsed,
            min_margin=10.0,
            existing_comic=existing
        )
        decision.provider_results = provider_results
        return best_cand, decision

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

    def resolve_file_pipeline(self, file_path: str, url_override: str = "", force_overwrite: bool = False) -> ResolutionResult:
        """
        Phase 57: Complete pipeline entry point executing identity resolution, candidate scoring,
        and metadata retrieval, returning a comprehensive ResolutionResult with preserved provider states.
        """
        identity, decision = self.resolve_identity(file_path, url_override=url_override)
        meta_res = None
        comic = None

        if identity and decision.action != "SKIP":
            meta_res = self.retrieve_metadata_result(identity, file_path=file_path)
            if meta_res.state == STATE_METADATA_FOUND and meta_res.comic:
                comic = meta_res.comic

        res_src = decision.resolution_source if decision and decision.resolution_source else (identity.resolution_source if identity else "")
        fb_used = decision.fallback_used if decision and decision.fallback_used else (identity.fallback_used if identity else False)
        fb_reason = decision.fallback_reason if decision and decision.fallback_reason else (identity.fallback_reason if identity else "")

        return ResolutionResult(
            identity=identity,
            confidence=decision.score if decision else 0.0,
            decision=decision,
            provider_results=decision.provider_results if decision else {},
            conflicts=[str(c) for c in (decision.conflicts if decision else [])],
            metadata_result=meta_res,
            comic=comic,
            resolution_source=res_src,
            fallback_used=fb_used,
            fallback_reason=fb_reason
        )
