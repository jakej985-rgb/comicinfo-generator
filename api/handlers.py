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
from typing import Optional
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import yaml

from config import load_config, init_config, DEFAULT_CONFIG_PATH
from cache.db import CacheManager
from services.kapowarr import (
    get_kapowarr_library_status, test_kapowarr_connection, request_kapowarr_issue_download
)
from services.story_arc import (
    search_story_arcs, get_story_arc_details,
    fix_story_arcs_on_device, clean_duplicate_story_arcs_on_device,
    rename_story_arc_on_device, update_issue_arc_number_on_device,
    parse_custom_chronological_reading_order, MARVEL_ZOMBIES_PRESET_TEXT
)
from pipeline.resolver import MetadataResolver, read_existing_comicinfo

from api.serializers import comic_to_dict, dict_to_comic
from api.validation import (
    ValidationError,
    validate_filesystem_boundary,
    validate_folder_path,
    validate_comic_file_path,
    validate_url,
    validate_search_query
)
from services.metadata import detect_provider, fetch_and_merge_urls, scrape_any_volume, search_all_providers
from services.search import extract_issue_num_from_filename
from services.processing import (
    find_file_path, open_native_file_picker, open_native_folder_picker, embed_and_track
)

_repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(_repo_dir, "static")

def sanitize_error_text(text: str) -> str:
    """Sanitizes text to guarantee API keys are never exposed in error responses or logs."""
    if not text:
        return text
    try:
        cfg = load_config()
        for secret in (cfg.comicvine.api_key, cfg.kapowarr.api_key):
            if secret and len(secret) >= 4:
                text = text.replace(secret, "********")
    except Exception:
        pass
    return text


class ComicServerHandler(BaseHTTPRequestHandler):

    def _get_allowed_origin(self) -> Optional[str]:
        """
        Phase 80.2: Evaluates request Origin against configured CORS origins
        and localhost/127.0.0.1 boundaries.
        """
        origin = self.headers.get("Origin")
        if not origin:
            return None
        try:
            cfg = load_config()
            allowed = [o.rstrip("/").lower() for o in cfg.server.cors_origins]
            parsed = urlparse(origin)
            hostname = (parsed.hostname or "").lower()
            if hostname in ("localhost", "127.0.0.1"):
                return origin
            if origin.rstrip("/").lower() in allowed:
                return origin
        except Exception:
            pass
        return None

    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        allowed_origin = self._get_allowed_origin()
        if allowed_origin:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, status: int, data: dict):
        if isinstance(data, dict) and "error" in data and isinstance(data["error"], str):
            data["error"] = sanitize_error_text(data["error"])
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
                    "comicvine": {
                        "api_key_set": bool(cfg.comicvine.api_key and cfg.comicvine.api_key.strip())
                    },
                    "kapowarr": {
                        "url": cfg.kapowarr.url,
                        "api_key_set": bool(cfg.kapowarr.api_key and cfg.kapowarr.api_key.strip())
                    },
                    "server": {
                        "host": cfg.server.host,
                        "port": cfg.server.port,
                        "cors_origins": list(cfg.server.cors_origins)
                    },
                    "automation": {
                        "mode": cfg.automation.mode,
                        "workers": cfg.automation.workers,
                        "prefer_kapowarr": cfg.automation.prefer_kapowarr
                    },
                    "cache": {
                        "enabled": cfg.cache.enabled,
                        "db_path": cfg.cache.db_path
                    },
                    "output": {
                        "embed_xml": cfg.output.embed_xml,
                        "overwrite": cfg.output.overwrite,
                        "delete_cbr": cfg.output.delete_cbr,
                        "strict_archive_verification": cfg.output.strict_archive_verification
                    },
                    "logging": {
                        "level": cfg.logging.level,
                        "log_file": cfg.logging.log_file
                    }
                }
            })

        elif path == "/api/kapowarr/library":
            try:
                cfg = load_config()
                res = get_kapowarr_library_status(cfg)
                self._json(200, res)
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/kapowarr/series-issues":
            series_id = query_params.get("id", [""])[0] or query_params.get("series_id", [""])[0]
            series_url = query_params.get("url", [""])[0]
            folder_path = query_params.get("folder_path", [""])[0]
            try:
                cfg = load_config()
                if series_url:
                    validate_url(series_url)
                if folder_path:
                    folder_path = validate_folder_path(folder_path, configured_roots=cfg.library.roots, must_exist=False)

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
            except ValidationError as ve:
                self._json(ve.status_code, {"error": ve.message})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/story-arc/search":
            q = query_params.get("q", [""])[0] or query_params.get("query", [""])[0]
            try:
                valid_q = validate_search_query(q)
                cfg = load_config()
                arcs = search_story_arcs(valid_q, api_key=cfg.comicvine.api_key)
                self._json(200, {"success": True, "count": len(arcs), "story_arcs": arcs})
            except ValidationError as ve:
                self._json(ve.status_code, {"error": ve.message})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/story-arc/detail":
            arc_url = query_params.get("url", [""])[0]
            try:
                valid_url = validate_url(arc_url)
                details = get_story_arc_details(valid_url)
                self._json(200, {"success": True, "data": details})
            except ValidationError as ve:
                self._json(ve.status_code, {"error": ve.message})
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
                target_config_path = os.environ.get("COMICINFO_CONFIG") or DEFAULT_CONFIG_PATH
                init_config(target_config_path)
                expanded = os.path.expanduser(target_config_path)
                existing_yaml = {}
                if os.path.exists(expanded):
                    try:
                        with open(expanded, "r", encoding="utf-8") as f:
                            existing_yaml = yaml.safe_load(f) or {}
                    except Exception:
                        existing_yaml = {}

                # Deep update with secret preservation
                if "comicvine" in new_cfg_data:
                    cv = new_cfg_data["comicvine"]
                    if not isinstance(existing_yaml.get("comicvine"), dict):
                        existing_yaml["comicvine"] = {}
                    if cv.get("clear_api_key"):
                        existing_yaml["comicvine"]["api_key"] = ""
                    elif "api_key" in cv and cv["api_key"].strip():
                        existing_yaml["comicvine"]["api_key"] = cv["api_key"].strip()

                if "kapowarr" in new_cfg_data:
                    kap = new_cfg_data["kapowarr"]
                    if not isinstance(existing_yaml.get("kapowarr"), dict):
                        existing_yaml["kapowarr"] = {}
                    if "url" in kap:
                        existing_yaml["kapowarr"]["url"] = kap["url"]
                    if kap.get("clear_api_key"):
                        existing_yaml["kapowarr"]["api_key"] = ""
                    elif "api_key" in kap and kap["api_key"].strip():
                        existing_yaml["kapowarr"]["api_key"] = kap["api_key"].strip()

                for section in ("server", "automation", "cache", "output", "logging"):
                    if section in new_cfg_data and isinstance(new_cfg_data[section], dict):
                        if not isinstance(existing_yaml.get(section), dict):
                            existing_yaml[section] = {}
                        existing_yaml[section].update(new_cfg_data[section])

                with open(expanded, "w", encoding="utf-8") as f:
                    yaml.dump(existing_yaml, f, default_flow_style=False)
                self._json(200, {"success": True, "message": "Configuration saved successfully."})
            except Exception as e:
                self._json(500, {"error": f"Failed to save config: {e}"})

        elif path == "/api/provider/test":
            cfg = load_config()
            online = test_kapowarr_connection(cfg.kapowarr.url, cfg.kapowarr.api_key)
            self._json(200, {
                "success": True,
                "kapowarr": {"name": "Kapowarr", "url": cfg.kapowarr.url, "online": online},
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
            try:
                query = validate_search_query(fields.get("query", ""))
                search_type = fields.get("type", "all").strip()
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
            except ValidationError as ve:
                self._json(ve.status_code, {"error": ve.message})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/scrape":
            url_val = fields.get("urls") or fields.get("url") or ""
            try:
                valid_url = validate_url(str(url_val))
                comic = fetch_and_merge_urls(valid_url)
                provider = detect_provider(str(valid_url))
                res = comic_to_dict(comic)
                res["provider"] = provider
                self._json(200, {"success": True, "provider": provider, "comic": res})
            except ValidationError as ve:
                self._json(ve.status_code, {"error": ve.message})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/scrape-volume":
            url = fields.get("url", "").strip()
            try:
                valid_url = validate_url(url)
                series_name, issue_map, issues_list = scrape_any_volume(valid_url)
                provider = detect_provider(valid_url)
                self._json(200, {
                    "success": True, "provider": provider,
                    "series_name": series_name, "issues": issue_map,
                    "issues_list": issues_list, "count": len(issue_map)
                })
            except ValidationError as ve:
                self._json(ve.status_code, {"error": ve.message})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/batch-preview":
            volume_url = fields.get("url", "").strip()
            folder_path_input = fields.get("folder_path", "").strip()

            try:
                cfg = load_config()
                valid_url = validate_url(volume_url)
                valid_folder = validate_folder_path(folder_path_input, configured_roots=cfg.library.roots, must_exist=True)

                provider = detect_provider(valid_url)
                series_name, issue_map, issues_list = scrape_any_volume(valid_url)
                comic_files = [
                    f for f in sorted(os.listdir(valid_folder))
                    if f.lower().endswith((".cbz", ".cbr"))
                ]
                if not comic_files:
                    self._json(400, {
                        "error": f"No .cbz or .cbr files found in '{folder_path_input}'."})
                    return

                items = []
                for fname in comic_files:
                    full_path = os.path.join(valid_folder, fname)
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
                    "series_name": series_name, "folder_path": valid_folder,
                    "total_files": len(comic_files), "total_series_issues": len(issues_list),
                    "matched_count": len([x for x in items if x["matched_url"]]),
                    "issues_list": issues_list, "items": items
                })
            except ValidationError as ve:
                self._json(ve.status_code, {"error": ve.message})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/batch-embed":
            folder_path_input = fields.get("folder_path", "").strip()
            items = fields.get("items") or []
            total_series_issues_override = fields.get("total_series_issues") or 0

            try:
                cfg = load_config()
                valid_folder = validate_folder_path(folder_path_input, configured_roots=cfg.library.roots, must_exist=True)
            except ValidationError as ve:
                self._json(ve.status_code, {"error": ve.message})
                return

            cfg = load_config()
            self.send_response(200)
            allowed_origin = self._get_allowed_origin()
            if allowed_origin:
                self.send_header("Access-Control-Allow-Origin", allowed_origin)
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
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

                full_file_path = os.path.join(valid_folder, fname)
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
                res = request_kapowarr_issue_download(
                    cfg,
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
                cfg = load_config()
                if file_path:
                    file_path = validate_comic_file_path(file_path, configured_roots=cfg.library.roots, must_exist=True)
                if url_str:
                    url_str = validate_url(url_str)

                comic = None
                if file_path and os.path.exists(file_path) and file_path.lower().endswith(".cbz"):
                    comic = read_existing_comicinfo(file_path)
                if not comic and url_str:
                    comic = fetch_and_merge_urls(url_str)
                if not comic and file_path:
                    resolver = MetadataResolver(config=cfg)
                    comic, _ = resolver.resolve_file_metadata(
                        file_path, url_override=url_str, force_overwrite=True)
                if comic:
                    self._json(200, {"success": True, "comic": comic_to_dict(comic)})
                else:
                    self._json(404, {"error": "No metadata found for file or URL."})
            except ValidationError as ve:
                self._json(ve.status_code, {"error": ve.message})
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
                self._json(200, fix_story_arcs_on_device(
                    fields.get("issues", []), story_arc_name=story_arc_name))
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/story-arc/clean-duplicate-tags":
            try:
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
                cfg = load_config()
                valid_path = validate_comic_file_path(file_path, configured_roots=cfg.library.roots, must_exist=True)
                self._json(200, update_issue_arc_number_on_device(
                    valid_path, story_arc_name, new_arc_number))
            except ValidationError as ve:
                self._json(ve.status_code, {"error": ve.message})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif path == "/api/embed-custom":
            file_path_input = fields.get("file_path", "").strip()
            comic_data = fields.get("comic") or fields.get("metadata") or {}
            if not file_path_input:
                self._json(400, {"error": "Target comic file path is required."})
                return
            try:
                cfg = load_config()
                real_path = file_path_input if os.path.exists(file_path_input) else find_file_path(file_path_input)
                if not real_path:
                    self._json(404, {"error": f"File '{file_path_input}' not found."})
                    return
                valid_path = validate_comic_file_path(real_path, configured_roots=cfg.library.roots, must_exist=True)
                comic = dict_to_comic(comic_data)
                target_archive = embed_and_track(valid_path, comic, provider="Manual")
                self._json(200, {
                    "success": True, "target_file": target_archive,
                    "deleted_original": valid_path.lower().endswith(".cbr"),
                    "message": f"Successfully embedded ComicInfo.xml into '{os.path.basename(target_archive)}'.",
                    "comic": comic_to_dict(comic)
                })
            except ValidationError as ve:
                self._json(ve.status_code, {"error": ve.message})
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
            try:
                cfg = load_config()
                valid_url = validate_url(str(url_val))
                real_path = find_file_path(file_path_input)
                if not real_path:
                    self._json(404, {"error": f"File '{file_path_input}' not found. Click Browse."})
                    return
                valid_path = validate_comic_file_path(real_path, configured_roots=cfg.library.roots, must_exist=True)
                comic = fetch_and_merge_urls(valid_url)
                provider = detect_provider(str(valid_url))
                target_archive = embed_and_track(valid_path, comic, provider=provider)
                res = comic_to_dict(comic)
                res["provider"] = provider
                self._json(200, {
                    "success": True, "provider": provider,
                    "target_file": target_archive,
                    "deleted_original": delete_old_cbr and valid_path.lower().endswith(".cbr"),
                    "message": f"Successfully embedded ComicInfo.xml [{provider}] into '{os.path.basename(target_archive)}'.",
                    "comic": res
                })
            except ValidationError as ve:
                self._json(ve.status_code, {"error": ve.message})
            except Exception as e:
                self._json(500, {"error": str(e)})

        else:
            self._json(404, {"error": "Unknown API endpoint"})

    def log_message(self, format, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))
