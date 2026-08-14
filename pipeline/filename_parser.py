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
    # Safely handle fractional issue filenames (e.g. #1/2) that might otherwise be split by os.path.basename
    if re.search(r"#\s*\d+/\d+", file_path) and not os.path.isabs(file_path) and not os.path.exists(file_path):
        basename = file_path
        parent_dir = ""
    else:
        basename = os.path.basename(file_path)
        parent_dir = os.path.basename(os.path.dirname(os.path.abspath(file_path)))

    name_no_ext = os.path.splitext(basename)[0]

    # Edition markers & Exclusions (Phase 90.3)
    lower_name = name_no_ext.lower()
    tpb_keywords = [
        "tpb", "trade paperback", "hc", "hardcover", "gn", "graphic novel",
        "omnibus", "compendium", "masterworks", "collection", "deluxe",
        "deluxe edition", "collected edition", "complete edition",
        "vol 0", "vol.0", "volume 0", "vol 1 tpb", "vol.1 tpb", "vol 1 hc", "volume 1 tpb"
    ]
    if any(re.search(r"\b" + re.escape(k) + r"\b", lower_name) for k in tpb_keywords):
        res.is_tpb = True

    # Special issue markers (Phase 90.2)
    if "annual" in lower_name:
        res.is_annual = True
    if any(k in lower_name for k in ["special", "giant", "fcbd", "free comic book day", "preview", "one-shot", "oneshot"]):
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

    # Extract issue number (e.g. #001, #1A, #1.5, 001, #0, #1/2, Annual 1, FCBD, Preview, One-Shot)
    m_num = None
    # 1. Named specials
    if re.search(r"\bannual\s*#?\s*(\d+)\b", name_no_ext, re.I):
        m_num = re.search(r"\bannual\s*#?\s*(\d+)\b", name_no_ext, re.I)
        res.issue_number = str(int(m_num.group(1)))
        res.is_annual = True
    elif re.search(r"\bannual\b", name_no_ext, re.I):
        res.issue_number = "Annual"
        res.is_annual = True
    elif re.search(r"\b(fcbd|free comic book day)\b", name_no_ext, re.I):
        res.issue_number = "FCBD"
    elif re.search(r"\b(one-shot|oneshot)\b", name_no_ext, re.I):
        res.issue_number = "One-Shot"
    elif re.search(r"\bpreview\b", name_no_ext, re.I):
        res.issue_number = "Preview"
    elif re.search(r"\bspecial\s*#?\s*(\d+)\b", name_no_ext, re.I):
        m_num = re.search(r"\bspecial\s*#?\s*(\d+)\b", name_no_ext, re.I)
        res.issue_number = str(int(m_num.group(1)))
        res.is_special = True
    elif re.search(r"\bspecial\b", name_no_ext, re.I):
        res.issue_number = "Special"
        res.is_special = True
    else:
        # 2. Standard and fractional numbers
        m_num = re.search(r"#\s*(\d+½|\d+/\d+|\d+\.\d+|\d+[a-zA-Z]?|½|1/2|0\.5|0+)", name_no_ext)
        if not m_num:
            m_num = re.search(r"\bissue\s*#?\s*(\d+½|\d+/\d+|\d+\.\d+|\d+[a-zA-Z]?|½|1/2|0\.5|0+)", name_no_ext, re.I)
        if not m_num:
            # Fallback to trailing space/underscore/dash number e.g. "Batman 001", "Batman_001"
            m_num = re.search(r"(?:^|[\s_\-#])(\d{1,4}[a-zA-Z]?)\b(?=[^\d]*$)", name_no_ext)

        if m_num:
            raw_num = m_num.group(1).strip()
            if raw_num in ("½", "1/2", "0.5") or raw_num.endswith("½") or raw_num.endswith("1/2"):
                if raw_num in ("½", "1/2", "0.5"):
                    res.issue_number = "0.5"
                else:
                    prefix = re.sub(r"[½|1/2]", "", raw_num).strip()
                    res.issue_number = f"{prefix}.5"
            elif raw_num.isdigit():
                res.issue_number = str(int(raw_num))
            elif re.match(r"^0+(\d+)$", raw_num):
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

    if res.is_annual and not clean.lower().endswith("annual") and "annual" in name_no_ext.lower():
        clean = f"{clean} Annual".strip()
    elif res.is_special and not clean.lower().endswith("special") and "special" in name_no_ext.lower():
        clean = f"{clean} Special".strip()

    # If parent dir has a clean series name (e.g. "Batman (2016)"), use parent dir as fallback/preference
    if parent_dir and parent_dir.lower() not in ("comics", "downloads", "tmp", "temp"):
        clean_parent = re.sub(r"[\(\[\b](19\d\d|20\d\d)[\)\]\b]", "", parent_dir)
        clean_parent = re.sub(r"[_\-\.\(\)\[\]]+", " ", clean_parent).strip()
        if clean_parent and (not clean or clean.lower() == clean_parent.lower()):
            clean = clean_parent

    res.series_name = clean if clean else (parent_dir or name_no_ext)
    return res
