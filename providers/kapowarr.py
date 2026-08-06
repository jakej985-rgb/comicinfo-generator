import requests
import re
import urllib.parse
from typing import Optional, Tuple
from models.comic import Comic
from providers.base import BaseProvider

class KapowarrProvider(BaseProvider):
    """
    Kapowarr metadata provider integration.
    Communicates with Kapowarr REST API to fetch series & issue details.
    """

    def __init__(self, url: str = "http://localhost:5656", api_key: str = ""):
        self.url = url.rstrip("/")
        self.api_key = api_key

    def get_name(self) -> str:
        return "Kapowarr"

    def _get_headers(self) -> dict:
        headers = {
            "Accept": "application/json",
            "User-Agent": "ComicInfoGenerator/2.0"
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def test_connection(self) -> bool:
        """Tests connectivity to Kapowarr server."""
        if not self.url:
            return False
        try:
            r = requests.get(f"{self.url}/api/v1/system/status", headers=self._get_headers(), timeout=4)
            if r.status_code == 200:
                return True
            # Fallback check series endpoint
            r2 = requests.get(f"{self.url}/api/v1/series", headers=self._get_headers(), timeout=4)
            return r2.status_code in (200, 401)
        except Exception:
            return False

    def search_series(self, query: str) -> list[dict]:
        """Searches monitored series in Kapowarr."""
        results = []
        if not self.url or not query.strip():
            return results

        try:
            encoded = urllib.parse.quote(query.strip())
            r = requests.get(f"{self.url}/api/v1/series?name={encoded}", headers=self._get_headers(), timeout=5)
            if r.status_code == 200:
                data = r.json()
                series_list = data if isinstance(data, list) else data.get("results", [])
                for s in series_list:
                    s_id = str(s.get("id", ""))
                    s_name = s.get("name") or s.get("title", "")
                    s_year = str(s.get("year", ""))
                    results.append({
                        "title": s_name,
                        "url": f"{self.url}/series/{s_id}",
                        "id": s_id,
                        "cv_id": str(s.get("comicvine_id", "") or s.get("cv_id", "")),
                        "type": "kapowarr_volume",
                        "type_label": "Kapowarr Series",
                        "provider": "Kapowarr",
                        "year": s_year,
                        "count": f"{s.get('issue_count', 0)} issues",
                        "description": f"Kapowarr Series ID #{s_id}"
                    })
        except Exception:
            pass

        return results

    def search_issue(self, query: str) -> list[dict]:
        """Searches issues in Kapowarr."""
        results = []
        if not self.url or not query.strip():
            return results

        try:
            encoded = urllib.parse.quote(query.strip())
            r = requests.get(f"{self.url}/api/v1/issue?name={encoded}", headers=self._get_headers(), timeout=5)
            if r.status_code == 200:
                data = r.json()
                issue_list = data if isinstance(data, list) else data.get("results", [])
                for i in issue_list:
                    i_id = str(i.get("id", ""))
                    i_title = i.get("title") or i.get("name", "")
                    i_num = str(i.get("number", "") or i.get("issue_number", ""))
                    results.append({
                        "title": i_title or f"Issue #{i_num}",
                        "url": f"{self.url}/issue/{i_id}",
                        "id": i_id,
                        "cv_id": str(i.get("comicvine_id", "") or i.get("cv_id", "")),
                        "type": "kapowarr_issue",
                        "type_label": "Kapowarr Issue",
                        "provider": "Kapowarr",
                        "year": "",
                        "count": "1 issue",
                        "description": f"Kapowarr Issue ID #{i_id}"
                    })
        except Exception:
            pass

        return results

    def lookup_volume(self, volume_id: str) -> tuple[str, dict[str, str], list[dict]]:
        """Looks up a Kapowarr series by ID or URL."""
        m_id = re.search(r"(\d+)", str(volume_id))
        s_id = m_id.group(1) if m_id else str(volume_id)

        series_name = ""
        issue_map = {}
        issues_list = []

        if not self.url or not s_id:
            return series_name, issue_map, issues_list

        try:
            r = requests.get(f"{self.url}/api/v1/series/{s_id}", headers=self._get_headers(), timeout=5)
            if r.status_code == 200:
                data = r.json()
                series_name = data.get("name") or data.get("title") or f"Kapowarr Series #{s_id}"
                
                issues = data.get("issues", [])
                if not issues:
                    # Fetch issues sub-endpoint
                    r_iss = requests.get(f"{self.url}/api/v1/series/{s_id}/issues", headers=self._get_headers(), timeout=5)
                    if r_iss.status_code == 200:
                        issues = r_iss.json()

                for iss in issues:
                    num = str(iss.get("issue_number") or iss.get("number", "")).strip().lstrip("#").lstrip("0") or "0"
                    iss_id = str(iss.get("id", ""))
                    web_url = f"{self.url}/issue/{iss_id}"
                    if num not in issue_map:
                        issue_map[num] = web_url
                        issues_list.append({
                            "number": num,
                            "label": f"Issue #{num}",
                            "url": web_url,
                            "id": iss_id,
                            "cv_id": str(iss.get("comicvine_id", "") or iss.get("cv_id", ""))
                        })

                issues_list = sorted(
                    issues_list,
                    key=lambda x: int(re.sub(r"\D", "", x["number"])) if re.sub(r"\D", "", x["number"]) else 0
                )
        except Exception:
            pass

        return series_name, issue_map, issues_list

    def lookup_issue(self, issue_id_or_url: str) -> Optional[Comic]:
        """Looks up a Kapowarr issue and returns a normalized Comic object or None."""
        m_id = re.search(r"(\d+)", str(issue_id_or_url))
        i_id = m_id.group(1) if m_id else str(issue_id_or_url)

        if not self.url or not i_id:
            return None

        try:
            r = requests.get(f"{self.url}/api/v1/issue/{i_id}", headers=self._get_headers(), timeout=5)
            if r.status_code != 200:
                return None

            data = r.json()
            if not data or not data.get("id"):
                return None

            c = Comic()
            c.provider_name = "Kapowarr"
            c.provider_id = str(data.get("id"))
            c.web = f"{self.url}/issue/{i_id}"
            
            c.title = data.get("title") or data.get("name") or ""
            c.number = str(data.get("issue_number") or data.get("number", "")).strip().lstrip("#")
            c.summary = data.get("summary") or data.get("overview") or ""

            # Year/Date
            rel_date = str(data.get("release_date") or data.get("date") or "")
            m_year = re.search(r"\b(19\d\d|20\d\d)\b", rel_date)
            if m_year:
                c.year = int(m_year.group(1))

            # Series info
            series_info = data.get("series", {})
            if isinstance(series_info, dict):
                c.series = series_info.get("name") or series_info.get("title") or ""
                c.publisher = series_info.get("publisher", "")
            elif isinstance(series_info, str):
                c.series = series_info

            # ComicVine ID cross-reference tag
            cv_id = data.get("comicvine_id") or data.get("cv_id")
            if cv_id:
                c.notes = f"ComicVine ID: {cv_id}"

            if not c.title and c.series:
                c.title = f"{c.series} #{c.number}" if c.number else c.series

            return c
        except Exception:
            return None
