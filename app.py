import base64
import cgi
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

repo_dir = os.path.dirname(os.path.abspath(__file__))
if repo_dir not in sys.path:
    sys.path.insert(0, repo_dir)

from models.comic import Comic, merge_comics
from providers.comicvine import scrape_issue, scrape_volume, search_comicvine
from writers.archive import embed_comicinfo_in_cbz
from writers.comicinfo import write_xml, generate_xml_bytes
from converters.cbr_to_cbz import convert_cbr_to_cbz

PORT = 5000
STATIC_DIR = os.path.join(repo_dir, "static")

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
    }

def fetch_and_merge_urls(url_val) -> Comic:
    """Accepts a single URL string, list of URLs, or multi-line string and scrapes/merges them."""
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
        raise ValueError("No valid Comic Vine URLs provided.")

    if len(urls) == 1:
        return scrape_issue(urls[0])

    comics = [scrape_issue(u) for u in urls]
    return merge_comics(comics)

def extract_issue_num_from_filename(filename: str) -> str:
    """Extracts issue number from a comic archive filename using accurate hierarchy."""
    fname = re.sub(r"\.(cbz|cbr|zip|rar)$", "", filename, flags=re.I)
    
    # 1. Match explicit 'Issue 002', 'Issue #002', 'Issue 2'
    m = re.search(r"\bissue\s*#?\s*0*(\d+[a-zA-Z]?|\d+\.\d+|\d+)", fname, re.I)
    if m:
        return m.group(1)

    # 2. Match explicit '#02' or '#2'
    m = re.search(r"#0*(\d+[a-zA-Z]?|\d+\.\d+|\d+)", fname)
    if m:
        return m.group(1)

    # 3. Match 'Volume XX Issue YY' or 'Volume XX 002' or 'Vol XX - 02'
    m = re.search(r"(?:vol|volume)\s*\d+[\s\-_]+(?:issue\s*#?)?0*(\d+[a-zA-Z]?|\d+\.\d+|\d+)", fname, re.I)
    if m:
        return m.group(1)

    # 4. Match 'Vol 001' or 'Volume 001' ONLY if single volume number
    m = re.search(r"(?:vol|volume)\s*0*(\d+)", fname, re.I)
    if m:
        return m.group(1)

    # 5. Trailing standalone issue numbers (e.g. 'Bart Simpson 002' or 'Comic 23')
    m = re.search(r"\b0*(\d+)\b", fname)
    if m:
        return m.group(1)

    return ""

def get_active_display_env():
    """Detects active X11 DISPLAY and XAUTHORITY from active desktop processes."""
    env = dict(os.environ)
    if "DISPLAY" not in env or not env["DISPLAY"]:
        for d in [":0", ":0.0", ":1"]:
            env["DISPLAY"] = d
            break
    if "XAUTHORITY" not in env or not env["XAUTHORITY"]:
        env["XAUTHORITY"] = os.path.expanduser("~/.Xauthority")
    return env

def open_native_file_picker() -> str:
    """Opens a native OS file dialog using zenity or kdialog."""
    env = get_active_display_env()

    zenity = shutil.which("zenity")
    if zenity:
        try:
            res = subprocess.run([
                zenity, "--file-selection",
                "--title=Select Comic Archive (.cbz, .cbr)",
                "--file-filter=Comic Archives (*.cbz *.cbr) | *.cbz *.cbr *.zip *.rar"
            ], capture_output=True, text=True, timeout=60, env=env)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception as e:
            sys.stderr.write(f"Zenity file picker notice: {e}\n")

    kdialog = shutil.which("kdialog")
    if kdialog:
        try:
            res = subprocess.run([
                kdialog, "--getopenfilename", os.path.expanduser("~"),
                "*.cbz *.cbr|Comic Archives (*.cbz *.cbr)"
            ], capture_output=True, text=True, timeout=60, env=env)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception as e:
            sys.stderr.write(f"Kdialog file picker notice: {e}\n")

    return ""

def open_native_folder_picker() -> str:
    """Opens a native OS directory dialog using zenity or kdialog."""
    env = get_active_display_env()

    zenity = shutil.which("zenity")
    if zenity:
        try:
            res = subprocess.run([
                zenity, "--file-selection", "--directory",
                "--title=Select Comic Series Folder"
            ], capture_output=True, text=True, timeout=60, env=env)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception as e:
            sys.stderr.write(f"Zenity folder picker notice: {e}\n")

    kdialog = shutil.which("kdialog")
    if kdialog:
        try:
            res = subprocess.run([
                kdialog, "--getexistingdirectory", os.path.expanduser("~")
            ], capture_output=True, text=True, timeout=60, env=env)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception as e:
            sys.stderr.write(f"Kdialog folder picker notice: {e}\n")

    return ""

def find_file_path(path_str: str) -> str:
    """Searches for a file path or filename across common directories and mounted drives."""
    if not path_str:
        return ""
    path_str = path_str.strip("'\"").strip()
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

        if parsed.path == "/api/search":
            query = fields.get("query", "").strip()
            search_type = fields.get("type", "all").strip()

            if not query:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing search query"}).encode("utf-8"))
                return

            try:
                results = search_comicvine(query, search_type)
                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "query": query,
                    "count": len(results),
                    "results": results
                }).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif parsed.path == "/api/scrape":
            url_val = fields.get("urls") or fields.get("url") or ""
            if not url_val:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing Comic Vine URL(s)"}).encode("utf-8"))
                return
            try:
                comic = fetch_and_merge_urls(url_val)
                self._set_headers(200)
                self.wfile.write(json.dumps({"success": True, "comic": comic_to_dict(comic)}).encode("utf-8"))
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
                series_name, issue_map, issues_list = scrape_volume(url)
                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
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
                series_name, issue_map, issues_list = scrape_volume(volume_url)

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

                    matched_url = issue_map.get(issue_num) or issue_map.get(issue_num.lstrip("0"))
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
                    "series_name": series_name,
                    "folder_path": folder_path_input,
                    "total_files": len(comic_files),
                    "matched_count": len([x for x in items if x["matched_url"]]),
                    "issues_list": issues_list,
                    "items": items
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
                self.wfile.write(json.dumps({"error": "Comic Vine URL(s) required"}).encode("utf-8"))
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
                embed_comicinfo_in_cbz(target_archive, comic)

                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "target_file": target_archive,
                    "deleted_original": delete_old_cbr if was_cbr else False,
                    "message": f"Successfully embedded ComicInfo.xml into '{os.path.basename(target_archive)}'{converted_note}.",
                    "comic": comic_to_dict(comic)
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
    print(f" ComicInfo Generator Web UI running!")
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
