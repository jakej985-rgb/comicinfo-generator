"""
api/server.py — Phase 32

Thin HTTP server bootstrap. No business logic.
"""
import os
import sys
from http.server import HTTPServer

from api.handlers import ComicServerHandler

PORT = 5005
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


def run_server(port: int = PORT):
    os.makedirs(STATIC_DIR, exist_ok=True)
    httpd = None
    target_port = port

    for p in range(target_port, target_port + 20):
        try:
            httpd = HTTPServer(("", p), ComicServerHandler)
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
