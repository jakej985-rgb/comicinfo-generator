import re
import urllib.parse
from typing import Optional, Tuple, List, Dict
from bs4 import BeautifulSoup
from models.comic import Comic
from providers.base import BaseProvider
from providers.gcd.client import GCDClient
from providers.gcd.parser import parse_gcp_text_refined, parse_gcd_soup, clean_creator_name
from config import load_config
from cache.db import CacheManager

class GCPProvider(BaseProvider):
    """Grand Comics Database Provider implementing BaseProvider interface."""

    def __init__(self, timeout: int = 4):
        self.client = GCDClient(timeout=timeout)

    def get_name(self) -> str:
        return "GCP"

    def search_series(self, query: str) -> list[dict]:
        return self._search_gcp(query, search_type="gcp_volume")

    def search_issue(self, query: str) -> list[dict]:
        return self._search_gcp(query, search_type="gcp_issue")

    def lookup_volume(self, volume_id: str) -> tuple[str, dict[str, str], list[dict]]:
        url = volume_id if volume_id.startswith("http") else f"https://www.comics.org/series/{volume_id}/"
        return self._scrape_volume(url)

    def lookup_issue(self, issue_id_or_url: str) -> Optional[Comic]:
        url = issue_id_or_url if issue_id_or_url.startswith("http") else f"https://www.comics.org/issue/{issue_id_or_url}/"
        return self._scrape_issue(url)

    def _scrape_issue(self, url_or_text: str, use_cache: bool = True) -> Comic:
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

        api_data = self.client.fetch_api_json(f"https://www.comics.org/api/issue/{issue_id}/")
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
                s_data = self.client.fetch_api_json(series_api)
                if s_data:
                    c.series = s_data.get("name", "")
                    pub_api = s_data.get("publisher")
                    if pub_api:
                        p_data = self.client.fetch_api_json(pub_api)
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

        html_text = self.client.fetch_html(url)
        if html_text:
            res_c = parse_gcp_text_refined(html_text, url)
            if res_c.series and res_c.series != "Grand Comics Database Issue":
                if not res_c.summary:
                    res_c.summary = "Scraped Series, Publisher & Date from archive."
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
        c.summary = f"Metadata generated for GCP Issue #{issue_id} ({url})."
        if use_cache:
            try:
                cfg = load_config()
                cache_mgr = CacheManager(cfg.cache.db_path)
                cache_mgr.save_cached_issue("GCP", url, c)
            except Exception:
                pass

        return c

    def _scrape_volume(self, volume_url: str) -> tuple[str, dict[str, str], list[dict]]:
        m_series = re.search(r"/series/(\d+)", volume_url)
        if not m_series:
            raise ValueError(f"Invalid GCP Series URL: '{volume_url}'")

        series_id = m_series.group(1)
        s_data = self.client.fetch_api_json(f"https://www.comics.org/api/series/{series_id}/")
        if s_data and s_data.get("name"):
            series_name = s_data.get("name", "")
            issue_map = {}
            issues_list = []

            for iss_api_url in s_data.get("active_issues", []):
                m_iss = re.search(r"/issue/(\d+)", iss_api_url)
                if m_iss:
                    iss_id = m_iss.group(1)
                    web_url = f"https://www.comics.org/issue/{iss_id}/"
                    i_data = self.client.fetch_api_json(iss_api_url)
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

        html_text = self.client.fetch_html(volume_url)
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

    def _search_gcp(self, query: str, search_type: str = "all") -> list[dict]:
        results = []
        clean_query = query.strip()
        if not clean_query:
            return results

        encoded_query = urllib.parse.quote_plus(clean_query)

        if search_type in ("all", "gcp_volume"):
            search_url = f"https://www.comics.org/search/advanced/process/?target=series&method=contains&series_name={encoded_query}"
            html_text = self.client.fetch_html(search_url)
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
            html_text = self.client.fetch_html(search_url)
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
