"""
services/search.py — Phase 32

Search service: issue number extraction and provider search delegation.
No HTTP or archive I/O concerns.
"""
import re
from typing import Tuple

from services.metadata import search_all_providers   # re-exported for backwards compat


def extract_issue_num_from_filename(filename: str) -> str:
    fname = re.sub(r"\.(cbz|cbr|zip|rar)$", "", filename, flags=re.I)

    # 1. Handle half issues
    m_half = re.search(r"(?:issue\s*#?|#|\b)0*(?:½|1/2|0\.5)\b", fname, re.I)
    if m_half or "½" in fname or "1/2" in fname:
        return "0.5"

    # 2. Check for Issue #000 / #0
    m_zero = re.search(r"\bissue\s*#?\s*(0+)(?!\d)", fname, re.I)
    if m_zero:
        return "0"
    m_zero_hash = re.search(r"#\s*(0+)(?!\d)", fname)
    if m_zero_hash:
        return "0"

    # 3. Standard matching
    m = re.search(r"\bissue\s*#?\s*0*(\d+[a-zA-Z]?|\d+\.\d+|\d+)", fname, re.I)
    if m:
        return m.group(1)

    m = re.search(r"#\s*0*(\d+[a-zA-Z]?|\d+\.\d+|\d+)", fname)
    if m:
        return m.group(1)

    m = re.search(r"\bv(\d+)\b", fname, re.I)
    if m:
        fname = fname.replace(m.group(0), "")

    m = re.search(r"\b(19\d\d|20\d\d)\b", fname)
    if m:
        fname = fname.replace(m.group(0), "")

    m = re.search(r"\b0+(?!\d)", fname)
    if m:
        return "0"

    m = re.search(r"0*(\d+)\b", fname)
    if m:
        return m.group(1)

    return ""
