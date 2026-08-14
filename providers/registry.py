"""
providers/registry.py — Phase 84: Provider Registry

Central registry for metadata providers (Kapowarr, ComicVine, GCD/GCP).
Decouples resolver from concrete provider classes and allows dynamic registration and priority ordering.
"""

from typing import Dict, List, Optional, Any
from providers.base import BaseProvider
from providers.kapowarr import KapowarrProvider
from providers.comicvine import ComicVineProvider
from providers.gcp import GCPProvider


class ProviderRegistry:
    """
    Central registry for metadata provider implementations.
    Allows dynamic registration, priority ordering, and retrieval.
    """

    def __init__(self, priority: Optional[List[str]] = None):
        self._providers: Dict[str, BaseProvider] = {}
        self._priority: List[str] = [p.lower().strip() for p in (priority or ["kapowarr", "comicvine", "gcd"])]

    def register(self, name: str, provider: BaseProvider) -> None:
        """Registers a provider instance under a normalized name."""
        norm_name = self._normalize_name(name)
        self._providers[norm_name] = provider

    def unregister(self, name: str) -> None:
        """Unregisters a provider."""
        norm_name = self._normalize_name(name)
        self._providers.pop(norm_name, None)

    def get(self, name: str) -> Optional[BaseProvider]:
        """Retrieves a provider by name (case-insensitive, e.g. 'kapowarr', 'comicvine', 'gcd', 'gcp')."""
        norm_name = self._normalize_name(name)
        return self._providers.get(norm_name)

    def get_provider(self, name: str) -> Optional[BaseProvider]:
        """Alias for get()."""
        return self.get(name)

    def has_provider(self, name: str) -> bool:
        """Returns True if provider is registered."""
        norm_name = self._normalize_name(name)
        return norm_name in self._providers

    def list_providers(self) -> List[str]:
        """Returns list of registered provider names."""
        return list(self._providers.keys())

    @property
    def priority(self) -> List[str]:
        """Returns configured priority list."""
        return list(self._priority)

    @priority.setter
    def priority(self, new_priority: List[str]) -> None:
        """Updates provider priority order."""
        self._priority = [p.lower().strip() for p in new_priority]

    def get_ordered_providers(self) -> List[BaseProvider]:
        """Returns list of active registered providers in priority order."""
        ordered: List[BaseProvider] = []
        for name in self._priority:
            norm = self._normalize_name(name)
            if norm in self._providers:
                prov = self._providers[norm]
                if prov not in ordered:
                    ordered.append(prov)
        for norm, prov in self._providers.items():
            if prov not in ordered:
                ordered.append(prov)
        return ordered

    def _normalize_name(self, name: str) -> str:
        n = name.lower().strip()
        if n in ("cv", "comic_vine", "comicvine"):
            return "comicvine"
        if n in ("gcd", "gcp", "grandcomicsdatabase", "grandcomics"):
            return "gcd"
        if n in ("kapowarr", "kap"):
            return "kapowarr"
        return n

    @classmethod
    def from_config(cls, config: Optional[Any] = None, **kwargs) -> "ProviderRegistry":
        """
        Builds and initializes standard providers from Config object or explicit overrides.
        """
        priority = None
        if config and hasattr(config, "providers") and hasattr(config.providers, "priority"):
            priority = config.providers.priority

        registry = cls(priority=priority)

        # Kapowarr
        if "kapowarr" in kwargs and kwargs["kapowarr"] is not None:
            registry.register("kapowarr", kwargs["kapowarr"])
        elif config and hasattr(config, "kapowarr"):
            registry.register("kapowarr", KapowarrProvider(url=config.kapowarr.url, api_key=config.kapowarr.api_key))
        else:
            registry.register("kapowarr", KapowarrProvider())

        # ComicVine
        if "comicvine" in kwargs and kwargs["comicvine"] is not None:
            registry.register("comicvine", kwargs["comicvine"])
        elif config and hasattr(config, "comicvine"):
            registry.register("comicvine", ComicVineProvider(api_key=config.comicvine.api_key))
        else:
            registry.register("comicvine", ComicVineProvider())

        # GCD / GCP
        if "gcp" in kwargs and kwargs["gcp"] is not None:
            registry.register("gcd", kwargs["gcp"])
        elif "gcd" in kwargs and kwargs["gcd"] is not None:
            registry.register("gcd", kwargs["gcd"])
        else:
            registry.register("gcd", GCPProvider())

        return registry
