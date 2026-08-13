from abc import ABC, abstractmethod
from typing import Optional, Tuple, List
from models.comic import Comic

# --- Provider Response Status States ---
STATE_SUCCESS = "SUCCESS"
STATE_NOT_FOUND = "NOT_FOUND"
STATE_CONNECTION_ERROR = "CONNECTION_ERROR"
STATE_AUTH_ERROR = "AUTH_ERROR"
STATE_RATE_LIMITED = "RATE_LIMITED"
STATE_PARSE_ERROR = "PARSE_ERROR"
STATE_INVALID_RESPONSE = "INVALID_RESPONSE"


# --- Provider Exceptions ---
class ProviderError(Exception):
    """Base exception for provider operations."""
    def __init__(self, message: str, provider_name: str = "", original_exception: Optional[Exception] = None):
        super().__init__(message)
        self.provider_name = provider_name
        self.original_exception = original_exception

class ProviderConnectionError(ProviderError):
    """Raised when connecting to provider service fails."""

class ProviderAuthenticationError(ProviderError):
    """Raised when authentication/API key fails."""

class ProviderRateLimitError(ProviderError):
    """Raised when provider rate limits requests."""

class ProviderParseError(ProviderError):
    """Raised when parsing provider response fails."""

class ProviderResponseError(ProviderError):
    """Raised when provider returns an invalid or malformed response."""

class MetadataNotFoundError(ProviderError):
    """Raised when queried metadata item is not found."""


class BaseProvider(ABC):
    """
    Abstract Base Class for metadata providers (Kapowarr, ComicVine, GCP, etc.).
    All providers return normalized Comic objects and standardized search/lookup dictionaries.
    """

    @abstractmethod
    def get_name(self) -> str:
        """Returns provider identifier name (e.g. 'Kapowarr', 'CV', 'GCP')."""
        pass

    @abstractmethod
    def search_series(self, query: str) -> list[dict]:
        """Searches for comic series matching query."""
        pass

    @abstractmethod
    def search_issue(self, query: str) -> list[dict]:
        """Searches for comic issues matching query."""
        pass

    @abstractmethod
    def lookup_volume(self, volume_id: str) -> tuple[str, dict[str, str], list[dict]]:
        """
        Looks up volume/series information.
        Returns: (series_name, issue_map_dict, issue_list)
        """
        pass

    @abstractmethod
    def lookup_issue(self, issue_id_or_url: str) -> Optional[Comic]:
        """
        Looks up a single issue by ID, URL, or identifier.
        Returns normalized Comic object or None if not found.
        """
        pass

    def download_cover(self, url: str) -> bytes:
        """Downloads cover image bytes if available."""
        return b""
