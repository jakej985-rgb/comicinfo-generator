import re
from typing import Tuple, List, Dict
from bs4 import BeautifulSoup
from models.comic import Comic

MONTH_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10,
    "november": 11, "nov": 11, "december": 12, "dec": 12
}

def parse_date(date_str: str) -> Tuple[int, int, int]:
    """Extracts (year, month, day) from date string."""
    date_str = date_str.strip()
    
    # ISO format YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
        
    # Month DD, YYYY
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", date_str)
    if m:
        month_name = m.group(1).lower()
        month = MONTH_MAP.get(month_name, 0)
        return int(m.group(3)), month, int(m.group(2))
        
    # Month YYYY
    m = re.search(r"([A-Za-z]+)\s+(\d{4})", date_str)
    if m:
        month_name = m.group(1).lower()
        month = MONTH_MAP.get(month_name, 0)
        return int(m.group(2)), month, 0

    # Year only
    m = re.search(r"\b(\d{4})\b", date_str)
    if m:
        return int(m.group(1)), 0, 0

    return 0, 0, 0


def parse_series(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        s_link = h1.find("a", class_="wiki-title")
        if s_link:
            return s_link.get_text(strip=True)
        h1_txt = " ".join(h1.get_text(" ", strip=True).split())
        m = re.match(r"(.+?)\s+#?(\d+[a-zA-Z]?|\d+\.\d+|\d+)", h1_txt)
        if m:
            return m.group(1).strip()
    return ""


def parse_issue_number(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        i_link = h1.find("a", class_="wiki-issue-number")
        if i_link:
            return i_link.get_text(strip=True).lstrip("#").strip()
        h1_txt = " ".join(h1.get_text(" ", strip=True).split())
        m = re.match(r"(.+?)\s+#?(\d+[a-zA-Z]?|\d+\.\d+|\d+)", h1_txt)
        if m:
            return m.group(2).strip()
    return ""


def parse_title(soup: BeautifulSoup, series: str = "", number: str = "") -> str:
    page_text = " ".join(soup.get_text(" ", strip=True).split())
    m_name = re.search(r"Issue details\s+Name\s+(.+?)\s+Name\s+Name of this issue", page_text)
    if m_name:
        val = m_name.group(1).strip()
        if val and val.lower() not in ("none", "name"):
            return val

    og_title = soup.find("meta", attrs={"property": "og:title"}) or soup.find("meta", attrs={"name": "twitter:title"})
    if og_title:
        og_txt = og_title.get("content", "")
        m = re.search(r"#\d+[a-zA-Z]?\s*[:-]\s*(.+?)(?:\s*\(Issue\)|$)", og_txt)
        if m:
            return m.group(1).strip()

    h1 = soup.find("h1")
    if h1:
        h1_txt = " ".join(h1.get_text(" ", strip=True).split())
        m = re.search(r"#\d+[a-zA-Z]?\s*[:-]\s*(.+)", h1_txt)
        if m:
            return m.group(1).strip()

    if series:
        return f"{series} #{number}" if number else series
    return ""


def parse_publisher(soup: BeautifulSoup) -> str:
    desc_elem = soup.find(class_="wiki-descriptor")
    if desc_elem:
        txt = desc_elem.get_text(" ", strip=True)
        m = re.search(r"released by\s+(.+?)(?:\s+on|\.|$)", txt, re.I)
        if m:
            return m.group(1).strip()

    ad_meta = soup.find("meta", attrs={"name": "adtags"})
    if ad_meta:
        m = re.search(r"publisher=([^&]+)", ad_meta.get("content", ""))
        if m:
            return m.group(1).replace("-", " ").title()
    return ""


def parse_release_date(soup: BeautifulSoup) -> Tuple[int, int, int]:
    page_text = " ".join(soup.get_text(" ", strip=True).split())
    m_store = re.search(r"In Store Date\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", page_text, re.I)
    if m_store:
        return parse_date(m_store.group(1))

    m_cover = re.search(r"Cover Date\s+([A-Za-z]+\s+(?:\d{1,2},?\s+)?\d{4})", page_text, re.I)
    if m_cover:
        return parse_date(m_cover.group(1))

    desc_elem = soup.find(class_="wiki-descriptor")
    if desc_elem:
        m_rel = re.search(r"released by\s+.*?\s+on\s+([A-Za-z]+\s+(?:\d{1,2},?\s+)?\d{4})", desc_elem.get_text(" ", strip=True), re.I)
        if m_rel:
            return parse_date(m_rel.group(1))

    return 0, 0, 0


def parse_summary(soup: BeautifulSoup) -> str:
    summary_elem = soup.find(class_="js-toc-content") or soup.find(class_="content-body")
    if summary_elem:
        txt = " ".join(summary_elem.get_text(" ", strip=True).split())
        return re.sub(r"^Part \d+ last edited by [^\s]+ on [^\s]+ [^\s]+ View full history", "", txt).strip()

    desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if desc:
        return desc.get("content", "").strip()

    return ""


def parse_creators(soup: BeautifulSoup) -> Dict[str, List[str]]:
    creators = {
        "writers": [], "pencillers": [], "inkers": [],
        "colorists": [], "letterers": [], "cover_artists": []
    }
    for block in soup.find_all(class_="wiki-details-object"):
        if "Creators" in block.get_text(" ", strip=True):
            for a in block.find_all("a"):
                name = a.get_text(strip=True)
                if not name or len(name) < 2:
                    continue
                parent_txt = a.parent.get_text(" ", strip=True).lower() if a.parent else ""
                if "writer" in parent_txt and name not in creators["writers"]:
                    creators["writers"].append(name)
                elif ("penciler" in parent_txt or "penciller" in parent_txt or "artist" in parent_txt) and name not in creators["pencillers"]:
                    creators["pencillers"].append(name)
                elif "inker" in parent_txt and name not in creators["inkers"]:
                    creators["inkers"].append(name)
                elif "colorist" in parent_txt and name not in creators["colorists"]:
                    creators["colorists"].append(name)
                elif "letterer" in parent_txt and name not in creators["letterers"]:
                    creators["letterers"].append(name)
                elif "cover" in parent_txt and name not in creators["cover_artists"]:
                    creators["cover_artists"].append(name)
    return creators


def parse_characters(soup: BeautifulSoup) -> List[str]:
    characters = []
    for block in soup.find_all(class_="wiki-details-object"):
        if "Characters" in block.get_text(" ", strip=True):
            for a in block.find_all("a"):
                name = a.get_text(strip=True)
                if name and name.lower() not in ("none", "add", "this issue") and len(name) > 1 and name not in characters:
                    characters.append(name)
    return characters


def parse_teams(soup: BeautifulSoup) -> List[str]:
    teams = []
    for block in soup.find_all(class_="wiki-details-object"):
        if "Teams" in block.get_text(" ", strip=True):
            for a in block.find_all("a"):
                name = a.get_text(strip=True)
                if name and name.lower() not in ("none", "add", "this issue") and len(name) > 1 and name not in teams:
                    teams.append(name)
    return teams


def parse_story_arcs(soup: BeautifulSoup) -> List[str]:
    arcs = []
    for block in soup.find_all(class_="wiki-details-object"):
        txt = block.get_text(" ", strip=True)
        if "Story Arcs" in txt or "Story Arc" in txt:
            for a in block.find_all("a"):
                name = a.get_text(strip=True).strip('"\'')
                if name and name.lower() not in ("none", "add", "this issue") and len(name) > 1 and name not in arcs:
                    arcs.append(name)
    return arcs


def parse_html(html_text: str, url: str = "") -> Comic:
    """Parses Comic Vine issue HTML content into a Comic object."""
    soup = BeautifulSoup(html_text, "html.parser")
    for edit in soup.find_all(class_="wiki-item-edit"):
        edit.decompose()

    c = Comic()
    c.provider_name = "CV"
    c.web = url
    c.series = parse_series(soup)
    c.number = parse_issue_number(soup)
    c.title = parse_title(soup, series=c.series, number=c.number)
    c.publisher = parse_publisher(soup)

    y, m, d = parse_release_date(soup)
    if y:
        c.year, c.month, c.day = y, m, d

    c.summary = parse_summary(soup)
    creators = parse_creators(soup)
    c.writers = creators["writers"]
    c.pencillers = creators["pencillers"]
    c.inkers = creators["inkers"]
    c.colorists = creators["colorists"]
    c.letterers = creators["letterers"]
    c.cover_artists = creators["cover_artists"]

    c.characters = parse_characters(soup)
    c.teams = parse_teams(soup)
    c.story_arcs = parse_story_arcs(soup)

    return c
