"""
services/metadata.py — Phase 32

Metadata fetch and provider-routing service layer.
No HTTP or archive I/O concerns.
"""
import json
import re
from typing import Tuple

from models.comic import Comic, merge_comics
from config import load_config
from providers.kapowarr import KapowarrProvider
from providers.comicvine import scrape_issue as scrape_cv_issue, scrape_volume as scrape_cv_volume, search_comicvine
from providers.gcp import scrape_gcp_issue, scrape_gcp_volume, search_gcp


def detect_provider(url: str) -> str:
    """Returns 'Kapowarr', 'GCP', or 'CV' based on URL or text content."""
    url_lower = url.lower()
    try:
        cfg = load_config()
        kap_base = cfg.kapowarr.url.lower().rstrip("/") if cfg.kapowarr.url else ""
        if kap_base and kap_base in url_lower:
            return "Kapowarr"
    except Exception:
        pass
    if "comics.org" in url_lower or any(
        k in url for k in ["Pencils:", "Script:", "Characters:", "Table of Contents"]
    ):
        return "GCP"
    return "CV"


def scrape_single_url(url_or_text: str) -> Comic:
    """Fetches metadata for a single URL/page-text via the appropriate provider."""
    prov = detect_provider(url_or_text)
    if prov == "Kapowarr":
        try:
            cfg = load_config()
            kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
            c = kap.lookup_issue(url_or_text)
            if c:
                return c
        except Exception:
            pass
    elif prov == "GCP":
        return scrape_gcp_issue(url_or_text)
    return scrape_cv_issue(url_or_text)


def scrape_any_volume(url: str) -> Tuple[str, dict, list]:
    """Fetches volume/series data from the appropriate provider."""
    prov = detect_provider(url)
    if prov == "Kapowarr":
        try:
            cfg = load_config()
            kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
            return kap.lookup_volume(url)
        except Exception:
            pass
    elif prov == "GCP":
        return scrape_gcp_volume(url)
    return scrape_cv_volume(url)


def fetch_and_merge_urls(url_val) -> Comic:
    """Resolves one or more URLs/texts into a merged Comic object."""
    if isinstance(url_val, str) and (
        any(k in url_val for k in ["Pencils:", "Script:", "Characters:", "Table of Contents"])
        or ("comics.org" in url_val and len(url_val.split("\n")) > 2)
    ):
        return scrape_gcp_issue(url_val)

    urls = []
    if isinstance(url_val, list):
        urls = [str(u).strip() for u in url_val if u and str(u).strip()]
    elif isinstance(url_val, str):
        if url_val.startswith("[") and url_val.endswith("]"):
            try:
                parsed = json.loads(url_val)
                if isinstance(parsed, list):
                    urls = [str(u).strip() for u in parsed if str(u).strip()]
            except Exception:
                pass
        if not urls:
            urls = [
                u.strip()
                for u in re.split(r"[\n,\s]+", url_val)
                if u.strip() and u.strip().startswith("http")
            ]

    if not urls:
        if isinstance(url_val, str) and url_val.strip():
            return scrape_single_url(url_val.strip())
        raise ValueError("No valid comic database URLs or page text provided.")

    if len(urls) == 1:
        return scrape_single_url(urls[0])

    comics = [scrape_single_url(u) for u in urls]
    return merge_comics(comics)


def search_all_providers(query: str, search_type: str = "all") -> Tuple[list, bool]:
    """Searches all configured providers and returns combined results."""
    results = []
    kapowarr_active = False

    try:
        cfg = load_config()
        if cfg.kapowarr.url and cfg.kapowarr.api_key:
            kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
            if kap.test_connection():
                kapowarr_active = True
                if search_type in ("all", "kapowarr", "kapowarr_volume", "kapowarr_issue"):
                    if search_type in ("all", "kapowarr", "kapowarr_volume"):
                        for r in kap.search_series(query):
                            r["provider"] = "Kapowarr"
                            results.append(r)
                    if search_type in ("all", "kapowarr", "kapowarr_issue"):
                        for r in kap.search_issue(query):
                            r["provider"] = "Kapowarr"
                            results.append(r)
    except Exception:
        pass

    if search_type in ("all", "scrapers", "cv_volume", "cv_issue"):
        cv_type = "all"
        if search_type == "cv_volume":
            cv_type = "volume"
        elif search_type == "cv_issue":
            cv_type = "issue"
        for r in search_comicvine(query, cv_type):
            r["provider"] = "CV"
            if r["type"] == "volume":
                r["type"] = "cv_volume"
                r["type_label"] = "CV Series"
            else:
                r["type"] = "cv_issue"
                r["type_label"] = "CV Issue"
            results.append(r)

    if search_type in ("all", "scrapers", "gcp_volume", "gcp_issue"):
        for r in search_gcp(query, search_type):
            r["provider"] = "GCP"
            results.append(r)

    return results, kapowarr_active
