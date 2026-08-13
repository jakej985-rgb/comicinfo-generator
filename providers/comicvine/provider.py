import re
import urllib.parse
from typing import Optional, Tuple, List, Dict
from bs4 import BeautifulSoup
from models.comic import Comic
from providers.base import BaseProvider
from providers.comicvine.client import ComicVineClient
from providers.comicvine.parser import parse_html, parse_date
from config import load_config
from cache.db import CacheManager

def _volume_slug_from_url(volume_url: str) -> str:
    m = re.search(r"/([^/]+)/4050-", volume_url)
    if not m:
        return ""
    slug = m.group(1).lower().strip()
    return "" if slug == "volume" else slug

def _slug_matches_series(issue_url: str, series_slug: str) -> bool:
    if not series_slug:
        return True
    m = re.search(r"/([^/]+)/4000-", issue_url)
    if not m:
        return True
    issue_slug = m.group(1).lower()

    COLLECTED_KEYWORDS = (
        "-tpb", "-hc", "-gn", "-graphic-novel", "-trade-paperback",
        "-hardcover", "-softcover", "-collection", "-collected",
        "-omnibus", "-compendium", "-deluxe", "-edition", "-masterworks",
        "-box-set", "-slipcase", "-treasury", "-digest", "-epic-collection",
        "-ultimate-collection", "-must-haves", "-volume-", "-vol-", "coleccionable"
    )
    if any(kw in issue_slug for kw in COLLECTED_KEYWORDS):
        return False

    def strip_articles(slug: str) -> str:
        for prefix in ("the-", "a-", "an-"):
            if slug.startswith(prefix):
                slug = slug[len(prefix):]
        return slug

    norm_series = strip_articles(series_slug)
    norm_issue = strip_articles(issue_slug)

    if not norm_issue.startswith(norm_series):
        return False

    suffix = norm_issue[len(norm_series):]
    if not suffix:
        return True
    if not suffix.startswith("-"):
        return False

    after_dash = suffix[1:]
    if not after_dash or after_dash[0].isdigit():
        return True

    ALLOWED_SPECIAL_PREFIXES = {
        "annual", "special", "super", "giant", "fcbd", "free", "ashcan", "preview", "oneshot", "one", "zero", "issue"
    }
    first_word = after_dash.split("-")[0]
    return first_word in ALLOWED_SPECIAL_PREFIXES


class ComicVineProvider(BaseProvider):
    """
    Comic Vine provider integration implementing BaseProvider interface.
    Coordinates HTTP fetching via ComicVineClient and pure HTML parsing via parser module.
    """

    def __init__(self, api_key: str = "", timeout: int = 30):
        self.api_key = api_key
        self.client = ComicVineClient(api_key=api_key, timeout=timeout)

    def get_name(self) -> str:
        return "CV"

    def search_series(self, query: str) -> list[dict]:
        return self._search_comicvine(query, search_type="volume")

    def search_issue(self, query: str) -> list[dict]:
        return self._search_comicvine(query, search_type="issue")

    def lookup_volume(self, volume_id: str) -> tuple[str, dict[str, str], list[dict]]:
        url = volume_id if volume_id.startswith("http") else f"https://comicvine.gamespot.com/volume/4050-{volume_id}/"
        return self._scrape_volume(url)

    def lookup_issue(self, issue_id_or_url: str) -> Optional[Comic]:
        url = issue_id_or_url if issue_id_or_url.startswith("http") else f"https://comicvine.gamespot.com/issue/4000-{issue_id_or_url}/"
        try:
            return self._scrape_issue(url)
        except Exception:
            return None

    def _scrape_issue(self, url: str, use_cache: bool = True) -> Comic:
        clean_url = url.strip()
        if use_cache:
            try:
                cfg = load_config()
                cache_mgr = CacheManager(cfg.cache.db_path)
                cached = cache_mgr.get_cached_issue("ComicVine", clean_url)
                if cached and cached.series:
                    return cached
            except Exception:
                pass

        html_content = self.client.fetch_html(clean_url)
        comic = parse_html(html_content, clean_url)

        if comic and use_cache:
            try:
                cfg = load_config()
                cache_mgr = CacheManager(cfg.cache.db_path)
                cache_mgr.save_cached_issue("ComicVine", clean_url, comic)
            except Exception:
                pass

        return comic

    def _scrape_volume(self, volume_url: str, max_pages_limit: int = 50, use_cache: bool = True) -> tuple[str, dict[str, str], list[dict]]:
        clean_url = re.sub(r"\?page=\d+.*$", "", volume_url).rstrip("/") + "/"
        if use_cache:
            try:
                cfg = load_config()
                cache_mgr = CacheManager(cfg.cache.db_path)
                cached_vol = cache_mgr.get_cached_series("ComicVine", clean_url)
                if cached_vol and "series_name" in cached_vol and "matched_map" in cached_vol and "matched_list" in cached_vol:
                    return cached_vol["series_name"], cached_vol["matched_map"], cached_vol["matched_list"]
            except Exception:
                pass

        html_content = self.client.fetch_html(clean_url)
        soup = BeautifulSoup(html_content, "html.parser")

        series_name = ""
        h1 = soup.find("h1")
        if h1:
            series_name = h1.get_text(" ", strip=True).split("»")[0].strip()

        series_slug = _volume_slug_from_url(volume_url)
        if not series_slug and series_name:
            clean_name = re.sub(r"[^a-zA-Z0-9\s-]", "", series_name).lower().strip()
            series_slug = re.sub(r"[\s_]+", "-", clean_name)

        max_page = 1
        for a in soup.find_all("a", href=re.compile(r"page=\d+")):
            m = re.search(r"page=(\d+)", a["href"])
            if m:
                pnum = int(m.group(1))
                if pnum > max_page:
                    max_page = pnum

        matched_map = {}
        matched_list = []

        def extract_issues_from_soup(s):
            for a in s.find_all("a", href=re.compile(r"/4000-\d+")):
                href = a["href"]
                full_url = href if href.startswith("http") else "https://comicvine.gamespot.com" + href
                parent = a.find_parent(["li", "div", "tr", "td"]) or a
                txt = parent.get_text(" ", strip=True)

                if re.search(r"\(#?\d+\s*[-–]\s*\d+\)", txt) or re.search(r"#\d+\s*[-–]\s*\d+", txt):
                    continue

                m = re.search(r"#(?:Issue\s*)?(\d+½|\d+/\d+|\d+\.\d+|\d+[a-zA-Z]?|½|1/2|0\.5)", txt, re.I)
                if not m:
                    m = re.search(r"Issue\s*#?\s*(\d+½|\d+/\d+|\d+\.\d+|\d+[a-zA-Z]?|½|1/2|0\.5)", txt, re.I)
                num_str = m.group(1) if m else ""

                if not num_str:
                    label = a.get_text(" ", strip=True)
                    m_label = re.search(r"#(\d+½|\d+/\d+|\d+\.\d+|\d+[a-zA-Z]?|½|1/2|0\.5)", label)
                    if m_label:
                        num_str = m_label.group(1)

                if num_str:
                    if _slug_matches_series(full_url, series_slug):
                        if num_str not in matched_map:
                            label_str = a.get_text(" ", strip=True)
                            matched_map[num_str] = full_url
                            matched_list.append({"number": num_str, "label": label_str, "url": full_url})

        extract_issues_from_soup(soup)

        pages_to_fetch = min(max_page, max_pages_limit)
        for page_idx in range(2, pages_to_fetch + 1):
            p_url = f"{clean_url}?page={page_idx}"
            try:
                p_html = self.client.fetch_html(p_url)
                p_soup = BeautifulSoup(p_html, "html.parser")
                extract_issues_from_soup(p_soup)
            except Exception:
                pass

        issue_map = dict(matched_map)
        issues_list = sorted(
            matched_list,
            key=lambda x: int(re.sub(r"\D", "", x["number"])) if re.sub(r"\D", "", x["number"]) else 0
        )

        if series_name and use_cache:
            try:
                cfg = load_config()
                cache_mgr = CacheManager(cfg.cache.db_path)
                cache_mgr.save_cached_series(
                    "ComicVine",
                    clean_url,
                    series_name,
                    0,
                    "",
                    {"series_name": series_name, "matched_map": issue_map, "matched_list": issues_list}
                )
            except Exception:
                pass

        return series_name, issue_map, issues_list

    def _search_comicvine(self, query: str, search_type: str = "all", use_cache: bool = True) -> list[dict]:
        clean_query = query.strip()
        if not clean_query:
            return []

        if use_cache:
            try:
                cfg = load_config()
                cache_mgr = CacheManager(cfg.cache.db_path)
                cached_res = cache_mgr.get_cached_search("ComicVine", search_type, clean_query)
                if cached_res is not None:
                    return cached_res
            except Exception:
                pass

        encoded_query = urllib.parse.quote_plus(clean_query)
        search_url = f"https://comicvine.gamespot.com/search/?q={encoded_query}"
        if search_type == "volume":
            search_url += "&indices%5B0%5D=volume"
        elif search_type == "issue":
            search_url += "&indices%5B0%5D=issue"

        html_content = self.client.fetch_html(search_url)
        soup = BeautifulSoup(html_content, "html.parser")

        results = []
        for li in soup.find_all(["li", "div"], class_=re.compile(r"search-result|media|wiki-block", re.I)):
            a = li.find("a", href=re.compile(r"/(?:4000|4050)-\d+"))
            if not a:
                continue

            href = a["href"]
            full_url = href if href.startswith("http") else "https://comicvine.gamespot.com" + href
            raw_title = a.get_text(" ", strip=True)

            img = li.find("img")
            img_src = img.get("src", "") if img else ""
            text_block = li.get_text(" ", strip=True)
            is_volume = "/4050-" in full_url

            m_year = re.search(r"\b(19\d\d|20\d\d)\b", text_block)
            year_str = m_year.group(1) if m_year else ""

            m_count = re.search(r"\((\d+)\s+issues\)", text_block, re.I)
            count_str = f"{m_count.group(1)} issues" if m_count else ""
            clean_title = re.sub(r"\s+", " ", raw_title).strip()

            if clean_title and full_url and not any(r["url"] == full_url for r in results):
                results.append({
                    "title": clean_title,
                    "url": full_url,
                    "image": img_src,
                    "type": "volume" if is_volume else "issue",
                    "type_label": "Volume / Series" if is_volume else "Single Issue",
                    "year": year_str,
                    "count": count_str,
                    "description": text_block[:160]
                })

        if use_cache:
            try:
                cfg = load_config()
                cache_mgr = CacheManager(cfg.cache.db_path)
                cache_mgr.save_cached_search("ComicVine", search_type, clean_query, results)
            except Exception:
                pass

        return results
