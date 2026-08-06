import os
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict, Tuple
from models.comic import Comic
from config import Config
from cache.db import CacheManager
from providers.kapowarr import KapowarrProvider
from providers.comicvine import ComicVineProvider
from providers.gcp import GCPProvider

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
            root = ET.fromstring(xml_data)

            c = Comic()
            c.title = root.findtext("Title") or ""
            c.series = root.findtext("Series") or ""
            c.number = root.findtext("Number") or ""
            c.volume = root.findtext("Volume") or ""
            c.summary = root.findtext("Summary") or ""
            c.notes = root.findtext("Notes") or ""
            c.publisher = root.findtext("Publisher") or ""
            c.genre = root.findtext("Genre") or ""
            c.web = root.findtext("Web") or ""

            try:
                c.year = int(root.findtext("Year") or 0)
                c.month = int(root.findtext("Month") or 0)
                c.day = int(root.findtext("Day") or 0)
            except ValueError:
                pass

            writers = root.findtext("Writer")
            if writers: c.writers = [w.strip() for w in writers.split(",") if w.strip()]
            pencillers = root.findtext("Penciller")
            if pencillers: c.pencillers = [p.strip() for p in pencillers.split(",") if p.strip()]
            inkers = root.findtext("Inker")
            if inkers: c.inkers = [i.strip() for i in inkers.split(",") if i.strip()]
            colorists = root.findtext("Colorist")
            if colorists: c.colorists = [col.strip() for col in colorists.split(",") if col.strip()]
            letterers = root.findtext("Letterer")
            if letterers: c.letterers = [l.strip() for l in letterers.split(",") if l.strip()]

            chars = root.findtext("Characters")
            if chars: c.characters = [ch.strip() for ch in chars.split(",") if ch.strip()]
            teams = root.findtext("Teams")
            if teams: c.teams = [t.strip() for t in teams.split(",") if t.strip()]

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
