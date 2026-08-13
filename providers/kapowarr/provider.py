import os
import re
import zipfile
from typing import Optional, Tuple, List
from models.comic import Comic
from models.identity import ComicIdentity
from providers.base import BaseProvider
from providers.kapowarr.client import KapowarrClient
from providers.kapowarr.models import KapowarrVolume, KapowarrIssue
from config import load_config
from cache.db import CacheManager

import time

class KapowarrProvider(BaseProvider):
    """
    Kapowarr metadata provider integration.
    Wraps KapowarrClient to convert API responses into application domain models.
    Phase 43: In-memory snapshot cache (60s TTL) for fast O(1) issue & series lookups.
    """

    def __init__(self, url: str = "http://localhost:5656", api_key: str = ""):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.client = KapowarrClient(url=url, api_key=api_key)
        self._snapshot_time: float = 0.0
        self._snapshot_ttl: float = 60.0  # 60 second cache for volume/issue library snapshot
        self._snapshot_volumes: List[KapowarrVolume] = []
        self._issue_index: dict[str, tuple[KapowarrVolume, KapowarrIssue]] = {}

    def get_library_snapshot(self, force_refresh: bool = False) -> List[KapowarrVolume]:
        """
        Phase 43: Returns cached library volumes snapshot and builds O(1) issue index.
        Avoids redundant REST API roundtrips during batch operations.
        """
        now = time.time()
        if not force_refresh and self._snapshot_volumes and (now - self._snapshot_time) < self._snapshot_ttl:
            return self._snapshot_volumes

        if not self.url:
            return []

        try:
            data = self.client.get("/api/volumes")
            series_list = data if isinstance(data, list) else []
            volumes = [KapowarrVolume.from_dict(s, base_url=self.url) for s in series_list]
            issue_idx = {}
            for vol in volumes:
                for iss in vol.issues:
                    if iss.id:
                        issue_idx[str(iss.id)] = (vol, iss)
            self._snapshot_volumes = volumes
            self._issue_index = issue_idx
            self._snapshot_time = now
        except Exception:
            pass

        return self._snapshot_volumes

    def get_name(self) -> str:
        return "Kapowarr"

    def test_connection(self) -> bool:
        """Tests connectivity to Kapowarr server."""
        if not self.url:
            return False
        try:
            res = self.client.get("/api/volumes")
            return res is not None
        except Exception:
            return False

    def search_series(self, query: str) -> list[dict]:
        """Searches monitored volumes/series in Kapowarr."""
        results = []
        if not self.url:
            return results

        try:
            params = {"query": query.strip()} if query.strip() else None
            data = self.client.get("/api/volumes", params=params)
            series_list = data if isinstance(data, list) else []

            for s in series_list:
                vol = KapowarrVolume.from_dict(s, base_url=self.url)
                results.append({
                    "title": vol.name,
                    "url": f"{self.url}/volume/{vol.id}",
                    "id": vol.id,
                    "cv_id": vol.comicvine_id,
                    "type": "kapowarr_volume",
                    "type_label": "Kapowarr Series",
                    "provider": "Kapowarr",
                    "year": str(vol.year) if vol.year else "",
                    "count": f"{vol.issue_count} issues",
                    "description": f"Kapowarr Volume ID #{vol.id}"
                })
        except Exception:
            pass

        return results

    def add_volume(self, cv_volume_id: str, folder_path: str = "") -> dict:
        """Adds a new comic volume to Kapowarr by ComicVine volume ID."""
        if not self.url:
            return {"error": "Kapowarr server URL not configured."}
        try:
            payload = {
                "comicvine_id": str(cv_volume_id),
                "folder": folder_path
            }
            res = self.client.post("/api/volumes", json_payload=payload)
            return {"success": True, "data": res}
        except Exception as e:
            return {"error": str(e)}

    def request_issue_download(self, issue_id: str = "", cv_volume_id: str = "", issue_title: str = "") -> dict:
        """Triggers Kapowarr search/download for a specific issue or volume."""
        if not self.url:
            return {"error": "Kapowarr server URL not configured."}
        try:
            if issue_id:
                res = self.client.post(f"/api/issue/{issue_id}/search")
                return {"success": True, "message": f"Triggered Kapowarr download search for issue '{issue_title or issue_id}'."}

            if cv_volume_id:
                res = self.add_volume(cv_volume_id)
                if res.get("success") or "already exists" in str(res.get("error", "")).lower():
                    return {"success": True, "message": f"Added series volume #{cv_volume_id} to Kapowarr & triggered issue search."}

            return {"error": "Kapowarr URL or Volume ID required to request download."}
        except Exception as e:
            return {"error": str(e)}

    def search_issue(self, query: str) -> list[dict]:
        """Phase 43: Searches issues inside monitored volumes using snapshot index."""
        results = []
        if not self.url or not query.strip():
            return results

        volumes = self.get_library_snapshot()
        clean_q = query.strip().lower()

        for vol in volumes:
            for i in vol.issues:
                if clean_q in i.title.lower() or clean_q in f"issue {i.issue_number}".lower() or clean_q in f"#{i.issue_number}".lower():
                    results.append({
                        "title": i.title or f"Issue #{i.issue_number}",
                        "url": i.web_url,
                        "id": i.id,
                        "cv_id": i.comicvine_id,
                        "type": "kapowarr_issue",
                        "type_label": "Kapowarr Issue",
                        "provider": "Kapowarr",
                        "year": "",
                        "count": "1 issue",
                        "description": f"Kapowarr Issue ID #{i.id}"
                    })

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
            data = self.client.get(f"/api/volumes/{s_id}")
            vol = KapowarrVolume.from_dict(data, base_url=self.url)
            series_name = vol.name or f"Kapowarr Volume #{s_id}"

            for iss in vol.issues:
                num = iss.issue_number.lstrip("0") or "0"
                if num not in issue_map:
                    issue_map[num] = iss.web_url
                    issues_list.append({
                        "number": num,
                        "label": f"Issue #{num}",
                        "url": iss.web_url,
                        "id": iss.id,
                        "cv_id": iss.comicvine_id
                    })

            issues_list = sorted(
                issues_list,
                key=lambda x: int(re.sub(r"\D", "", x["number"])) if re.sub(r"\D", "", x["number"]) else 0
            )
        except Exception:
            pass

        return series_name, issue_map, issues_list

    def lookup_issue(self, issue_id_or_url: str) -> Optional[Comic]:
        """Phase 43: Fast lookup of a Kapowarr issue using snapshot index with fallback."""
        m_id = re.search(r"(\d+)", str(issue_id_or_url))
        i_id = m_id.group(1) if m_id else str(issue_id_or_url)

        if not self.url or not i_id:
            return None

        # 1. Check snapshot index if available
        if self._issue_index and i_id in self._issue_index:
            vol, iss = self._issue_index[i_id]
            return self._build_comic_from_issue(vol, iss)

        # 2. Fallback: Search series / volumes individually if not in snapshot
        volumes = self.search_series("")
        for v in volumes:
            v_id = v["id"]
            try:
                data = self.client.get(f"/api/volumes/{v_id}")
                vol = KapowarrVolume.from_dict(data, base_url=self.url)
                for iss in vol.issues:
                    if str(iss.id) == str(i_id):
                        return self._build_comic_from_issue(vol, iss)
            except Exception:
                pass

        return None

    def _build_comic_from_issue(self, vol: KapowarrVolume, iss: KapowarrIssue) -> Comic:
        c = Comic()
        c.provider_name = "Kapowarr"
        c.provider_id = str(iss.id)
        c.web = iss.web_url
        c.title = iss.title
        c.number = iss.issue_number
        c.summary = iss.summary
        c.series = vol.name
        c.publisher = vol.publisher

        m_year = re.search(r"\b(19\d\d|20\d\d)\b", iss.release_date)
        if m_year:
            c.year = int(m_year.group(1))

        if iss.comicvine_id or vol.comicvine_id:
            c.notes = f"ComicVine ID: {iss.comicvine_id or vol.comicvine_id}"

        if not c.title and c.series:
            c.title = f"{c.series} #{c.number}" if c.number else c.series

        return c

    def get_library_status(self, prefer_kapowarr: bool = False) -> list[dict]:
        """Fetches Kapowarr library volumes AND scans local library directories for all comic series."""
        kapowarr_items = []
        local_items = []
        existing_paths = set()

        if self.url:
            try:
                data = self.client.get("/api/volumes")
                series_list = data if isinstance(data, list) else []

                for s in series_list:
                    vol = KapowarrVolume.from_dict(s, base_url=self.url)
                    if vol.folder_path:
                        existing_paths.add(os.path.realpath(vol.folder_path))

                    total_files = 0
                    tagged_count = 0
                    missing_count = 0

                    if vol.folder_path and os.path.exists(vol.folder_path) and os.path.isdir(vol.folder_path):
                        for root, _, files in os.walk(vol.folder_path):
                            for f in files:
                                if f.lower().endswith((".cbz", ".cbr")):
                                    total_files += 1
                                    full_f = os.path.join(root, f)
                                    if f.lower().endswith(".cbz"):
                                        try:
                                            with zipfile.ZipFile(full_f, 'r') as zf:
                                                names = [name.lower() for name in zf.namelist()]
                                                if "comicinfo.xml" in names:
                                                    tagged_count += 1
                                                else:
                                                    missing_count += 1
                                        except Exception:
                                            missing_count += 1
                                    else:
                                        missing_count += 1
                    else:
                        missing_count = vol.issue_count

                    kapowarr_items.append({
                        "id": vol.id,
                        "title": vol.name,
                        "year": str(vol.year) if vol.year else "",
                        "cv_id": vol.comicvine_id,
                        "url": f"{self.url}/volume/{vol.id}",
                        "cv_url": f"https://comicvine.gamespot.com/volume/4050-{vol.comicvine_id}/" if vol.comicvine_id else "",
                        "folder_path": vol.folder_path,
                        "issue_count": vol.issue_count,
                        "total_files": total_files,
                        "tagged_count": tagged_count,
                        "missing_count": missing_count,
                        "has_missing": missing_count > 0,
                        "is_complete": tagged_count > 0 and missing_count == 0,
                        "source": "kapowarr",
                        "status_label": f"{tagged_count}/{total_files} Tagged ({missing_count} Missing)" if total_files > 0 else f"Folder Not Scanned ({vol.issue_count} issues)"
                    })
            except Exception:
                pass

        library_dir = "/mnt/disk1/Comics"

        if os.path.exists(library_dir):
            local_idx = 1
            for root, dirs, files in os.walk(library_dir):
                cbz_cbr_files = [f for f in files if f.lower().endswith((".cbz", ".cbr"))]
                if not cbz_cbr_files:
                    continue

                real_root = os.path.realpath(root)
                if real_root in existing_paths:
                    continue
                existing_paths.add(real_root)

                rel_path = os.path.relpath(root, library_dir)
                parts = rel_path.split(os.sep)
                series_title = parts[0]
                if len(parts) > 1 and "volume" in parts[1].lower():
                    series_title = f"{parts[0]} - {parts[1]}"
                elif len(parts) > 1:
                    series_title = f"{parts[0]} ({parts[1]})"

                total_files = len(cbz_cbr_files)
                tagged_count = 0
                missing_count = 0

                for f in cbz_cbr_files:
                    full_f = os.path.join(root, f)
                    if f.lower().endswith(".cbz"):
                        try:
                            with zipfile.ZipFile(full_f, 'r') as zf:
                                if "comicinfo.xml" in [n.lower() for n in zf.namelist()]:
                                    tagged_count += 1
                                else:
                                    missing_count += 1
                        except Exception:
                            missing_count += 1
                    else:
                        missing_count += 1

                local_items.append({
                    "id": f"local_{local_idx}",
                    "title": series_title,
                    "year": "",
                    "cv_id": "",
                    "url": "",
                    "cv_url": "",
                    "folder_path": root,
                    "issue_count": total_files,
                    "total_files": total_files,
                    "tagged_count": tagged_count,
                    "missing_count": missing_count,
                    "has_missing": missing_count > 0,
                    "is_complete": tagged_count > 0 and missing_count == 0,
                    "source": "local",
                    "status_label": f"{tagged_count}/{total_files} Tagged ({missing_count} Missing)"
                })
                local_idx += 1

        final_items = (kapowarr_items + local_items) if prefer_kapowarr else (local_items + kapowarr_items)

        if final_items:
            try:
                cfg = load_config()
                cache_mgr = CacheManager(cfg.cache.db_path)
                cache_mgr.save_cached_search("Kapowarr", "library", f"all_prefer_{prefer_kapowarr}", final_items)
                for item in final_items:
                    if item.get("title") and item.get("id"):
                        cache_mgr.save_cached_series(
                            item.get("source", "kapowarr"),
                            str(item.get("id")),
                            item.get("title", ""),
                            int(item.get("year")) if str(item.get("year", "")).isdigit() else 0,
                            "",
                            item
                        )
            except Exception:
                pass

        return final_items
