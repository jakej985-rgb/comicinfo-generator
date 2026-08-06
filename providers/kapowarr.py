import requests
import re
import urllib.parse
from typing import Optional, Tuple
from models.comic import Comic
from providers.base import BaseProvider

class KapowarrProvider(BaseProvider):
    """
    Kapowarr metadata provider integration.
    Communicates with Kapowarr REST API (/api/volumes, /api/system/tasks).
    """

    def __init__(self, url: str = "http://localhost:5656", api_key: str = ""):
        self.url = url.rstrip("/")
        self.api_key = api_key

    def get_name(self) -> str:
        return "Kapowarr"

    def _get_params(self, extra_params: Optional[dict] = None) -> dict:
        params = {}
        if self.api_key:
            params["api_key"] = self.api_key
            params["apikey"] = self.api_key
        if extra_params:
            params.update(extra_params)
        return params

    def _get_headers(self) -> dict:
        headers = {
            "Accept": "application/json",
            "User-Agent": "ComicInfoGenerator/2.0"
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
            headers["apikey"] = self.api_key
        return headers

    def test_connection(self) -> bool:
        """Tests connectivity to Kapowarr server via /api/volumes or /api/system/tasks."""
        if not self.url:
            return False
        try:
            r = requests.get(f"{self.url}/api/volumes", headers=self._get_headers(), params=self._get_params(), timeout=4)
            if r.status_code == 200:
                return True
            r2 = requests.get(f"{self.url}/api/system/tasks", headers=self._get_headers(), params=self._get_params(), timeout=4)
            return r2.status_code in (200, 401)
        except Exception:
            return False

    def search_series(self, query: str) -> list[dict]:
        """Searches monitored volumes/series in Kapowarr."""
        results = []
        if not self.url:
            return results

        try:
            params = self._get_params({"query": query.strip()} if query.strip() else None)
            r = requests.get(f"{self.url}/api/volumes", headers=self._get_headers(), params=params, timeout=5)
            if r.status_code == 200:
                resp_json = r.json()
                data = resp_json.get("result", resp_json) if isinstance(resp_json, dict) else resp_json
                series_list = data if isinstance(data, list) else []

                for s in series_list:
                    s_id = str(s.get("id", ""))
                    s_name = s.get("name") or s.get("title", "")
                    s_year = str(s.get("year", ""))
                    results.append({
                        "title": s_name,
                        "url": f"{self.url}/volume/{s_id}",
                        "id": s_id,
                        "cv_id": str(s.get("comicvine_id", "") or s.get("cv_id", "")),
                        "type": "kapowarr_volume",
                        "type_label": "Kapowarr Series",
                        "provider": "Kapowarr",
                        "year": s_year,
                        "count": f"{s.get('issue_count', 0)} issues",
                        "description": f"Kapowarr Volume ID #{s_id}"
                    })
        except Exception:
            pass

        return results

    def search_issue(self, query: str) -> list[dict]:
        """Searches issues inside monitored volumes in Kapowarr."""
        results = []
        if not self.url or not query.strip():
            return results

        # Fetch volumes and filter issues matching query
        volumes = self.search_series("")
        clean_q = query.strip().lower()
        
        for v in volumes:
            v_id = v["id"]
            try:
                r = requests.get(f"{self.url}/api/volumes/{v_id}", headers=self._get_headers(), params=self._get_params(), timeout=5)
                if r.status_code == 200:
                    resp_json = r.json()
                    v_data = resp_json.get("result", resp_json) if isinstance(resp_json, dict) else resp_json
                    issues = v_data.get("issues", [])
                    for i in issues:
                        i_id = str(i.get("id", ""))
                        i_num = str(i.get("issue_number") or i.get("number", ""))
                        i_name = i.get("name") or i.get("title", "") or f"Issue #{i_num}"
                        
                        if clean_q in i_name.lower() or clean_q in f"issue {i_num}".lower() or clean_q in f"#{i_num}".lower():
                            results.append({
                                "title": i_name,
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

    def lookup_volume(self, volume_id: str) -> Tuple[str, dict[str, str], list[dict]]:
        """Looks up a Kapowarr volume/series by ID."""
        m_id = re.search(r"(\d+)", str(volume_id))
        s_id = m_id.group(1) if m_id else str(volume_id)

        series_name = ""
        issue_map = {}
        issues_list = []

        if not self.url or not s_id:
            return series_name, issue_map, issues_list

        try:
            r = requests.get(f"{self.url}/api/volumes/{s_id}", headers=self._get_headers(), params=self._get_params(), timeout=5)
            if r.status_code == 200:
                resp_json = r.json()
                data = resp_json.get("result", resp_json) if isinstance(resp_json, dict) else resp_json
                series_name = data.get("name") or data.get("title") or f"Kapowarr Volume #{s_id}"
                
                issues = data.get("issues", [])
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

        # Fetch volumes to locate issue details
        volumes = self.search_series("")
        for v in volumes:
            v_id = v["id"]
            try:
                r = requests.get(f"{self.url}/api/volumes/{v_id}", headers=self._get_headers(), params=self._get_params(), timeout=5)
                if r.status_code == 200:
                    resp_json = r.json()
                    v_data = resp_json.get("result", resp_json) if isinstance(resp_json, dict) else resp_json
                    for iss in v_data.get("issues", []):
                        if str(iss.get("id")) == str(i_id):
                            c = Comic()
                            c.provider_name = "Kapowarr"
                            c.provider_id = str(i_id)
                            c.web = f"{self.url}/issue/{i_id}"
                            c.title = iss.get("name") or iss.get("title") or ""
                            c.number = str(iss.get("issue_number") or iss.get("number", "")).strip().lstrip("#")
                            c.summary = iss.get("summary") or iss.get("overview") or ""
                            c.series = v_data.get("name") or v_data.get("title") or ""
                            c.publisher = v_data.get("publisher", "")

                            rel_date = str(iss.get("release_date") or iss.get("date") or "")
                            m_year = re.search(r"\b(19\d\d|20\d\d)\b", rel_date)
                            if m_year:
                                c.year = int(m_year.group(1))

                            cv_id = iss.get("comicvine_id") or iss.get("cv_id") or v_data.get("comicvine_id")
                            if cv_id:
                                c.notes = f"ComicVine ID: {cv_id}"

                            if not c.title and c.series:
                                c.title = f"{c.series} #{c.number}" if c.number else c.series

                            return c
            except Exception:
                pass

        return None
