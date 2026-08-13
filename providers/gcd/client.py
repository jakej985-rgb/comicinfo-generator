import requests
from typing import Dict, Any, Optional
from providers.base import ProviderConnectionError

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

class GCDClient:
    """
    HTTP client for Grand Comics Database (comics.org).
    Handles direct scraping, API JSON requests, and Wayback Machine archive fallbacks.
    """

    def __init__(self, timeout: int = 4):
        self.timeout = timeout

    def fetch_html(self, url: str) -> str:
        """Fetches HTML content from comics.org with direct request & HTTPS Wayback Machine fallback."""
        if HAS_CURL_CFFI:
            try:
                r = cffi_requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=self.timeout)
                if r.status_code == 200 and "Just a moment..." not in r.text and "<title>Just a moment..." not in r.text:
                    return r.text
            except Exception:
                pass

        try:
            r = requests.get(url, headers=HEADERS, timeout=self.timeout)
            if r.status_code == 200 and "Just a moment..." not in r.text and "<title>Just a moment..." not in r.text:
                return r.text
        except Exception:
            pass

        # HTTPS Wayback Machine Archive Fallback
        try:
            wb_url = f"https://web.archive.org/web/2024/{url}"
            r = requests.get(wb_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=8)
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text
        except Exception:
            pass

        return ""

    def fetch_api_json(self, url: str) -> Dict[str, Any]:
        """Fetches JSON content from comics.org REST API endpoint."""
        clean_url = url if "?format=json" in url else f"{url.rstrip('/')}/?format=json"
        headers = dict(HEADERS)
        headers["Accept"] = "application/json"

        if HAS_CURL_CFFI:
            try:
                r = cffi_requests.get(clean_url, headers=headers, impersonate="chrome", timeout=self.timeout)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                pass

        try:
            r = requests.get(clean_url, headers=headers, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass

        return {}
