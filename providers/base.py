from abc import ABC, abstractmethod
from typing import Optional, Tuple
from models.comic import Comic

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
