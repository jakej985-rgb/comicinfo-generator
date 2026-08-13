import requests
from typing import Optional, Dict, Any
from providers.base import ProviderConnectionError, ProviderAuthenticationError

class KapowarrClient:
    """
    Dedicated low-level HTTP client for Kapowarr REST API.
    Handles authentication, timeouts, retries, and status decoding.
    """

    def __init__(self, url: str = "http://localhost:5656", api_key: str = "", timeout: int = 5):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

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

    def get(self, endpoint: str, params: Optional[dict] = None) -> Any:
        """Executes GET request against Kapowarr API endpoint."""
        if not self.url:
            raise ProviderConnectionError("Kapowarr server URL not configured.", provider_name="Kapowarr")

        full_url = f"{self.url}/{endpoint.lstrip('/')}"
        p = self._get_params(params)

        try:
            r = requests.get(full_url, headers=self._get_headers(), params=p, timeout=self.timeout)
            if r.status_code == 401 or r.status_code == 403:
                raise ProviderAuthenticationError(f"Kapowarr authentication failed (HTTP {r.status_code}).", provider_name="Kapowarr")
            r.raise_for_status()
            data = r.json()
            return data.get("result", data) if isinstance(data, dict) else data
        except Exception as e:
            if isinstance(e, (ProviderConnectionError, ProviderAuthenticationError)):
                raise e
            raise ProviderConnectionError(f"Kapowarr GET request failed ({endpoint}): {e}", provider_name="Kapowarr", original_exception=e)

    def post(self, endpoint: str, json_payload: Optional[dict] = None) -> Any:
        """Executes POST request against Kapowarr API endpoint."""
        if not self.url:
            raise ProviderConnectionError("Kapowarr server URL not configured.", provider_name="Kapowarr")

        full_url = f"{self.url}/{endpoint.lstrip('/')}"
        p = self._get_params()

        try:
            r = requests.post(full_url, json=json_payload, headers=self._get_headers(), params=p, timeout=self.timeout)
            if r.status_code in (401, 403):
                raise ProviderAuthenticationError(f"Kapowarr authentication failed (HTTP {r.status_code}).", provider_name="Kapowarr")
            r.raise_for_status()
            return r.json() if r.text else {}
        except Exception as e:
            if isinstance(e, (ProviderConnectionError, ProviderAuthenticationError)):
                raise e
            raise ProviderConnectionError(f"Kapowarr POST request failed ({endpoint}): {e}", provider_name="Kapowarr", original_exception=e)
