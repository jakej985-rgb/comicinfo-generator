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
from pipeline.confidence import evaluate_confidence, ConfidenceDecision, LEVEL_AUTO_ACCEPT, LEVEL_ACCEPT_WITH_WARNING

def read_existing_comicinfo(cbz_path: str) -> Optional[Comic]:
    """Reads existing ComicInfo.xml from a .cbz archive if present and valid."""
    if not os.path.exists(cbz_path) or not cbz_path.lower().endswith(".cbz"):
        return None

    try:
        with zipfile.ZipFile(cbz_path, "r") as z:
            xml_names = [n for n in z.namelist() if n.lower() == "comicinfo.xml"]
            if not xml_names:
                return None

            xml_data = z.read(xml_names[0])
            c = ComicInfoParser.parse_xml_bytes(xml_data)

            if c.series or c.title:
                c.provider_name = "ExistingXML"
                return c
    except Exception:
        pass

    return None

class MetadataResolver:
    """
    Metadata Resolution Pipeline.
    Strictly separates Identity Resolution (resolve_identity) from Metadata Retrieval (retrieve_metadata).
    """

    def __init__(self, config: Config, cache_mgr: Optional[CacheManager] = None):
        self.config = config
        self.cache_mgr = cache_mgr or CacheManager(config.cache.db_path)

        self.kapowarr = KapowarrProvider(url=config.kapowarr.url, api_key=config.kapowarr.api_key)
        self.comicvine = ComicVineProvider(api_key=config.comicvine.api_key)
        self.gcp = GCPProvider()

    def resolve_identity(self, file_path: str, url_override: str = "") -> Tuple[Optional[ComicIdentity], ConfidenceDecision]:
        """
        Phase 9 Step 1: Resolves comic identity candidate without retrieving full metadata details.
        Returns (best_candidate_identity, confidence_decision).
        """
        parsed = parse_filename_identity(file_path)

        # 1. Direct URL Override
        if url_override:
            url_str = url_override.strip()
            if "comicvine" in url_str.lower():
                m = re.search(r"4000-(\d+)", url_str)
                cand = ComicIdentity(
                    provider="ComicVine",
                    issue_id=f"4000-{m.group(1)}" if m else url_str,
                    issue_provider="ComicVine",
                    series_name=parsed.series_name,
                    issue_number=parsed.issue_number
                )
                decision = evaluate_confidence(cand, parsed)
                return cand, decision

        # 2. Existing Embedded XML identity check
        existing = read_existing_comicinfo(file_path)
        if existing and not self.config.output.overwrite:
            cand = ComicIdentity(
                provider="ExistingXML",
                series_name=existing.series or existing.title,
                issue_number=existing.number,
                publication_year=existing.year,
                publisher=existing.publisher
            )
            decision = evaluate_confidence(cand, parsed)
            return cand, decision

        # 3. Gather local identity candidates (filename + directory)
        local_candidates = extract_identity_candidates(file_path)

        # 4. Search Providers for Candidate Identity Signals
        fname = os.path.basename(file_path)
        provider_candidates: List[ComicIdentity] = []

        # Kapowarr
        if self.kapowarr.test_connection():
            try:
                searches = self.kapowarr.search_issue(fname)
                for s in searches:
                    if s.get("id"):
                        provider_candidates.append(ComicIdentity(
                            provider="Kapowarr",
                            issue_id=str(s["id"]),
                            issue_provider="Kapowarr",
                            series_name=s.get("title", "").split(" #")[0] or parsed.series_name,
                            issue_number=parsed.issue_number
                        ))
            except Exception:
                pass

        # ComicVine
        try:
            cv_results = self.comicvine.search_issue(fname)
            for r in cv_results:
                if r.get("url"):
                    m_cv = re.search(r"4000-(\d+)", r["url"])
                    provider_candidates.append(ComicIdentity(
                        provider="ComicVine",
                        issue_id=f"4000-{m_cv.group(1)}" if m_cv else r["url"],
                        issue_provider="ComicVine",
                        series_name=r.get("title", "").split(" #")[0] or parsed.series_name,
                        issue_number=parsed.issue_number
                    ))
        except Exception:
            pass

        all_candidates = local_candidates + provider_candidates
        if not all_candidates:
            empty_cand = ComicIdentity(series_name=parsed.series_name, issue_number=parsed.issue_number)
            return None, ConfidenceDecision(score=0.0, action="SKIP")

        # 5. Evaluate Confidence Decisions for all candidates
        scored_pairs = []
        for cand in all_candidates:
            dec = evaluate_confidence(cand, parsed)
            scored_pairs.append((cand, dec))

        # Sort by score descending
        scored_pairs.sort(key=lambda p: p[1].score, reverse=True)
        best_cand, best_dec = scored_pairs[0]

        return (best_cand, best_dec) if best_dec.action != "SKIP" else (None, best_dec)

    def retrieve_metadata(self, identity: ComicIdentity) -> Optional[Comic]:
        """
        Phase 9 Step 2: Retrieves full Comic metadata details for a resolved ComicIdentity.
        Does NOT alter identity resolution.
        """
        if not identity:
            return None

        comic: Optional[Comic] = None

        if identity.provider == "ExistingXML":
            # Retain existing XML fields
            comic = Comic(
                series=identity.series_name,
                number=identity.issue_number,
                year=identity.publication_year,
                publisher=identity.publisher,
                provider_name="ExistingXML"
            )
        elif identity.provider == "Kapowarr" and identity.issue_id:
            comic = self.kapowarr.lookup_issue(identity.issue_id)
        elif identity.provider == "ComicVine" and identity.issue_id:
            cv_url = f"https://comicvine.gamespot.com/issue/{identity.issue_id}/" if not identity.issue_id.startswith("http") else identity.issue_id
            comic = self.comicvine.lookup_issue(cv_url)
        elif identity.provider == "GCP" and identity.issue_id:
            comic = self.gcp.lookup_issue(identity.issue_id)

        # Fallback metadata generation from identity if provider lookup returns partial data
        if not comic:
            comic = Comic(
                series=identity.series_name,
                number=identity.issue_number,
                year=identity.publication_year,
                publisher=identity.publisher,
                provider_name=identity.provider or "Resolver"
            )

        comic.identity = identity
        return comic

    def resolve_file_metadata(self, file_path: str, url_override: str = "", force_overwrite: bool = False) -> Tuple[Optional[Comic], str]:
        """
        Pipeline entry point chaining resolve_identity() and retrieve_metadata(identity).
        Returns (Comic_object, provider_name_used).
        """
        identity, decision = self.resolve_identity(file_path, url_override=url_override)
        if identity and decision.action != "SKIP":
            comic = self.retrieve_metadata(identity)
            return comic, identity.provider or "Resolver"

        return None, "None"
