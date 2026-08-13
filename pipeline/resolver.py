import os
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict, Tuple
from models.comic import Comic
from config import Config
from cache.db import CacheManager
from providers.kapowarr import KapowarrProvider
from providers.comicvine import ComicVineProvider
from providers.gcp import GCPProvider

from writers.comicinfo import ComicInfoParser

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
    Evaluates metadata providers according to priority:
    1. Existing valid ComicInfo.xml
    2. Kapowarr Provider (preferred)
    3. ComicVine Provider
    4. GCP Provider (fallback)
    """

    def __init__(self, config: Config, cache_mgr: Optional[CacheManager] = None):
        self.config = config
        self.cache_mgr = cache_mgr or CacheManager(config.cache.db_path)

        self.kapowarr = KapowarrProvider(url=config.kapowarr.url, api_key=config.kapowarr.api_key)
        self.comicvine = ComicVineProvider(api_key=config.comicvine.api_key)
        self.gcp = GCPProvider()

    def resolve_file_metadata(self, file_path: str, url_override: str = "", force_overwrite: bool = False) -> Tuple[Optional[Comic], str]:
        """
        Resolves metadata for a comic archive file according to priority hierarchy.
        Returns (Comic_object, provider_name_used).
        """
        # Step 1: Check existing ComicInfo.xml inside archive
        if not force_overwrite and not self.config.output.overwrite:
            existing = read_existing_comicinfo(file_path)
            if existing:
                return existing, "ExistingXML"

        # Step 2: Direct URL or copied page text override
        if url_override:
            url_str = url_override.strip()
            if "comics.org" in url_str.lower() or "Pencils:" in url_str:
                c = self.gcp.lookup_issue(url_str)
                if c: return c, "GCP"
            elif "comicvine" in url_str.lower():
                c = self.comicvine.lookup_issue(url_str)
                if c: return c, "CV"
            elif "kapowarr" in url_str.lower() or url_str.isdigit():
                c = self.kapowarr.lookup_issue(url_str)
                if c: return c, "Kapowarr"

        # Step 3: Kapowarr Lookup (preferred provider)
        if self.kapowarr.test_connection():
            fname = os.path.basename(file_path)
            searches = self.kapowarr.search_issue(fname)
            if searches and searches[0].get("id"):
                c = self.kapowarr.lookup_issue(searches[0]["id"])
                if c: return c, "Kapowarr"

        # Step 4: ComicVine Lookup
        fname = os.path.basename(file_path)
        cv_results = self.comicvine.search_issue(fname)
        if cv_results and cv_results[0].get("url"):
            c = self.comicvine.lookup_issue(cv_results[0]["url"])
            if c: return c, "CV"

        # Step 5: GCP Fallback
        gcp_results = self.gcp.search_issue(fname)
        if gcp_results and gcp_results[0].get("url"):
            c = self.gcp.lookup_issue(gcp_results[0]["url"])
            if c: return c, "GCP"

        return None, "None"
