import re
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class IssueNumber:
    """
    Represents a normalized comic issue number preserving variant suffixes,
    decimals, zero-padding, and special issue indicators without converting all to integers.
    """
    raw: str = ""
    clean: str = ""
    number_part: float = 0.0
    suffix: str = ""
    is_annual: bool = False
    is_special: bool = False

    @classmethod
    def parse(cls, val: str) -> "IssueNumber":
        if not val:
            return cls()

        raw_str = str(val).strip()
        lower = raw_str.lower()

        is_annual = "annual" in lower
        is_special = any(k in lower for k in ["special", "giant", "one-shot", "oneshot", "preview", "fcbd"])

        if is_annual:
            m_ann = re.search(r"\d+", raw_str)
            num_val = float(m_ann.group(0)) if m_ann else 1.0
            return cls(raw=raw_str, clean=f"Annual #{int(num_val)}", number_part=num_val, is_annual=True)

        if is_special:
            return cls(raw=raw_str, clean="Special", is_special=True)

        # Handle fractions ½, 1/2
        if raw_str in ("½", "1/2"):
            return cls(raw=raw_str, clean="0.5", number_part=0.5)

        # Regex to split numeric prefix and alpha suffix (e.g. "1A", "0.5", "001", "10.1")
        m = re.match(r"^(\d+(?:\.\d+)?)([a-zA-Z]*)$", raw_str)
        if m:
            num_str = m.group(1)
            suffix = m.group(2)
            num_val = float(num_str)
            clean_str = f"{num_str.lstrip('0') or '0'}{suffix}"
            return cls(raw=raw_str, clean=clean_str, number_part=num_val, suffix=suffix)

        return cls(raw=raw_str, clean=raw_str)

    def matches(self, other: "IssueNumber") -> bool:
        """Returns True if two issue numbers represent the same issue."""
        if not self.raw or not other.raw:
            return False
        if self.is_annual and other.is_annual:
            return self.number_part == other.number_part
        if self.is_special and other.is_special:
            return True
        return self.clean.lower() == other.clean.lower() or (
            self.number_part == other.number_part and self.suffix.lower() == other.suffix.lower()
        )
