import base64
import cgi
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import yaml
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

repo_dir = os.path.dirname(os.path.abspath(__file__))
if repo_dir not in sys.path:
    sys.path.insert(0, repo_dir)

from models.comic import Comic, merge_comics
from config import load_config, init_config, DEFAULT_CONFIG_PATH
from cache.db import CacheManager
from providers.kapowarr import KapowarrProvider
from providers.comicvine import scrape_issue as scrape_cv_issue, scrape_volume as scrape_cv_volume, search_comicvine, ComicVineProvider
from providers.gcp import scrape_gcp_issue, scrape_gcp_volume, search_gcp, GCPProvider
from providers.story_arc import search_story_arcs, get_story_arc_details, parse_custom_chronological_reading_order, MARVEL_ZOMBIES_PRESET_TEXT
from writers.archive import embed_comicinfo_in_cbz
from writers.comicinfo import write_xml, generate_xml_bytes
from converters.cbr_to_cbz import convert_cbr_to_cbz
from automation.watcher import LibraryWatcher
from automation.queue import ProcessingQueue
from pipeline.resolver import MetadataResolver, read_existing_comicinfo


PORT = 5005
STATIC_DIR = os.path.join(repo_dir, "static")

# Global Watcher state for Web UI
global_watcher: Optional[LibraryWatcher] = None
global_watcher_folder: str = ""

def comic_to_dict(c: Comic) -> dict:
    return {
        "title": c.title,
        "series": c.series,
        "number": c.number,
        "volume": c.volume,
        "count": c.count,
        "summary": c.summary,
        "notes": c.notes,
        "year": c.year,
        "month": c.month,
        "day": c.day,
        "publisher": c.publisher,
        "genre": c.genre,
        "web": c.web,
        "language": c.language,
        "format": c.format,
        "writers": c.writers,
        "pencillers": c.pencillers,
        "inkers": c.inkers,
        "colorists": c.colorists,
        "letterers": c.letterers,
        "cover_artists": c.cover_artists,
        "characters": c.characters,
        "teams": c.teams,
        "story_arcs": c.story_arcs,
        "story_arc_numbers": c.story_arc_numbers,
    }

def dict_to_comic(d: dict) -> Comic:
    c = Comic()
    c.title = str(d.get("title", ""))
    c.series = str(d.get("series", ""))
    c.number = str(d.get("number", ""))
    c.volume = str(d.get("volume", ""))
    c.count = int(d.get("count") or 1)
    c.summary = str(d.get("summary", ""))
    c.notes = str(d.get("notes", ""))
    c.year = int(d.get("year") or 0)
    c.month = int(d.get("month") or 0)
    c.day = int(d.get("day") or 0)
    c.publisher = str(d.get("publisher", ""))
    c.genre = str(d.get("genre", ""))
    c.web = str(d.get("web", ""))
    c.language = str(d.get("language", "en"))
    c.format = str(d.get("format", "Comic"))

    def to_list(val):
        if isinstance(val, list):
            return [str(v).strip() for v in val if str(v).strip()]
        if isinstance(val, str) and val.strip():
            return [v.strip() for v in val.split(",") if v.strip()]
        return []

    c.writers = to_list(d.get("writers"))
    c.pencillers = to_list(d.get("pencillers"))
    c.inkers = to_list(d.get("inkers"))
    c.colorists = to_list(d.get("colorists"))
    c.letterers = to_list(d.get("letterers"))
    c.cover_artists = to_list(d.get("cover_artists"))
    c.characters = to_list(d.get("characters"))
    c.teams = to_list(d.get("teams"))
    c.story_arcs = to_list(d.get("story_arcs"))
    c.story_arc_numbers = to_list(d.get("story_arc_numbers"))
    c.provider_name = str(d.get("provider_name") or d.get("provider") or "")
    return c

def detect_provider(url: str) -> str:
    """Returns 'Kapowarr' if Kapowarr URL/ID, 'GCP' if comics.org or GCP layout, otherwise 'CV'."""
    url_lower = url.lower()
    try:
        cfg = load_config()
        kap_base = cfg.kapowarr.url.lower().rstrip("/") if cfg.kapowarr.url else ""
        if kap_base and kap_base in url_lower:
            return "Kapowarr"
    except Exception:
        pass
    if "comics.org" in url_lower or any(k in url for k in ["Pencils:", "Script:", "Characters:", "Table of Contents"]):
        return "GCP"
    return "CV"

def scrape_single_url(url_or_text: str) -> Comic:
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

def scrape_any_volume(url: str) -> tuple[str, dict[str, str], list[dict]]:
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
    if isinstance(url_val, str) and (any(k in url_val for k in ["Pencils:", "Script:", "Characters:", "Table of Contents"]) or ("comics.org" in url_val and len(url_val.split("\n")) > 2)):
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
            urls = [u.strip() for u in re.split(r"[\n,\s]+", url_val) if u.strip() and u.strip().startswith("http")]

    if not urls:
        if isinstance(url_val, str) and url_val.strip():
            return scrape_single_url(url_val.strip())
        raise ValueError("No valid comic database URLs or page text provided.")

    if len(urls) == 1:
        return scrape_single_url(urls[0])

    comics = [scrape_single_url(u) for u in urls]
    return merge_comics(comics)

def search_all_providers(query: str, search_type: str = "all") -> tuple[list[dict], bool]:
    results = []
    kapowarr_active = False

    # 1. Kapowarr Library Search
    try:
        cfg = load_config()
        if cfg.kapowarr.url and cfg.kapowarr.api_key:
            kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
            if kap.test_connection():
                kapowarr_active = True
                if search_type in ("all", "kapowarr", "kapowarr_volume", "kapowarr_issue"):
                    if search_type in ("all", "kapowarr", "kapowarr_volume"):
                        kap_vols = kap.search_series(query)
                        for r in kap_vols:
                            r["provider"] = "Kapowarr"
                            results.append(r)
                    if search_type in ("all", "kapowarr", "kapowarr_issue"):
                        kap_issues = kap.search_issue(query)
                        for r in kap_issues:
                            r["provider"] = "Kapowarr"
                            results.append(r)
    except Exception:
        pass

    # 2. Comic Vine Search
    if search_type in ("all", "scrapers", "cv_volume", "cv_issue"):
        cv_type = "all"
        if search_type == "cv_volume": cv_type = "volume"
        elif search_type == "cv_issue": cv_type = "issue"
        
        cv_results = search_comicvine(query, cv_type)
        for r in cv_results:
            r["provider"] = "CV"
            if r["type"] == "volume":
                r["type"] = "cv_volume"
                r["type_label"] = "CV Series"
            else:
                r["type"] = "cv_issue"
                r["type_label"] = "CV Issue"
            results.append(r)

    # 3. Grand Comics Database Search
    if search_type in ("all", "scrapers", "gcp_volume", "gcp_issue"):
        gcp_results = search_gcp(query, search_type)
        for r in gcp_results:
            r["provider"] = "GCP"
            results.append(r)

    return results, kapowarr_active


def extract_issue_num_from_filename(filename: str) -> str:
    fname = re.sub(r"\.(cbz|cbr|zip|rar)$", "", filename, flags=re.I)

    # 1. Handle half issues: 00½, 0½, ½, 1/2, 0.5
    m_half = re.search(r"(?:issue\s*#?|#|\b)0*(?:½|1/2|0\.5)\b", fname, re.I)
    if m_half or "½" in fname or "1/2" in fname:
        return "0.5"

    # 2. Check for Issue #000 / #0
    m_zero = re.search(r"\bissue\s*#?\s*(0+)(?!\d)", fname, re.I)
    if m_zero:
        return "0"
    m_zero_hash = re.search(r"#\s*(0+)(?!\d)", fname)
    if m_zero_hash:
        return "0"

    # 3. Standard issue number matching
    m = re.search(r"\bissue\s*#?\s*0*(\d+[a-zA-Z]?|\d+\.\d+|\d+)", fname, re.I)
    if m:
        return m.group(1)

    m = re.search(r"#\s*0*(\d+[a-zA-Z]?|\d+\.\d+|\d+)", fname)
    if m:
        return m.group(1)

    m = re.search(r"\bv(\d+)\b", fname, re.I)
    if m:
        fname = fname.replace(m.group(0), "")

    m = re.search(r"\b(19\d\d|20\d\d)\b", fname)
    if m:
        fname = fname.replace(m.group(0), "")

    m = re.search(r"\b0+(?!\d)", fname)
    if m:
        return "0"

    m = re.search(r"0*(\d+)\b", fname)
    if m:
        return m.group(1)

    return ""


def open_native_file_picker() -> str:
    try:
        zenity_path = shutil.which("zenity")
        if zenity_path:
            res = subprocess.run(
                [zenity_path, "--file-selection", "--title=Select Comic Archive (.cbz or .cbr)", "--file-filter=Comic Archives (*.cbz *.cbr) | *.cbz *.cbr"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()

        kdialog_path = shutil.which("kdialog")
        if kdialog_path:
            res = subprocess.run(
                [kdialog_path, "--getopenfilename", os.path.expanduser("~"), "*.cbz *.cbr|Comic Archives (*.cbz *.cbr)"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
    except Exception:
        pass
    return ""

def open_native_folder_picker() -> str:
    try:
        zenity_path = shutil.which("zenity")
        if zenity_path:
            res = subprocess.run(
                [zenity_path, "--file-selection", "--directory", "--title=Select Comics Folder Directory"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()

        kdialog_path = shutil.which("kdialog")
        if kdialog_path:
            res = subprocess.run(
                [kdialog_path, "--getexistingdirectory", os.path.expanduser("~")],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
    except Exception:
        pass
    return ""

def find_file_path(path_str: str) -> str:
    if os.path.exists(path_str):
        return path_str

    filename = os.path.basename(path_str)
    search_dirs = [
        os.getcwd(),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Comics"),
        os.path.expanduser("~"),
        "/media/m3tal",
        "/mnt"
    ]

    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        candidate = os.path.join(sdir, filename)
        if os.path.exists(candidate):
            return candidate

    return ""

class ComicServerHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(200)

    def do_GET(self):
        global global_watcher, global_watcher_folder
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            file_path = os.path.join(STATIC_DIR, "index.html")
            content_type = "text/html; charset=utf-8"
        elif path == "/style.css":
            file_path = os.path.join(STATIC_DIR, "style.css")
            content_type = "text/css; charset=utf-8"
        elif path == "/app.js":
            file_path = os.path.join(STATIC_DIR, "app.js")
            content_type = "application/javascript; charset=utf-8"
        elif path == "/api/config":
            cfg = load_config()
            self._set_headers(200)
            self.wfile.write(json.dumps({
                "success": True,
                "config": {
                    "comicvine": {"api_key": cfg.comicvine.api_key},
                    "kapowarr": {"url": cfg.kapowarr.url, "api_key": cfg.kapowarr.api_key},
                    "automation": {"mode": cfg.automation.mode, "workers": cfg.automation.workers, "watch_folder": cfg.automation.watch_folder, "prefer_kapowarr": cfg.automation.prefer_kapowarr},
                    "cache": {"enabled": cfg.cache.enabled, "db_path": cfg.cache.db_path},
                    "output": {"embed_xml": cfg.output.embed_xml, "overwrite": cfg.output.overwrite, "delete_cbr": cfg.output.delete_cbr},
                    "logging": {"level": cfg.logging.level, "log_file": cfg.logging.log_file}
                }
            }).encode("utf-8"))
            return
        elif path == "/api/kapowarr/library":
            try:
                cfg = load_config()
                kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
                items = kap.get_library_status(watch_folder=cfg.automation.watch_folder, prefer_kapowarr=cfg.automation.prefer_kapowarr)
                self._set_headers(200)
                self.wfile.write(json.dumps({"online": kap.test_connection(), "items": items}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return
        elif path == "/api/kapowarr/series-issues":
            query_params = parse_qs(parsed.query)
            series_id = query_params.get("id", [""])[0] or query_params.get("series_id", [""])[0]
            series_url = query_params.get("url", [""])[0]
            folder_path = query_params.get("folder_path", [""])[0]

            try:
                cfg = load_config()
                series_name = ""
                issues_list = []

                if series_url or series_id:
                    target_url = series_url or f"{cfg.kapowarr.url}/volume/{series_id}"
                    series_name, _, issues_list = scrape_any_volume(target_url)

                if folder_path and os.path.exists(folder_path):
                    local_files = [f for f in os.listdir(folder_path) if f.lower().endswith((".cbz", ".cbr"))]
                    for iss in issues_list:
                        num = str(iss.get("number", ""))
                        matched_file = None
                        is_tagged = False
                        for f in local_files:
                            ext_num = extract_issue_num_from_filename(f)
                            if ext_num == num or ext_num.lstrip("0") == num.lstrip("0"):
                                matched_file = f
                                full_f = os.path.join(folder_path, f)
                                if f.lower().endswith(".cbz"):
                                    try:
                                        with zipfile.ZipFile(full_f, 'r') as zf:
                                            if "comicinfo.xml" in [name.lower() for name in zf.namelist()]:
                                                is_tagged = True
                                    except Exception:
                                        pass
                                break
                        iss["matched_file"] = matched_file
                        iss["is_tagged"] = is_tagged
                        iss["file_path"] = os.path.join(folder_path, matched_file) if matched_file else ""

                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "series_name": series_name,
                    "count": len(issues_list),
                    "issues": issues_list
                }).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return
        elif path == "/api/story-arc/search":
            query_params = parse_qs(parsed.query)
            q = query_params.get("q", [""])[0] or query_params.get("query", [""])[0]
            try:
                cfg = load_config()
                arcs = search_story_arcs(q, api_key=cfg.comicvine.api_key)
                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "count": len(arcs), "story_arcs": arcs}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return
        elif path == "/api/story-arc/detail":
            query_params = parse_qs(parsed.query)
            arc_url = query_params.get("url", [""])[0]
            try:
                cfg = load_config()
                details = get_story_arc_details(arc_url, watch_folder=cfg.automation.watch_folder)
                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "data": details}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return
        elif path == "/api/watch/status":
            is_active = global_watcher is not None and global_watcher.observer is not None and global_watcher.observer.is_alive()
            self._set_headers(200)
            self.wfile.write(json.dumps({
                "success": True,
                "is_active": is_active,
                "watch_folder": global_watcher_folder
            }).encode("utf-8"))
            return
        elif path == "/api/cache/stats":
            cfg = load_config()
            cache_mgr = CacheManager(cfg.cache.db_path)
            stats = cache_mgr.get_stats()
            self._set_headers(200)
            self.wfile.write(json.dumps({"success": True, "stats": stats}).encode("utf-8"))
            return
        else:
            self._set_headers(404, "text/plain")
            self.wfile.write(b"404 Not Found")
            return

        if os.path.exists(file_path):
            self._set_headers(200, content_type)
            with open(file_path, "rb") as f:
                self.wfile.write(f.read())
        else:
            self._set_headers(404, "text/plain")
            self.wfile.write(b"404 File Not Found")

    def do_POST(self):
        global global_watcher, global_watcher_folder
        parsed = urlparse(self.path)

        if parsed.path == "/api/browse-file":
            selected_path = open_native_file_picker()
            self._set_headers(200)
            self.wfile.write(json.dumps({"success": bool(selected_path), "file_path": selected_path}).encode("utf-8"))
            return

        if parsed.path == "/api/browse-folder":
            selected_folder = open_native_folder_picker()
            self._set_headers(200)
            self.wfile.write(json.dumps({"success": bool(selected_folder), "folder_path": selected_folder}).encode("utf-8"))
            return

        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))

        fields = {}
        uploaded_file = None

        if "multipart/form-data" in content_type:
            try:
                fs = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={
                        "REQUEST_METHOD": "POST",
                        "CONTENT_TYPE": content_type,
                        "CONTENT_LENGTH": str(content_length)
                    }
                )
                for k in fs.keys():
                    item = fs[k]
                    if isinstance(item, list):
                        item = item[0]
                    if getattr(item, "filename", None):
                        uploaded_file = {
                            "filename": item.filename,
                            "content": item.file.read() if hasattr(item, "file") else item.value
                        }
                    else:
                        fields[k] = item.value
            except Exception as e:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": f"Error parsing form data: {e}"}).encode("utf-8"))
                return
        else:
            post_data = self.rfile.read(content_length)
            try:
                fields = json.loads(post_data.decode("utf-8")) if post_data else {}
            except Exception:
                fields = {}

        if parsed.path == "/api/config":
            try:
                new_cfg_data = fields.get("config", {})
                init_config(DEFAULT_CONFIG_PATH)
                with open(os.path.expanduser(DEFAULT_CONFIG_PATH), "w", encoding="utf-8") as f:
                    yaml.dump(new_cfg_data, f, default_flow_style=False)
                
                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "message": "Configuration saved successfully."}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": f"Failed to save config: {e}"}).encode("utf-8"))

        elif parsed.path == "/api/provider/test":
            cfg = load_config()
            kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
            cv = ComicVineProvider(api_key=cfg.comicvine.api_key)
            gcp = GCPProvider()

            self._set_headers(200)
            self.wfile.write(json.dumps({
                "success": True,
                "kapowarr": {"name": "Kapowarr", "url": cfg.kapowarr.url, "online": kap.test_connection()},
                "comicvine": {"name": "ComicVine", "ready": True},
                "gcp": {"name": "Grand Comics Database", "ready": True}
            }).encode("utf-8"))

        elif parsed.path == "/api/watch/start":
            folder = fields.get("folder_path", "").strip()
            if not folder:
                cfg = load_config()
                folder = cfg.automation.watch_folder or os.getcwd()

            folder_abs = os.path.abspath(folder)
            if not os.path.exists(folder_abs):
                os.makedirs(folder_abs, exist_ok=True)

            try:
                if global_watcher:
                    global_watcher.stop()
                
                cfg = load_config()
                global_watcher = LibraryWatcher(cfg)
                global_watcher.start_watching(folder_abs)
                global_watcher_folder = folder_abs

                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "message": f"Started watching '{folder_abs}'", "watch_folder": folder_abs}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": f"Failed to start watcher: {e}"}).encode("utf-8"))

        elif parsed.path == "/api/watch/stop":
            try:
                if global_watcher:
                    global_watcher.stop()
                    global_watcher = None
                global_watcher_folder = ""
                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "message": "Folder Watcher stopped."}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": f"Failed to stop watcher: {e}"}).encode("utf-8"))

        elif parsed.path == "/api/cache/clear":
            try:
                cfg = load_config()
                cache_mgr = CacheManager(cfg.cache.db_path)
                cache_mgr.clear()
                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "message": "Cache cleared."}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": f"Failed to clear cache: {e}"}).encode("utf-8"))

        elif parsed.path == "/api/search":
            query = fields.get("query", "").strip()
            search_type = fields.get("type", "all").strip()

            if not query:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing search query"}).encode("utf-8"))
                return

            try:
                results, kapowarr_active = search_all_providers(query, search_type)
                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "query": query,
                    "count": len(results),
                    "kapowarr_active": kapowarr_active,
                    "results": results
                }).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif parsed.path == "/api/scrape":
            url_val = fields.get("urls") or fields.get("url") or ""
            if not url_val:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing database URL(s) or page text"}).encode("utf-8"))
                return
            try:
                comic = fetch_and_merge_urls(url_val)
                provider = detect_provider(str(url_val))
                res_dict = comic_to_dict(comic)
                res_dict["provider"] = provider
                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "provider": provider, "comic": res_dict}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif parsed.path == "/api/scrape-volume":
            url = fields.get("url", "").strip()
            if not url:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing Volume URL"}).encode("utf-8"))
                return
            try:
                series_name, issue_map, issues_list = scrape_any_volume(url)
                provider = detect_provider(url)
                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "provider": provider,
                    "series_name": series_name,
                    "issues": issue_map,
                    "issues_list": issues_list,
                    "count": len(issue_map)
                }).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif parsed.path == "/api/batch-preview":
            volume_url = fields.get("url", "").strip()
            folder_path_input = fields.get("folder_path", "").strip()

            if not volume_url or not folder_path_input:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Both Volume URL and Folder Path are required."}).encode("utf-8"))
                return

            if not os.path.exists(folder_path_input) or not os.path.isdir(folder_path_input):
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": f"Folder directory '{folder_path_input}' not found."}).encode("utf-8"))
                return

            try:
                provider = detect_provider(volume_url)
                series_name, issue_map, issues_list = scrape_any_volume(volume_url)

                comic_files = [
                    f for f in sorted(os.listdir(folder_path_input))
                    if f.lower().endswith((".cbz", ".cbr"))
                ]

                if not comic_files:
                    self._set_headers(400)
                    self.wfile.write(json.dumps({"error": f"No .cbz or .cbr files found in '{folder_path_input}'."}).encode("utf-8"))
                    return

                items = []
                for fname in comic_files:
                    full_path = os.path.join(folder_path_input, fname)
                    issue_num = extract_issue_num_from_filename(fname)

                    matched_url = (
                        issue_map.get(issue_num) or
                        issue_map.get(issue_num.lstrip("0")) or
                        (issue_map.get("0.5") or issue_map.get("1/2") or issue_map.get("½") if issue_num in ("0.5", "1/2", "½", "0½") else None) or
                        (issue_map.get("0") or issue_map.get("00") or issue_map.get("000") if issue_num in ("0", "00", "000") else None)
                    )
                    if not matched_url and len(comic_files) == 1 and "1" in issue_map:
                        matched_url = issue_map["1"]

                    is_cbr = fname.lower().endswith(".cbr")

                    items.append({
                        "filename": fname,
                        "full_path": full_path,
                        "issue_number": issue_num or "Unknown",
                        "matched_url": matched_url or "",
                        "matched_urls": [matched_url] if matched_url else [],
                        "is_cbr": is_cbr,
                        "status": "ready" if matched_url else "unmatched",
                        "action": "Convert .cbr → .cbz & Delete original" if is_cbr else "Embed ComicInfo.xml"
                    })

                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "provider": provider,
                    "series_name": series_name,
                    "folder_path": folder_path_input,
                    "total_files": len(comic_files),
                    "total_series_issues": len(issues_list),
                    "matched_count": len([x for x in items if x["matched_url"]]),
                    "issues_list": issues_list,
                    "items": items
                }).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif parsed.path == "/api/batch-embed":
            volume_url = fields.get("url") or fields.get("urls") or ""
            folder_path_input = fields.get("folder_path", "").strip()
            items = fields.get("items") or []
            total_series_issues_override = fields.get("total_series_issues") or 0

            if not folder_path_input or not os.path.exists(folder_path_input):
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": f"Folder directory '{folder_path_input}' not found."}).encode("utf-8"))
                return

            cfg = load_config()
            delete_old_cbr = cfg.output.delete_cbr

            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            total_items = len(items)
            processed_count = 0
            errors = []

            for idx, item in enumerate(items):
                fname = item.get("filename")
                matched_url = item.get("matched_url")
                matched_urls = item.get("matched_urls") or ([matched_url] if matched_url else [])

                if not fname or not matched_urls:
                    chunk = json.dumps({"current": idx + 1, "total": total_items, "file": fname or "Unknown", "status": "skipped", "message": f"Skipped '{fname}': No matched database URL."}) + "\n"
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
                    continue

                full_file_path = os.path.join(folder_path_input, fname)
                if not os.path.exists(full_file_path):
                    chunk = json.dumps({"current": idx + 1, "total": total_items, "file": fname, "status": "error", "message": f"File '{fname}' not found on disk."}) + "\n"
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
                    continue

                target_archive = full_file_path
                if full_file_path.lower().endswith(".cbr"):
                    try:
                        target_archive = convert_cbr_to_cbz(full_file_path, delete_original=delete_old_cbr)
                    except Exception as ce:
                        err_msg = f"CBR conversion error for '{fname}': {ce}"
                        errors.append(err_msg)
                        chunk = json.dumps({"current": idx + 1, "total": total_items, "file": fname, "status": "error", "message": err_msg}) + "\n"
                        self.wfile.write(chunk.encode("utf-8"))
                        self.wfile.flush()
                        continue

                try:
                    comic = fetch_and_merge_urls(matched_urls if len(matched_urls) > 1 else matched_urls[0])
                    # Populate <Count> with total issues in series
                    count_val = total_series_issues_override or item.get("total_series_issues") or 0
                    if count_val and int(count_val) > 0:
                        comic.count = int(count_val)

                    embed_comicinfo_in_cbz(target_archive, comic)
                    processed_count += 1
                    msg = f"✅ Embedded ComicInfo.xml into '{os.path.basename(target_archive)}' ({comic.series} #{comic.number})"
                    chunk = json.dumps({"current": idx + 1, "total": total_items, "file": fname, "status": "success", "message": msg, "comic": comic_to_dict(comic)}) + "\n"
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
                except Exception as ie:
                    err_msg = f"Embedding error for '{fname}': {ie}"
                    errors.append(err_msg)
                    chunk = json.dumps({"current": idx + 1, "total": total_items, "file": fname, "status": "error", "message": err_msg}) + "\n"
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()


            final_chunk = json.dumps({
                "done": True,
                "processed_count": processed_count,
                "total_count": total_items,
                "errors": errors,
                "message": f"Batch process complete! Embedded metadata into {processed_count} of {total_items} file(s)."
            }) + "\n"
            self.wfile.write(final_chunk.encode("utf-8"))
            self.wfile.flush()
            return

        elif parsed.path == "/api/kapowarr/request-issue":
            issue_title = fields.get("issue_title", "")
            issue_id = fields.get("issue_id", "")
            cv_volume_id = fields.get("cv_volume_id", "")
            try:
                cfg = load_config()
                kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
                res = kap.request_issue_download(issue_id=issue_id, cv_volume_id=cv_volume_id, issue_title=issue_title)
                self._set_headers(200)
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        elif parsed.path == "/api/inspect-file":
            file_path = fields.get("file_path", "").strip()
            url_str = fields.get("url", "").strip()
            try:
                comic = None
                if file_path and os.path.exists(file_path) and file_path.lower().endswith(".cbz"):
                    comic = read_existing_comicinfo(file_path)

                if not comic and url_str:
                    comic = fetch_and_merge_urls(url_str)

                if not comic and file_path:
                    cfg = load_config()
                    resolver = MetadataResolver(config=cfg)
                    comic, _ = resolver.resolve_file_metadata(file_path, url_override=url_str, force_overwrite=True)

                if comic:
                    self._set_headers(200)
                    self.wfile.write(json.dumps({"success": True, "comic": comic_to_dict(comic)}).encode("utf-8"))
                else:
                    self._set_headers(404)
                    self.wfile.write(json.dumps({"error": "No metadata found for file or URL."}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return


        elif parsed.path == "/api/story-arc/parse-custom":
            text_data = fields.get("text", "") or fields.get("custom_list", "")
            arc_name = fields.get("title") or "Chronological Story Arc Crossover"
            if not text_data and fields.get("preset") == "marvel_zombies":
                text_data = MARVEL_ZOMBIES_PRESET_TEXT
                arc_name = "Marvel Zombies Complete Chronological Saga (71 Issues Crossover)"

            try:
                cfg = load_config()
                data = parse_custom_chronological_reading_order(text_data, arc_name=arc_name, watch_folder=cfg.automation.watch_folder)
                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "data": data}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        elif parsed.path == "/api/story-arc/fix-device-metadata":
            story_arc_name = fields.get("story_arc_name") or fields.get("arc_name") or fields.get("title") or "Story Arc"
            issues_list = fields.get("issues", [])
            try:
                from providers.story_arc import fix_story_arcs_on_device
                res = fix_story_arcs_on_device(issues_list, story_arc_name=story_arc_name)
                self._set_headers(200)
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        elif parsed.path == "/api/story-arc/clean-duplicate-tags":
            issues_list = fields.get("issues", [])
            try:
                from providers.story_arc import clean_duplicate_story_arcs_on_device
                res = clean_duplicate_story_arcs_on_device(issues_list)
                self._set_headers(200)
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return


        elif parsed.path == "/api/story-arc/rename-metadata":
            old_name = fields.get("old_name", "").strip()
            new_name = fields.get("new_name", "").strip()
            issues_list = fields.get("issues", [])
            if not old_name or not new_name:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "old_name and new_name are required."}).encode("utf-8"))
                return
            try:
                from providers.story_arc import rename_story_arc_on_device
                res = rename_story_arc_on_device(issues_list, old_name=old_name, new_name=new_name)
                self._set_headers(200)
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        elif parsed.path == "/api/story-arc/update-issue-arc-num":
            file_path = fields.get("file_path", "").strip()
            story_arc_name = fields.get("story_arc_name", "").strip()
            new_arc_number = fields.get("new_arc_number", "").strip()
            if not file_path or not story_arc_name or not new_arc_number:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "file_path, story_arc_name, and new_arc_number are required."}).encode("utf-8"))
                return
            try:
                from providers.story_arc import update_issue_arc_number_on_device
                res = update_issue_arc_number_on_device(file_path, story_arc_name, new_arc_number)
                self._set_headers(200)
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return


        elif parsed.path == "/api/embed-custom":
            file_path_input = fields.get("file_path", "").strip()
            comic_data = fields.get("comic") or fields.get("metadata") or {}

            if not file_path_input:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Target comic file path is required."}).encode("utf-8"))
                return

            real_file_path = file_path_input if os.path.exists(file_path_input) else find_file_path(file_path_input)
            if not real_file_path or not os.path.exists(real_file_path):
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": f"File '{file_path_input}' not found."}).encode("utf-8"))
                return

            cfg = load_config()
            delete_old_cbr = cfg.output.delete_cbr

            try:
                target_archive = real_file_path
                converted_note = ""
                was_cbr = real_file_path.lower().endswith(".cbr")
                if was_cbr:
                    target_archive = convert_cbr_to_cbz(real_file_path, delete_original=delete_old_cbr)
                    converted_note = f" (Converted from '{os.path.basename(real_file_path)}' & deleted original .cbr)"

                comic = dict_to_comic(comic_data)
                embed_comicinfo_in_cbz(target_archive, comic)

                res_dict = comic_to_dict(comic)
                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "target_file": target_archive,
                    "deleted_original": delete_old_cbr if was_cbr else False,
                    "message": f"Successfully updated and embedded custom ComicInfo.xml into '{os.path.basename(target_archive)}'{converted_note}.",
                    "comic": res_dict
                }).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif parsed.path == "/api/embed":
            url_val = fields.get("urls") or fields.get("url") or ""
            file_path_input = fields.get("file_path", "").strip()

            raw_del = fields.get("delete_original", True)
            delete_old_cbr = True if str(raw_del).lower() in ("true", "1", "yes") else False

            if not url_val:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Comic database URL(s) or page text required"}).encode("utf-8"))
                return

            real_file_path = ""
            if uploaded_file and uploaded_file.get("filename"):
                try:
                    upload_dir = os.path.expanduser("~/Downloads")
                    if not os.path.exists(upload_dir):
                        upload_dir = os.getcwd()
                    real_file_path = os.path.join(upload_dir, uploaded_file["filename"])
                    with open(real_file_path, "wb") as f:
                        f.write(uploaded_file["content"])
                except Exception as e:
                    self._set_headers(500)
                    self.wfile.write(json.dumps({"error": f"Error saving uploaded file: {e}"}).encode("utf-8"))
                    return

            if not real_file_path and file_path_input:
                real_file_path = find_file_path(file_path_input)

            if not real_file_path:
                self._set_headers(404)
                self.wfile.write(json.dumps({
                    "error": f"File '{file_path_input}' was not found. Please click Browse to select your file."
                }).encode("utf-8"))
                return

            try:
                target_archive = real_file_path
                converted_note = ""
                was_cbr = real_file_path.lower().endswith(".cbr")
                if was_cbr:
                    target_archive = convert_cbr_to_cbz(real_file_path, delete_original=delete_old_cbr)
                    converted_note = f" (Converted from '{os.path.basename(real_file_path)}' & deleted original .cbr)"

                comic = fetch_and_merge_urls(url_val)
                provider = detect_provider(str(url_val))
                embed_comicinfo_in_cbz(target_archive, comic)

                res_dict = comic_to_dict(comic)
                res_dict["provider"] = provider

                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "provider": provider,
                    "target_file": target_archive,
                    "deleted_original": delete_old_cbr if was_cbr else False,
                    "message": f"Successfully embedded ComicInfo.xml [{provider}] into '{os.path.basename(target_archive)}'{converted_note}.",
                    "comic": res_dict
                }).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Unknown API endpoint"}).encode("utf-8"))

    def log_message(self, format, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

def run_server(port=PORT):
    os.makedirs(STATIC_DIR, exist_ok=True)
    httpd = None
    target_port = port
    
    for p in range(target_port, target_port + 20):
        try:
            server_address = ("", p)
            httpd = HTTPServer(server_address, ComicServerHandler)
            target_port = p
            break
        except OSError:
            continue

    if not httpd:
        print(f"Error: Could not bind to any port in range {port}-{port+20}")
        sys.exit(1)

    print(f"==================================================")
    print(f" ComicInfo Generator Web UI running! [CV & GCP]")
    print(f" Open in browser: http://localhost:{target_port}")
    print(f"==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        httpd.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else PORT
    run_server(port)
