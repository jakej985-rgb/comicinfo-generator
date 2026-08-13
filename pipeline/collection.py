"""
Phase 26: TPB / Collected Edition Merging with pre-merge validation.

Validates a set of issues before permitting collection merging:
  - same series
  - compatible publisher
  - same provider volume
  - compatible numbering (no conflicting identities)

Reject: Batman #1 + Detective Comics #1 (different series)
Warn:   Batman #1 + Batman #1A (same base number, lettered variant)
Accept: Batman #1 + Batman #2 + Batman #3
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from models.identity import ComicIdentity
from pipeline.issue_order import parse_issue_order, sort_issues, IssueOrder

RESULT_ACCEPT  = "ACCEPT"
RESULT_WARN    = "WARN"
RESULT_REJECT  = "REJECT"

@dataclass
class CollectionIssue:
    """A single issue being considered for inclusion in a TPB/collection."""
    identity: ComicIdentity
    issue_number: str
    order: IssueOrder = field(default=None)

    def __post_init__(self):
        if self.order is None:
            self.order = parse_issue_order(self.issue_number)

@dataclass
class CollectionValidationResult:
    """Result of collection pre-merge validation."""
    result: str                      # ACCEPT / WARN / REJECT
    issues: List[str] = field(default_factory=list)   # Validation problem descriptions
    sorted_issue_numbers: List[str] = field(default_factory=list)

def _normalize_series(name: str) -> str:
    """Lowercases and strips punctuation for loose comparison."""
    import re
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()

def _normalize_publisher(name: str) -> str:
    return (name or "").lower().strip()

def validate_collection(candidates: List[CollectionIssue]) -> CollectionValidationResult:
    """
    Validates a list of CollectionIssues before merging into a TPB/collection.

    Rules:
      REJECT if:
        - Issues come from different series (different series_name after normalization)
        - Issues come from different provider volumes (different volume_id)
      WARN if:
        - Issues share the same base number with different letter variants (1 and 1A)
        - Publisher differs across issues
      ACCEPT otherwise.
    """
    if not candidates:
        return CollectionValidationResult(
            result=RESULT_REJECT,
            issues=["No issues provided to validate."]
        )

    problems = []
    warnings = []

    # --- Series consistency check ---
    series_names = set(_normalize_series(c.identity.series_name or "") for c in candidates)
    if len(series_names) > 1:
        problems.append(
            f"REJECT: Issues span multiple series: {sorted(series_names)}"
        )

    # --- Publisher consistency check (warning only) ---
    publishers = set(_normalize_publisher(c.identity.publisher or "") for c in candidates if c.identity.publisher)
    if len(publishers) > 1:
        warnings.append(
            f"WARN: Publisher mismatch across issues: {sorted(publishers)}"
        )

    # --- Provider volume ID consistency check ---
    volume_ids = set(c.identity.volume_id for c in candidates if getattr(c.identity, "volume_id", None))
    if len(volume_ids) > 1:
        problems.append(
            f"REJECT: Issues come from different provider volumes: {sorted(str(v) for v in volume_ids)}"
        )

    # --- Issue numbering conflict check ---
    # Group by base numeric value — 1 and 1A share base 1.0
    base_number_groups: dict = {}
    for c in candidates:
        base = c.order.numeric_value
        base_number_groups.setdefault(base, []).append(c)

    for base, group in base_number_groups.items():
        if len(group) > 1:
            raws = [g.issue_number for g in group]
            # If all have the same raw string → duplicate
            if len(set(raws)) == 1:
                problems.append(
                    f"REJECT: Duplicate issue number {raws[0]!r} appears {len(group)} times."
                )
            else:
                # Different letters sharing same base (1 and 1A) → warning
                warnings.append(
                    f"WARN: Issues share base number {base} with different variants: {raws}"
                )

    # --- Determine final result ---
    all_issue_numbers = [c.issue_number for c in candidates]
    sorted_numbers = sort_issues(all_issue_numbers)

    if problems:
        return CollectionValidationResult(
            result=RESULT_REJECT,
            issues=problems + warnings,
            sorted_issue_numbers=sorted_numbers
        )
    elif warnings:
        return CollectionValidationResult(
            result=RESULT_WARN,
            issues=warnings,
            sorted_issue_numbers=sorted_numbers
        )
    else:
        return CollectionValidationResult(
            result=RESULT_ACCEPT,
            issues=[],
            sorted_issue_numbers=sorted_numbers
        )
