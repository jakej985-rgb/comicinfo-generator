"""
api/server.py — Phase 32

Thin HTTP server bootstrap. No business logic.
"""
import os
import sys
from http.server import HTTPServer

from config import load_config, validate_startup_config, ConfigurationError
from api.handlers import ComicServerHandler

PORT = 5005
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


def run_server(port: int = None, host: str = None):
    try:
        cfg = load_config()
        warnings = validate_startup_config(cfg)
        for w in warnings:
            print(f"[{w}]", file=sys.stderr)
    except ConfigurationError as ce:
        print(f"FATAL CONFIGURATION ERROR: {ce}", file=sys.stderr)
        sys.exit(1)

    target_host = host or cfg.server.host or "127.0.0.1"
    target_port = port or cfg.server.port or PORT

    os.makedirs(STATIC_DIR, exist_ok=True)
    httpd = None

    for p in range(target_port, target_port + 20):
        try:
            httpd = HTTPServer((target_host, p), ComicServerHandler)
            target_port = p
            break
        except OSError:
            continue

    if not httpd:
        print(f"Error: Could not bind to {target_host} on any port in range {target_port}-{target_port+20}")
        sys.exit(1)

    print(f"==================================================")
    print(f" ComicInfo Generator Web UI running! [CV & GCP]")
    print(f" Open in browser: http://{target_host}:{target_port}")
    print(f"==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        httpd.server_close()
