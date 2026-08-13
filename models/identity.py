from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class ComicIdentity:
    """
    Represents the resolved identity of a comic issue/volume
    separately from full metadata details.
    """
    provider: str = ""                # e.g. "Kapowarr", "ComicVine", "GCP", "ExistingXML"
    provider_id: str = ""             # Unique ID assigned by primary provider
    series_provider: str = ""         # Provider managing series volume
    series_id: str = ""               # Series / Volume ID (e.g. "4050-12345")
    issue_provider: str = ""          # Provider managing issue
    issue_id: str = ""                # Issue ID (e.g. "4000-98765")
    series_name: str = ""             # Normalized series title
    publisher: str = ""               # Publisher name
    publication_year: int = 0         # Primary publication year
    volume: str = ""                  # Volume number/year
    issue_number: str = ""            # Issue number string (e.g. "1", "1A", "0.5")
    confidence: float = 0.0           # Confidence score (0.0 to 1.0)
    confidence_reasons: List[str] = field(default_factory=list)

    @property
    def is_resolved(self) -> bool:
        """Returns True if identity confidence meets threshold."""
        return self.confidence >= 0.5 and bool(self.series_name)

    def to_dict(self) -> dict:
        """Converts identity instance to dictionary."""
        return {
            "provider": self.provider,
            "provider_id": self.provider_id,
            "series_provider": self.series_provider,
            "series_id": self.series_id,
            "issue_provider": self.issue_provider,
            "issue_id": self.issue_id,
            "series_name": self.series_name,
            "publisher": self.publisher,
            "publication_year": self.publication_year,
            "volume": self.volume,
            "issue_number": self.issue_number,
            "confidence": self.confidence,
            "confidence_reasons": self.confidence_reasons,
            "is_resolved": self.is_resolved
        }
