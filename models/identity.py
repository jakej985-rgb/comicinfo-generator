import re
from dataclasses import dataclass, field
from typing import List, Optional, Any
from pipeline.issue_order import parse_issue_order, IssueOrder


def _normalize_series(title: str) -> str:
    if not title:
        return ""
    t = title.lower().strip()
    t = re.sub(r'^(the|a|an)\s+', '', t)
    t = re.sub(r'[\W_]+', ' ', t)
    return ' '.join(t.split())


@dataclass(frozen=True)
class CanonicalIdentityKey:
    """
    Phase 59: Canonical comic identity comparison key.
    Normalizes series name, volume, issue number/suffix, year, and publisher for accurate comparison
    WITHOUT destroying the original raw issue number or metadata string.
    """
    series_norm: str
    issue_numeric: float
    issue_suffix: str
    is_named: bool
    volume_norm: str
    year: int
    publisher_norm: str

    @classmethod
    def from_identity(cls, identity: "ComicIdentity") -> "CanonicalIdentityKey":
        order = parse_issue_order(identity.issue_number or "")
        return cls(
            series_norm=_normalize_series(identity.series_name),
            issue_numeric=order.numeric_value,
            issue_suffix=order.letter_suffix.upper(),
            is_named=order.is_named,
            volume_norm=str(identity.volume).strip().lower() if identity.volume else "",
            year=int(identity.publication_year or 0),
            publisher_norm=_normalize_series(identity.publisher)
        )

    @classmethod
    def from_parsed(cls, parsed: Any) -> "CanonicalIdentityKey":
        order = parse_issue_order(getattr(parsed, "issue_number", "") or "")
        return cls(
            series_norm=_normalize_series(getattr(parsed, "series_name", "")),
            issue_numeric=order.numeric_value,
            issue_suffix=order.letter_suffix.upper(),
            is_named=order.is_named,
            volume_norm=str(getattr(parsed, "volume", "")).strip().lower() if getattr(parsed, "volume", None) else "",
            year=int(getattr(parsed, "year", 0) or 0),
            publisher_norm=_normalize_series(getattr(parsed, "publisher", ""))
        )

    def matches(self, other: "CanonicalIdentityKey", allow_year_tolerance: bool = True) -> bool:
        """
        Determines if two canonical identity keys match the same comic edition.
        """
        if self.series_norm and other.series_norm and self.series_norm != other.series_norm:
            return False

        if self.issue_numeric != other.issue_numeric or self.issue_suffix != other.issue_suffix:
            return False

        if self.is_named != other.is_named:
            return False

        if self.volume_norm and other.volume_norm and self.volume_norm != other.volume_norm:
            return False

        if self.year > 0 and other.year > 0:
            diff = abs(self.year - other.year)
            if allow_year_tolerance and diff > 1:
                return False
            elif not allow_year_tolerance and diff > 0:
                return False

        return True


@dataclass
class IdentityEvidence:
    """Represents a specific evidence signal that contributed to identity candidate scoring."""
    source: str = ""        # e.g. "Comic Vine", "Filename", "Kapowarr"
    field: str = ""         # e.g. "issue_number", "series_name", "publisher"
    expected: str = ""      # Expected value from target file
    actual: str = ""        # Actual value from provider candidate
    score: float = 0.0      # Score points (+30, -50, etc.)
    explanation: str = ""   # Human-readable explanation


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
    identity_type: str = "Issue"      # "Issue", "Volume", "TPB", "Collected"
    volume_id: str = ""               # Provider-specific volume/series ID for cross-issue grouping
    resolution_source: str = ""       # e.g. "url_override", "existing_comicinfo", "persistent_cache", "kapowarr", "comicvine_fallback", "gcd_fallback"
    fallback_used: bool = False       # True if a fallback provider was used
    fallback_reason: str = ""         # Reason why fallback was triggered
    confidence: float = 0.0           # Confidence score (0.0 to 100.0)
    confidence_level: str = "UNRESOLVED" # "AUTO_ACCEPT", "MANUAL_REVIEW", "UNRESOLVED"
    confidence_reasons: List[str] = field(default_factory=list)
    evidence: List[IdentityEvidence] = field(default_factory=list)

    @property
    def is_resolved(self) -> bool:
        """Returns True if identity confidence meets threshold."""
        return self.confidence >= 50.0 and bool(self.series_name)

    @property
    def canonical_key(self) -> CanonicalIdentityKey:
        """Returns the canonical comparison key for this identity."""
        return CanonicalIdentityKey.from_identity(self)

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
            "identity_type": self.identity_type,
            "resolution_source": self.resolution_source,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level,
            "confidence_reasons": self.confidence_reasons,
            "evidence": [e.__dict__ for e in self.evidence],
            "is_resolved": self.is_resolved
        }
