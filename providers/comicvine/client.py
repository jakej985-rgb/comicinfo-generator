import time
import requests
from typing import Optional
from providers.base import (
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderAuthenticationError,
    MetadataNotFoundError
)

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1"
}

class ComicVineClient:
    """
    Dedicated HTTP client for Comic Vine web scraping.
    Handles user-agent headers, Cloudflare bypass (curl_cffi/cloudscraper), timeouts, and rate limiting.
    """

    def __init__(self, api_key: str = "", timeout: int = 30, min_request_interval: float = 1.0):
        self.api_key = api_key
        self.timeout = timeout
        self.min_request_interval = min_request_interval
        self._last_request_time = 0.0

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self._last_request_time = time.time()

    def fetch_html(self, url: str) -> str:
        """Fetches HTML content from Comic Vine URL with explicit typed error semantics."""
        self._rate_limit()
        html_content = ""

        if HAS_CURL_CFFI:
            try:
                r = cffi_requests.get(url, impersonate="chrome", timeout=self.timeout)
                if r.status_code == 200 and "Just a moment..." not in r.text:
                    html_content = r.text
            except Exception:
                pass

        if not html_content and HAS_CLOUDSCRAPER:
            try:
                scraper = cloudscraper.create_scraper()
                r = scraper.get(url, timeout=self.timeout)
                if r.status_code == 200 and "Just a moment..." not in r.text:
                    html_content = r.text
            except Exception:
                pass

        if not html_content:
            try:
                r = requests.get(url, headers=HEADERS, timeout=self.timeout)
                if r.status_code == 429:
                    raise ProviderRateLimitError("Comic Vine request rate limited (HTTP 429).", provider_name="CV")
                elif r.status_code in (401, 403):
                    raise ProviderAuthenticationError(f"Comic Vine authentication failed (HTTP {r.status_code}).", provider_name="CV")
                elif r.status_code == 404:
                    raise MetadataNotFoundError(f"Comic Vine resource not found at '{url}' (HTTP 404).", provider_name="CV")
                r.raise_for_status()
                html_content = r.text
            except Exception as e:
                if isinstance(e, (ProviderRateLimitError, ProviderAuthenticationError, MetadataNotFoundError)):
                    raise e
                raise ProviderConnectionError(f"Failed to fetch Comic Vine URL '{url}': {e}", provider_name="CV", original_exception=e)

        if "Just a moment..." in html_content and "<title>Just a moment..." in html_content:
            raise ProviderConnectionError("Comic Vine returned a Cloudflare verification challenge.", provider_name="CV")

        return html_content
