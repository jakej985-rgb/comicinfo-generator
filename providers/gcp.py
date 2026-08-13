import re
import urllib.parse
import requests
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from models.comic import Comic
from providers.base import BaseProvider
from config import load_config
from cache.db import CacheManager

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

MONTH_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10,
    "november": 11, "nov": 11, "december": 12, "dec": 12
}

def clean_creator_name(val: str) -> str:
    """Cleans up creator name strings by removing notes, parentheses, and trailing characters."""
    c = re.sub(r"\s*\([^)]*\)", "", val)
    c = re.sub(r"\s*\([^)]*", "", c)
    c = c.strip().strip("?").strip()
    return c

def fetch_gcp_html(url: str, timeout: int = 2) -> str:
    """Helper to fetch HTML content from comics.org URL with fast direct check & HTTPS Wayback Machine fallback."""
    if HAS_CURL_CFFI:
        try:
            r = cffi_requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=timeout)
            if r.status_code == 200 and "Just a moment..." not in r.text and "<title>Just a moment..." not in r.text:
                return r.text
        except Exception:
            pass

    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200 and "Just a moment..." not in r.text and "<title>Just a moment..." not in r.text:
            return r.text
    except Exception:
        pass

    # HTTPS Wayback Machine Archive Fallback if Cloudflare blocks direct HTTP request
    try:
        wb_url = f"https://web.archive.org/web/2024/{url}"
        r = requests.get(wb_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=8)
        if r.status_code == 200 and len(r.text) > 1000:
            return r.text
    except Exception:
        pass

    return ""

def fetch_gcp_api_json(url: str, timeout: int = 2) -> dict:
    """Helper to fetch JSON content from comics.org REST API endpoint with fast 2s timeout."""
    clean_url = url if "?format=json" in url else f"{url.rstrip('/')}/?format=json"
    headers = dict(HEADERS)
    headers["Accept"] = "application/json"
    
    if HAS_CURL_CFFI:
        try:
            r = cffi_requests.get(clean_url, headers=headers, impersonate="chrome", timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass

    try:
        r = requests.get(clean_url, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass

    return {}

def parse_gcd_soup(soup: BeautifulSoup, url: str) -> Comic:
    """Parses BeautifulSoup object from GCD HTML page."""
    c = Comic()
    c.provider_name = "GCP"
    c.web = url

    h1 = soup.find("h1")
    if h1:
        c.series = h1.get_text(" ", strip=True)
        c.title = c.series

    title_tag = soup.find("title")
    if title_tag:
        t_text = title_tag.get_text(" ", strip=True)
        m = re.search(r"GCD\s*::\s*Issue\s*::\s*(.+?)(?:\s*#\s*(.*))?$", t_text, re.I)
        if m:
            c.series = m.group(1).strip()
            c.number = m.group(2).strip() if m.group(2) else ""
            c.title = f"{c.series} #{c.number}" if c.number else c.series

    page_txt = soup.get_text(" ", strip=True)
    m_pub = re.search(r"([A-Za-z0-9\s]+),\s*(\d{4})\s+Series", page_txt)
    if m_pub:
        pub_raw = m_pub.group(1).strip()
        pub_parts = pub_raw.split()
        c.publisher = pub_parts[-1] if pub_parts else pub_raw
        c.year = int(m_pub.group(2))

    return c

def parse_gcp_text_refined(text: str, default_url: str = "") -> Comic:
    """Parses Grand Comics Database HTML or copied page text layout into a Comic object."""
    if "<html" in text.lower() or "<body" in text.lower() or "<title>" in text.lower():
        soup = BeautifulSoup(text, "html.parser")
        c_soup = parse_gcd_soup(soup, default_url)
        if c_soup.series and c_soup.series != "Grand Comics Database Issue":
            return c_soup

    c = Comic()
    c.provider_name = "GCP"
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Extract URL if present
    web_url = default_url
    clean_lines = []
    for l in lines:
        if l.startswith("http://") or l.startswith("https://"):
            if not web_url: web_url = l
        else:
            clean_lines.append(l)

    c.web = web_url

    if clean_lines:
        c.title = clean_lines[0]
        m_issue = re.search(r"(.+?)\s+#?(\d+[a-zA-Z]?|\d+\.\d+|\d+|\[[^\]]+\])", c.title)
        if m_issue:
            c.series = m_issue.group(1).strip()
            c.number = m_issue.group(2).strip().lstrip("#")
        else:
            c.series = c.title

    page_txt = "\n".join(clean_lines)

    m_pub = re.search(r"([A-Za-z0-9\s]+),\s+(\d{4})\s+Series", page_txt)
    if m_pub:
        raw_pub = m_pub.group(1).strip().split("\n")[-1].strip()
        c.publisher = raw_pub
        c.year = int(m_pub.group(2))

    m_date = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December|Summer|Winter|Spring|Fall)\s+(\d{4})\b", page_txt, re.I)
    if m_date:
        if not c.year: c.year = int(m_date.group(2))
        m_name = m_date.group(1).lower()
        if m_name in MONTH_MAP: c.month = MONTH_MAP[m_name]

    for line in clean_lines:
        if line.startswith("Script:") or line.startswith("Writer:"):
            for val in re.split(r"[,;]+", line.split(":", 1)[1]):
                clean = clean_creator_name(val)
                if clean and clean.lower() not in ("none", "") and clean not in c.writers:
                    c.writers.append(clean)

        elif line.startswith("Pencils:") or line.startswith("Penciller:"):
            for val in re.split(r"[,;]+", line.split(":", 1)[1]):
                clean = clean_creator_name(val)
                if clean and clean.lower() not in ("none", "") and clean not in c.pencillers:
                    c.pencillers.append(clean)

        elif line.startswith("Inks:") or line.startswith("Inker:"):
            for val in re.split(r"[,;]+", line.split(":", 1)[1]):
                clean = clean_creator_name(val)
                if clean and clean.lower() not in ("none", "") and clean not in c.inkers:
                    c.inkers.append(clean)

        elif line.startswith("Colors:") or line.startswith("Colorist:"):
            for val in re.split(r"[,;]+", line.split(":", 1)[1]):
                clean = clean_creator_name(val)
                if clean and clean.lower() not in ("none", "") and clean not in c.colorists:
                    c.colorists.append(clean)

        elif line.startswith("Letters:") or line.startswith("Letterer:"):
            for val in re.split(r"[,;]+", line.split(":", 1)[1]):
                clean = clean_creator_name(val)
                if clean and clean.lower() not in ("none", "") and clean not in c.letterers:
                    c.letterers.append(clean)

        elif line.startswith("Genre:"):
            c.genre = line.split(":", 1)[1].strip()

        elif line.startswith("Characters:"):
            for char in re.split(r"[;;\n]+", line.split(":", 1)[1]):
                clean = clean_creator_name(char)
                if clean and clean.lower() not in ("none", "") and len(clean) > 1 and clean not in c.characters:
                    c.characters.append(clean)

    if not c.title and c.series:
        c.title = f"{c.series} #{c.number}" if c.number else c.series

    return c

def scrape_gcp_issue(url_or_text: str, use_cache: bool = True) -> Comic:
    """Scrapes a Grand Comics Database issue page or copied text into a Comic using SQLite cache."""
    input_str = url_or_text.strip()

    if len(input_str.split("\n")) > 2 or any(k in input_str for k in ["Pencils:", "Script:", "Inks:", "Characters:", "Table of Contents"]):
        return parse_gcp_text_refined(input_str)

    m_url = re.search(r"https?://[^\s]+", input_str)
    url = m_url.group(0) if m_url else input_str

    if use_cache:
        try:
            cfg = load_config()
            cache_mgr = CacheManager(cfg.cache.db_path)
            cached = cache_mgr.get_cached_issue("GCP", url)
            if cached and cached.series:
                return cached
        except Exception:
            pass

    c = Comic()
    c.provider_name = "GCP"
    c.web = url
    
    m_issue = re.search(r"/issue/(\d+)", url)
    issue_id = m_issue.group(1) if m_issue else "1"
    c.number = issue_id
    c.provider_id = issue_id
    
    api_data = fetch_gcp_api_json(f"https://www.comics.org/api/issue/{issue_id}/", timeout=2)
    if api_data and api_data.get("id"):
        c.number = str(api_data.get("number", "")).strip().lstrip("#")
        c.title = api_data.get("title", "") or ""

        pub_date = str(api_data.get("publication_date", "")).strip()
        m_year = re.search(r"\b(19\d\d|20\d\d)\b", pub_date)
        if m_year:
            c.year = int(m_year.group(1))

        c.summary = api_data.get("notes", "") or ""

        series_api = api_data.get("series")
        if series_api:
            s_data = fetch_gcp_api_json(series_api, timeout=2)
            if s_data:
                c.series = s_data.get("name", "")
                pub_api = s_data.get("publisher")
                if pub_api:
                    p_data = fetch_gcp_api_json(pub_api, timeout=2)
                    if p_data:
                        c.publisher = p_data.get("name", "")

        for story in api_data.get("story_set", []):
            writer = story.get("writer")
            if writer:
                for w in re.split(r"[,;]+", writer):
                    w_name = clean_creator_name(w)
                    if w_name and w_name not in c.writers: c.writers.append(w_name)

            penciler = story.get("penciler")
            if penciler:
                for p in re.split(r"[,;]+", penciler):
                    p_name = clean_creator_name(p)
                    if p_name and p_name not in c.pencillers: c.pencillers.append(p_name)

            inker = story.get("inker")
            if inker:
                for i in re.split(r"[,;]+", inker):
                    i_name = clean_creator_name(i)
                    if i_name and i_name not in c.inkers: c.inkers.append(i_name)

            colorist = story.get("colorist")
            if colorist:
                for col in re.split(r"[,;]+", colorist):
                    col_name = clean_creator_name(col)
                    if col_name and col_name not in c.colorists: c.colorists.append(col_name)

            chars = story.get("characters")
            if chars:
                for ch in re.split(r"[;]+", chars):
                    ch_name = clean_creator_name(ch)
                    if ch_name and ch_name not in c.characters: c.characters.append(ch_name)

        if not c.title and c.series:
            c.title = f"{c.series} #{c.number}" if c.number else c.series

        if use_cache and c.series:
            try:
                cfg = load_config()
                cache_mgr = CacheManager(cfg.cache.db_path)
                cache_mgr.save_cached_issue("GCP", url, c)
            except Exception:
                pass

        return c

    html_text = fetch_gcp_html(url, timeout=2)
    if html_text:
        res_c = parse_gcp_text_refined(html_text, url)
        if res_c.series and res_c.series != "Grand Comics Database Issue":
            if not res_c.summary:
                res_c.summary = f"Scraped Series, Publisher & Date from archive. To include full creator credits & characters, copy-paste the GCP page text into the box!"
            if use_cache:
                try:
                    cfg = load_config()
                    cache_mgr = CacheManager(cfg.cache.db_path)
                    cache_mgr.save_cached_issue("GCP", url, res_c)
                except Exception:
                    pass
            return res_c

    c.title = f"GCP Issue #{issue_id}"
    c.series = "Grand Comics Database Issue"
    c.publisher = "Grand Comics Database (GCP)"
    c.summary = f"Metadata generated for GCP Issue #{issue_id} ({url}). Note: Direct scraping was blocked by Cloudflare anti-bot."
    if use_cache:
        try:
            cfg = load_config()
            cache_mgr = CacheManager(cfg.cache.db_path)
            cache_mgr.save_cached_issue("GCP", url, c)
        except Exception:
            pass
    return c

def scrape_gcp_volume(volume_url: str) -> tuple[str, dict[str, str], list[dict]]:
    """Scrapes a GCP Series/Volume page (https://www.comics.org/series/XXXXX/)."""
    m_series = re.search(r"/series/(\d+)", volume_url)
    if not m_series:
        raise ValueError(f"Invalid GCP Series URL: '{volume_url}'")

    series_id = m_series.group(1)

    s_data = fetch_gcp_api_json(f"https://www.comics.org/api/series/{series_id}/", timeout=2)
    if s_data and s_data.get("name"):
        series_name = s_data.get("name", "")
        issue_map = {}
        issues_list = []

        active_issues = s_data.get("active_issues", [])
        for iss_api_url in active_issues:
            m_iss = re.search(r"/issue/(\d+)", iss_api_url)
            if m_iss:
                iss_id = m_iss.group(1)
                web_url = f"https://www.comics.org/issue/{iss_id}/"
                i_data = fetch_gcp_api_json(iss_api_url, timeout=2)
                num = str(i_data.get("number", "")).strip().lstrip("#").lstrip("0") or "0"

                if num not in issue_map:
                    issue_map[num] = web_url
                    issues_list.append({
                        "number": num,
                        "label": f"Issue #{num}",
                        "url": web_url,
                        "id": iss_id
                    })

        issues_list = sorted(
            issues_list,
            key=lambda x: int(re.sub(r"\D", "", x["number"])) if re.sub(r"\D", "", x["number"]) else 0
        )
        return series_name, issue_map, issues_list

    html_text = fetch_gcp_html(volume_url, timeout=2)
    soup = BeautifulSoup(html_text, "html.parser")

    series_name = ""
    h1 = soup.find("h1")
    if h1:
        series_name = h1.get_text(" ", strip=True)

    if not series_name:
        series_name = f"GCP Series #{series_id}"

    issue_map = {}
    issues_list = []

    for a in soup.find_all("a", href=re.compile(r"/issue/\d+/")):
        href = a["href"]
        full_url = href if href.startswith("http") else "https://www.comics.org" + href
        txt = a.get_text(strip=True)
        m = re.search(r"#?(\d+[a-zA-Z]?|\d+\.\d+|\d+)", txt)
        if m:
            num = m.group(1).lstrip("0") or "0"
            if num not in issue_map:
                issue_map[num] = full_url
                issues_list.append({
                    "number": num,
                    "label": f"Issue #{num}",
                    "url": full_url
                })

    return series_name, issue_map, issues_list

def search_gcp(query: str, search_type: str = "all") -> list[dict]:
    """Searches Grand Comics Database for series or issues."""
    results = []
    clean_query = query.strip()
    if not clean_query:
        return results

    encoded_query = urllib.parse.quote_plus(clean_query)
    
    if search_type in ("all", "gcp_volume"):
        search_url = f"https://www.comics.org/search/advanced/process/?target=series&method=contains&series_name={encoded_query}"
        html_text = fetch_gcp_html(search_url, timeout=2)
        if html_text:
            soup = BeautifulSoup(html_text, "html.parser")
            for tr in soup.find_all("tr"):
                a = tr.find("a", href=re.compile(r"/series/\d+/"))
                if not a:
                    continue
                href = a["href"]
                full_url = href if href.startswith("http") else "https://www.comics.org" + href
                s_name = a.get_text(" ", strip=True)
                txt = " ".join(tr.get_text(" ", strip=True).split())

                m_year = re.search(r"\b(19\d\d|20\d\d)\b", txt)
                year_str = m_year.group(1) if m_year else ""

                m_issues = re.search(r"(\d+)\s+issues", txt, re.I)
                count_str = f"{m_issues.group(1)} issues" if m_issues else ""

                if s_name and full_url and not any(r["url"] == full_url for r in results):
                    results.append({
                        "title": s_name,
                        "url": full_url,
                        "image": "",
                        "type": "gcp_volume",
                        "type_label": "GCP Series",
                        "provider": "GCP",
                        "year": year_str,
                        "count": count_str,
                        "description": txt[:160]
                    })

    if search_type in ("all", "gcp_issue"):
        search_url = f"https://www.comics.org/search/advanced/process/?target=issue&method=contains&issue_name={encoded_query}"
        html_text = fetch_gcp_html(search_url, timeout=2)
        if html_text:
            soup = BeautifulSoup(html_text, "html.parser")
            for tr in soup.find_all("tr"):
                a = tr.find("a", href=re.compile(r"/issue/\d+/"))
                if not a:
                    continue
                href = a["href"]
                full_url = href if href.startswith("http") else "https://www.comics.org" + href
                i_name = a.get_text(" ", strip=True)
                txt = " ".join(tr.get_text(" ", strip=True).split())

                m_year = re.search(r"\b(19\d\d|20\d\d)\b", txt)
                year_str = m_year.group(1) if m_year else ""

                if i_name and full_url and not any(r["url"] == full_url for r in results):
                    results.append({
                        "title": i_name,
                        "url": full_url,
                        "image": "",
                        "type": "gcp_issue",
                        "type_label": "GCP Issue",
                        "provider": "GCP",
                        "year": year_str,
                        "count": "1 issue",
                        "description": txt[:160]
                    })

    return results

class GCPProvider(BaseProvider):
    """Grand Comics Database Provider implementing BaseProvider interface."""

    def get_name(self) -> str:
        return "GCP"

    def search_series(self, query: str) -> list[dict]:
        return search_gcp(query, search_type="gcp_volume")

    def search_issue(self, query: str) -> list[dict]:
        return search_gcp(query, search_type="gcp_issue")

    def lookup_volume(self, volume_id: str) -> tuple[str, dict[str, str], list[dict]]:
        url = volume_id if volume_id.startswith("http") else f"https://www.comics.org/series/{volume_id}/"
        return scrape_gcp_volume(url)

    def lookup_issue(self, issue_id_or_url: str) -> Optional[Comic]:
        url = issue_id_or_url if issue_id_or_url.startswith("http") else f"https://www.comics.org/issue/{issue_id_or_url}/"
        try:
            return scrape_gcp_issue(url)
        except Exception:
            return None
