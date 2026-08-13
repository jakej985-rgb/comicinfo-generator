"""
api/handlers.py — Phase 32

All HTTP route dispatch logic. Delegates to service layer.
No direct provider calls or archive I/O — those live in services/.
"""
import cgi
import json
import os
import sys
import zipfile
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import yaml

from config import load_config, init_config, DEFAULT_CONFIG_PATH
from cache.db import CacheManager
from providers.kapowarr import KapowarrProvider
from providers.gcp import GCPProvider
from providers.story_arc import (
    search_story_arcs, get_story_arc_details,
    parse_custom_chronological_reading_order, MARVEL_ZOMBIES_PRESET_TEXT
)
from pipeline.resolver import MetadataResolver, read_existing_comicinfo

from api.serializers import comic_to_dict, dict_to_comic
from services.metadata import detect_provider, fetch_and_merge_urls, scrape_any_volume, search_all_providers
from services.search import extract_issue_num_from_filename
from services.processing import (
    find_file_path, open_native_file_picker, open_native_folder_picker, embed_and_track
)

_repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(_repo_dir, "static")


class ComicServerHandler(BaseHTTPRequestHandler):

    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, status: int, data: dict):
        self._set_headers(status)
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_OPTIONS(self):
        self._set_headers(200)

    # ------------------------------------------------------------------ #
    # GET                                                                 #
    # ------------------------------------------------------------------ #
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # --- Static assets ---
        static_map = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "application/javascript; charset=utf-8"),
        }
        if path in static_map:
            fname, ct = static_map[path]
            file_path = os.path.join(STATIC_DIR, fname)
            if os.path.exists(file_path):
                self._set_headers(200, ct)
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self._set_headers(404, "text/plain")
                self.wfile.write(b"404 File Not Found")
            return

        query_params = parse_qs(parsed.query)

        if path == "/api/config":
            cfg = load_config()
            self._json(200, {
                "success": True,
                "config": {
                    "comicvine": {"api_key": cfg.comicvine.api_key},
                    "kapowarr": {"url": cfg.kapowarr.url, "api_key": cfg.kapowarr.api_key},
                    "automation": {"mode": cfg.automation.mode, "workers": cfg.automation.workers,
                                   "prefer_kapowarr": cfg.automation.prefer_kapowarr},
                    "cache": {"enabled": cfg.cache.enabled, "db_path": cfg.cache.db_path},
                    "output": {"embed_xml": cfg.output.embed_xml, "overwrite": cfg.output.overwrite,
                               "delete_cbr": cfg.output.delete_cbr},
                    "logging": {"level": cfg.logging.level, "log_file": cfg.logging.log_file}
                }
            })

        elif path == "/api/kapowarr/library":
            try:
                cfg = load_config()
                kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
                items = kap.get_library_status(prefer_kapowarr=cfg.automation.prefer_kapowarr)
                self._json(200, {"online": kap.test_connection(), "items": items})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/kapowarr/series-issues":
            series_id = query_params.get("id", [""])[0] or query_params.get("series_id", [""])[0]
            series_url = query_params.get("url", [""])[0]
            folder_path = query_params.get("folder_path", [""])[0]
            try:
                cfg = load_config()
                series_name, _, issues_list = "", {}, []
                if series_url or series_id:
                    target_url = series_url or f"{cfg.kapowarr.url}/volume/{series_id}"
                    series_name, _, issues_list = scrape_any_volume(target_url)

                if folder_path and os.path.exists(folder_path):
                    local_files = [f for f in os.listdir(folder_path)
                                   if f.lower().endswith((".cbz", ".cbr"))]
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
                                        with zipfile.ZipFile(full_f, "r") as zf:
                                            if "comicinfo.xml" in [n.lower() for n in zf.namelist()]:
                                                is_tagged = True
                                    except Exception:
                                        pass
                                break
                        iss["matched_file"] = matched_file
                        iss["is_tagged"] = is_tagged
                        iss["file_path"] = os.path.join(folder_path, matched_file) if matched_file else ""

                self._json(200, {
                    "success": True, "series_name": series_name,
                    "count": len(issues_list), "issues": issues_list
                })
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/story-arc/search":
            q = query_params.get("q", [""])[0] or query_params.get("query", [""])[0]
            try:
                cfg = load_config()
                arcs = search_story_arcs(q, api_key=cfg.comicvine.api_key)
                self._json(200, {"success": True, "count": len(arcs), "story_arcs": arcs})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/story-arc/detail":
            arc_url = query_params.get("url", [""])[0]
            try:
                details = get_story_arc_details(arc_url)
                self._json(200, {"success": True, "data": details})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/cache/stats":
            cfg = load_config()
            cache_mgr = CacheManager(cfg.cache.db_path)
            self._json(200, {"success": True, "stats": cache_mgr.get_stats()})

        else:
            self._set_headers(404, "text/plain")
            self.wfile.write(b"404 Not Found")

    # ------------------------------------------------------------------ #
    # POST                                                                #
    # ------------------------------------------------------------------ #
    def _parse_post_body(self):
        """Parses multipart or JSON POST body; returns (fields dict, uploaded_file or None)."""
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))
        fields = {}
        uploaded_file = None

        if "multipart/form-data" in content_type:
            try:
                fs = cgi.FieldStorage(
                    fp=self.rfile, headers=self.headers,
                    environ={"REQUEST_METHOD": "POST",
                             "CONTENT_TYPE": content_type,
                             "CONTENT_LENGTH": str(content_length)}
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
                return None, None, str(e)
        else:
            post_data = self.rfile.read(content_length)
            try:
                fields = json.loads(post_data.decode("utf-8")) if post_data else {}
            except Exception:
                fields = {}

        return fields, uploaded_file, None

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/browse-file":
            selected = open_native_file_picker()
            self._json(200, {"success": bool(selected), "file_path": selected})
            return

        if parsed.path == "/api/browse-folder":
            selected = open_native_folder_picker()
            self._json(200, {"success": bool(selected), "folder_path": selected})
            return

        fields, uploaded_file, parse_err = self._parse_post_body()
        if parse_err:
            self._json(400, {"error": f"Error parsing form data: {parse_err}"})
            return

        path = parsed.path

        if path == "/api/config":
            try:
                new_cfg_data = fields.get("config", {})
                init_config(DEFAULT_CONFIG_PATH)
                with open(os.path.expanduser(DEFAULT_CONFIG_PATH), "w", encoding="utf-8") as f:
                    yaml.dump(new_cfg_data, f, default_flow_style=False)
                self._json(200, {"success": True, "message": "Configuration saved successfully."})
            except Exception as e:
                self._json(500, {"error": f"Failed to save config: {e}"})

        elif path == "/api/provider/test":
            cfg = load_config()
            kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
            self._json(200, {
                "success": True,
                "kapowarr": {"name": "Kapowarr", "url": cfg.kapowarr.url, "online": kap.test_connection()},
                "comicvine": {"name": "ComicVine", "ready": True},
                "gcp": {"name": "Grand Comics Database", "ready": True}
            })

        elif path == "/api/cache/clear":
            try:
                cfg = load_config()
                CacheManager(cfg.cache.db_path).clear()
                self._json(200, {"success": True, "message": "Cache cleared."})
            except Exception as e:
                self._json(500, {"error": f"Failed to clear cache: {e}"})

        elif path == "/api/search":
            query = fields.get("query", "").strip()
            search_type = fields.get("type", "all").strip()
            if not query:
                self._json(400, {"error": "Missing search query"})
                return
            try:
                results, kapowarr_active = search_all_providers(query, search_type)
                try:
                    cfg = load_config()
                    CacheManager(cfg.cache.db_path).save_cached_search(
                        "Combined", search_type, query, results)
                except Exception:
                    pass
                self._json(200, {
                    "success": True, "query": query,
                    "count": len(results), "kapowarr_active": kapowarr_active,
                    "results": results
                })
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/scrape":
            url_val = fields.get("urls") or fields.get("url") or ""
            if not url_val:
                self._json(400, {"error": "Missing database URL(s) or page text"})
                return
            try:
                comic = fetch_and_merge_urls(url_val)
                provider = detect_provider(str(url_val))
                res = comic_to_dict(comic)
                res["provider"] = provider
                self._json(200, {"success": True, "provider": provider, "comic": res})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/scrape-volume":
            url = fields.get("url", "").strip()
            if not url:
                self._json(400, {"error": "Missing Volume URL"})
                return
            try:
                series_name, issue_map, issues_list = scrape_any_volume(url)
                provider = detect_provider(url)
                self._json(200, {
                    "success": True, "provider": provider,
                    "series_name": series_name, "issues": issue_map,
                    "issues_list": issues_list, "count": len(issue_map)
                })
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/batch-preview":
            volume_url = fields.get("url", "").strip()
            folder_path_input = fields.get("folder_path", "").strip()

            if not volume_url or not folder_path_input:
                self._json(400, {"error": "Both Volume URL and Folder Path are required."})
                return
            if not os.path.exists(folder_path_input) or not os.path.isdir(folder_path_input):
                self._json(404, {"error": f"Folder directory '{folder_path_input}' not found."})
                return

            try:
                provider = detect_provider(volume_url)
                series_name, issue_map, issues_list = scrape_any_volume(volume_url)
                comic_files = [
                    f for f in sorted(os.listdir(folder_path_input))
                    if f.lower().endswith((".cbz", ".cbr"))
                ]
                if not comic_files:
                    self._json(400, {
                        "error": f"No .cbz or .cbr files found in '{folder_path_input}'."})
                    return

                items = []
                for fname in comic_files:
                    full_path = os.path.join(folder_path_input, fname)
                    issue_num = extract_issue_num_from_filename(fname)
                    matched_url = (
                        issue_map.get(issue_num) or
                        issue_map.get(issue_num.lstrip("0")) or
                        (issue_map.get("0.5") if issue_num in ("0.5", "1/2", "½", "0½") else None) or
                        (issue_map.get("0") if issue_num in ("0", "00", "000") else None)
                    )
                    if not matched_url and len(comic_files) == 1 and "1" in issue_map:
                        matched_url = issue_map["1"]

                    is_cbr = fname.lower().endswith(".cbr")
                    items.append({
                        "filename": fname, "full_path": full_path,
                        "issue_number": issue_num or "Unknown",
                        "matched_url": matched_url or "",
                        "matched_urls": [matched_url] if matched_url else [],
                        "is_cbr": is_cbr,
                        "status": "ready" if matched_url else "unmatched",
                        "action": "Convert .cbr → .cbz & Delete original" if is_cbr else "Embed ComicInfo.xml"
                    })

                self._json(200, {
                    "success": True, "provider": provider,
                    "series_name": series_name, "folder_path": folder_path_input,
                    "total_files": len(comic_files), "total_series_issues": len(issues_list),
                    "matched_count": len([x for x in items if x["matched_url"]]),
                    "issues_list": issues_list, "items": items
                })
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/batch-embed":
            folder_path_input = fields.get("folder_path", "").strip()
            items = fields.get("items") or []
            total_series_issues_override = fields.get("total_series_issues") or 0

            if not folder_path_input or not os.path.exists(folder_path_input):
                self._json(400, {
                    "error": f"Folder directory '{folder_path_input}' not found."})
                return

            cfg = load_config()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            processed_count = 0
            errors = []

            for idx, item in enumerate(items):
                fname = item.get("filename")
                matched_url = item.get("matched_url")
                matched_urls = item.get("matched_urls") or ([matched_url] if matched_url else [])

                if not fname or not matched_urls:
                    chunk = json.dumps({
                        "current": idx + 1, "total": len(items), "file": fname or "Unknown",
                        "status": "skipped",
                        "message": f"Skipped '{fname}': No matched database URL."
                    }) + "\n"
                    self.wfile.write(chunk.encode()); self.wfile.flush()
                    continue

                full_file_path = os.path.join(folder_path_input, fname)
                if not os.path.exists(full_file_path):
                    chunk = json.dumps({
                        "current": idx + 1, "total": len(items), "file": fname,
                        "status": "error", "message": f"File '{fname}' not found on disk."
                    }) + "\n"
                    self.wfile.write(chunk.encode()); self.wfile.flush()
                    continue

                try:
                    comic = fetch_and_merge_urls(
                        matched_urls if len(matched_urls) > 1 else matched_urls[0]
                    )
                    count_val = total_series_issues_override or item.get("total_series_issues") or 0
                    if count_val and int(count_val) > 0:
                        comic.count = int(count_val)

                    provider = detect_provider(str(matched_urls[0]))
                    cache_mgr = CacheManager(cfg.cache.db_path)
                    target_archive = embed_and_track(
                        full_file_path, comic, provider=provider, cache_mgr=cache_mgr
                    )
                    processed_count += 1
                    msg = (f"✅ Embedded ComicInfo.xml into "
                           f"'{os.path.basename(target_archive)}' "
                           f"({comic.series} #{comic.number})")
                    chunk = json.dumps({
                        "current": idx + 1, "total": len(items), "file": fname,
                        "status": "success", "message": msg, "comic": comic_to_dict(comic)
                    }) + "\n"
                except Exception as ie:
                    err_msg = f"Error for '{fname}': {ie}"
                    errors.append(err_msg)
                    chunk = json.dumps({
                        "current": idx + 1, "total": len(items), "file": fname,
                        "status": "error", "message": err_msg
                    }) + "\n"

                self.wfile.write(chunk.encode()); self.wfile.flush()

            final = json.dumps({
                "done": True, "processed_count": processed_count,
                "total_count": len(items), "errors": errors,
                "message": (f"Batch process complete! "
                            f"Embedded metadata into {processed_count} of {len(items)} file(s).")
            }) + "\n"
            self.wfile.write(final.encode()); self.wfile.flush()

        elif path == "/api/kapowarr/request-issue":
            try:
                cfg = load_config()
                kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
                res = kap.request_issue_download(
                    issue_id=fields.get("issue_id", ""),
                    cv_volume_id=fields.get("cv_volume_id", ""),
                    issue_title=fields.get("issue_title", "")
                )
                self._json(200, res)
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/inspect-file":
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
                    comic, _ = resolver.resolve_file_metadata(
                        file_path, url_override=url_str, force_overwrite=True)
                if comic:
                    self._json(200, {"success": True, "comic": comic_to_dict(comic)})
                else:
                    self._json(404, {"error": "No metadata found for file or URL."})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/story-arc/parse-custom":
            text_data = fields.get("text", "") or fields.get("custom_list", "")
            arc_name = fields.get("title") or "Chronological Story Arc Crossover"
            if not text_data and fields.get("preset") == "marvel_zombies":
                text_data = MARVEL_ZOMBIES_PRESET_TEXT
                arc_name = "Marvel Zombies Complete Chronological Saga (71 Issues Crossover)"
            try:
                data = parse_custom_chronological_reading_order(text_data, arc_name=arc_name)
                self._json(200, {"success": True, "data": data})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/story-arc/fix-device-metadata":
            story_arc_name = (fields.get("story_arc_name") or fields.get("arc_name")
                              or fields.get("title") or "Story Arc")
            try:
                from providers.story_arc import fix_story_arcs_on_device
                self._json(200, fix_story_arcs_on_device(
                    fields.get("issues", []), story_arc_name=story_arc_name))
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/story-arc/clean-duplicate-tags":
            try:
                from providers.story_arc import clean_duplicate_story_arcs_on_device
                self._json(200, clean_duplicate_story_arcs_on_device(fields.get("issues", [])))
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/story-arc/rename-metadata":
            old_name = fields.get("old_name", "").strip()
            new_name = fields.get("new_name", "").strip()
            if not old_name or not new_name:
                self._json(400, {"error": "old_name and new_name are required."})
                return
            try:
                from providers.story_arc import rename_story_arc_on_device
                self._json(200, rename_story_arc_on_device(
                    fields.get("issues", []), old_name=old_name, new_name=new_name))
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/story-arc/update-issue-arc-num":
            file_path = fields.get("file_path", "").strip()
            story_arc_name = fields.get("story_arc_name", "").strip()
            new_arc_number = fields.get("new_arc_number", "").strip()
            if not file_path or not story_arc_name or not new_arc_number:
                self._json(400, {
                    "error": "file_path, story_arc_name, and new_arc_number are required."})
                return
            try:
                from providers.story_arc import update_issue_arc_number_on_device
                self._json(200, update_issue_arc_number_on_device(
                    file_path, story_arc_name, new_arc_number))
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/embed-custom":
            file_path_input = fields.get("file_path", "").strip()
            comic_data = fields.get("comic") or fields.get("metadata") or {}
            if not file_path_input:
                self._json(400, {"error": "Target comic file path is required."})
                return
            real_path = file_path_input if os.path.exists(file_path_input) else find_file_path(file_path_input)
            if not real_path:
                self._json(404, {"error": f"File '{file_path_input}' not found."})
                return
            try:
                comic = dict_to_comic(comic_data)
                target_archive = embed_and_track(real_path, comic, provider="Manual")
                self._json(200, {
                    "success": True, "target_file": target_archive,
                    "deleted_original": real_path.lower().endswith(".cbr"),
                    "message": f"Successfully embedded ComicInfo.xml into '{os.path.basename(target_archive)}'.",
                    "comic": comic_to_dict(comic)
                })
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/embed":
            url_val = fields.get("urls") or fields.get("url") or ""
            file_path_input = fields.get("file_path", "").strip()
            raw_del = fields.get("delete_original", True)
            delete_old_cbr = str(raw_del).lower() in ("true", "1", "yes")
            if not url_val or not file_path_input:
                self._json(400, {"error": "Comic database URL(s) and file path required"})
                return
            real_path = find_file_path(file_path_input)
            if not real_path:
                self._json(404, {"error": f"File '{file_path_input}' not found. Click Browse."})
                return
            try:
                comic = fetch_and_merge_urls(url_val)
                provider = detect_provider(str(url_val))
                target_archive = embed_and_track(real_path, comic, provider=provider)
                res = comic_to_dict(comic)
                res["provider"] = provider
                self._json(200, {
                    "success": True, "provider": provider,
                    "target_file": target_archive,
                    "deleted_original": delete_old_cbr and real_path.lower().endswith(".cbr"),
                    "message": f"Successfully embedded ComicInfo.xml [{provider}] into '{os.path.basename(target_archive)}'.",
                    "comic": res
                })
            except Exception as e:
                self._json(500, {"error": str(e)})

        else:
            self._json(404, {"error": "Unknown API endpoint"})

    def log_message(self, format, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))
