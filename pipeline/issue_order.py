"""
Phase 27: Complex Issue Ordering system.

Supports numeric, fractional, lettered, and named issue numbers:
  0, 0.5, 1, 1A, 1B, 1.5, 2, Annual, Special, etc.

Never uses raw int(number) comparisons.
"""
import re
from dataclasses import dataclass
from typing import Optional

# Named issue types sorted after regular numbers
_NAMED_ORDER = {
    "annual": 10000.0,
    "special": 10001.0,
    "tpb": 10002.0,
    "hc": 10003.0,
    "omnibus": 10004.0,
}

@dataclass
class IssueOrder:
    """Explicit normalized representation of an issue number for ordering."""
    raw: str
    numeric_value: float       # Primary sort key (e.g., 1.5 for "1.5", 10000 for "Annual")
    letter_suffix: str = ""    # Secondary sort key (e.g., "A" for "1A")
    is_named: bool = False     # True for Annual, Special, etc.

    def sort_key(self):
        return (self.numeric_value, self.letter_suffix)

    def __lt__(self, other: "IssueOrder"):
        return self.sort_key() < other.sort_key()

    def __le__(self, other: "IssueOrder"):
        return self.sort_key() <= other.sort_key()

    def __eq__(self, other: "IssueOrder"):
        return self.sort_key() == other.sort_key()

    def __repr__(self):
        return f"IssueOrder(raw={self.raw!r}, numeric={self.numeric_value}, suffix={self.letter_suffix!r})"


def parse_issue_order(raw: str) -> IssueOrder:
    """
    Parses any issue number string into a normalized IssueOrder for sorting.
    Examples:
      "0"      -> IssueOrder(0.0, "")
      "0.5"    -> IssueOrder(0.5, "")
      "1"      -> IssueOrder(1.0, "")
      "1A"     -> IssueOrder(1.0, "A")
      "1B"     -> IssueOrder(1.0, "B")
      "1.5"    -> IssueOrder(1.5, "")
      "Annual" -> IssueOrder(10000.0, "", is_named=True)
      "Special #1" -> IssueOrder(10001.0, "")
    """
    if not raw:
        return IssueOrder(raw="", numeric_value=99999.0)

    normalized = raw.strip()

    # Check named types first (case-insensitive)
    normalized_lower = normalized.lower()
    for name, order_val in _NAMED_ORDER.items():
        if normalized_lower.startswith(name):
            return IssueOrder(raw=raw, numeric_value=order_val, is_named=True)

    # Match: optional digits, optional dot+digits, optional letter suffix
    # e.g. "1", "1A", "1B", "0.5", "1.5", "12B"
    match = re.match(r'^(\d+(?:\.\d+)?)([A-Za-z]*)$', normalized)
    if match:
        numeric_str, letter = match.groups()
        return IssueOrder(raw=raw, numeric_value=float(numeric_str), letter_suffix=letter.upper())

    # Fallback: try to extract leading number
    leading = re.match(r'^(\d+(?:\.\d+)?)', normalized)
    if leading:
        return IssueOrder(raw=raw, numeric_value=float(leading.group(1)))

    # Non-numeric: sort at the end
    return IssueOrder(raw=raw, numeric_value=99998.0)


def sort_issues(issue_numbers: list) -> list:
    """
    Sorts a list of raw issue number strings using IssueOrder normalization.
    Returns sorted list of raw strings.
    """
    parsed = [(parse_issue_order(n), n) for n in issue_numbers]
    parsed.sort(key=lambda x: x[0].sort_key())
    return [n for _, n in parsed]
