import re
import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class ParsedFilename:
    series_name: str = ""
    volume: str = ""
    issue_number: str = ""
    year: int = 0
    publisher: str = ""
    is_tpb: bool = False
    is_annual: bool = False
    is_special: bool = False

def parse_filename_identity(file_path: str) -> ParsedFilename:
    """
    Parses a comic file path or filename to extract identity signals
    including series title, issue number, publication year, volume, and edition markers.
    """
    res = ParsedFilename()
    basename = os.path.basename(file_path)
    name_no_ext = os.path.splitext(basename)[0]

    # Check parent folder for series/year context (e.g. "Batman (2016)/Batman #001.cbz")
    parent_dir = os.path.basename(os.path.dirname(os.path.abspath(file_path)))

    # Edition markers
    lower_name = name_no_ext.lower()
    if any(k in lower_name for k in ["tpb", "trade paperback", "collection", "omnibus", "vol 0", "vol.0", "volume 0", "vol 1", "vol.1"]):
        res.is_tpb = True
    if "annual" in lower_name:
        res.is_annual = True
    if any(k in lower_name for k in ["special", "giant", "fcbd", "preview", "one-shot", "oneshot"]):
        res.is_special = True

    # Extract year (e.g. (2016) or [2016])
    m_year = re.search(r"[\(\[\b](19\d\d|20\d\d)[\)\]\b]", name_no_ext)
    if not m_year and parent_dir:
        m_year = re.search(r"[\(\[\b](19\d\d|20\d\d)[\)\]\b]", parent_dir)
    if m_year:
        res.year = int(m_year.group(1))

    # Extract volume (e.g. v1, v01, Vol. 01, Volume 1)
    m_vol = re.search(r"\b(?:v|vol|volume)\.?\s*(\d+)\b", name_no_ext, re.I)
    if m_vol:
        res.volume = m_vol.group(1).lstrip("0") or "1"

    # Extract issue number (e.g. #001, #1A, #1.5, 001, #0, #1/2)
    # Prefer explicit hash notation #1
    m_num = re.search(r"#\s*(\d+½|\d+/\d+|\d+\.\d+|\d+[a-zA-Z]?|½|1/2|0\.5|0)", name_no_ext)
    if not m_num:
        # Fallback to issue keyword Issue 01
        m_num = re.search(r"\bissue\s*#?\s*(\d+½|\d+/\d+|\d+\.\d+|\d+[a-zA-Z]?|½|1/2|0\.5|0)", name_no_ext, re.I)
    if not m_num:
        # Fallback to trailing space number e.g. "Batman 001"
        m_num = re.search(r"\b(\d{1,4}[a-zA-Z]?)\b(?=[^\d]*$)", name_no_ext)

    if m_num:
        raw_num = m_num.group(1).strip()
        if raw_num in ("½", "1/2", "0.5"):
            res.issue_number = "0.5"
        elif raw_num.isdigit():
            res.issue_number = str(int(raw_num))
        else:
            res.issue_number = raw_num

    # Extract series name by removing year, issue number, volume, extension formatting & subtitles
    clean = name_no_ext

    # If issue number match was found, split title subtitle at issue number
    if m_num and m_num.start() > 0:
        clean = clean[:m_num.start()]

    clean = re.sub(r"[\(\[\b](19\d\d|20\d\d)[\)\]\b]", "", clean)
    clean = re.sub(r"\b(?:v|vol|volume)\.?\s*\d+\b", "", clean, flags=re.I)
    clean = re.sub(r"#\s*(\d+½|\d+/\d+|\d+\.\d+|\d+[a-zA-Z]?|½|1/2|0\.5|0)", "", clean)
    clean = re.sub(r"\bissue\s*#?\s*(\d+½|\d+/\d+|\d+\.\d+|\d+[a-zA-Z]?|½|1/2|0\.5|0)", "", clean, flags=re.I)
    clean = re.sub(r"[_\-\.\(\)\[\]]+", " ", clean).strip()

    # If parent dir has a clean series name (e.g. "Batman (2016)"), use parent dir as fallback/preference
    if parent_dir and parent_dir.lower() not in ("comics", "downloads", "tmp", "temp"):
        clean_parent = re.sub(r"[\(\[\b](19\d\d|20\d\d)[\)\]\b]", "", parent_dir)
        clean_parent = re.sub(r"[_\-\.\(\)\[\]]+", " ", clean_parent).strip()
        if clean_parent and (not clean or clean.lower() == clean_parent.lower()):
            clean = clean_parent

    res.series_name = clean if clean else (parent_dir or name_no_ext)
    return res
