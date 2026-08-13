import re
from bs4 import BeautifulSoup
from models.comic import Comic

MONTH_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10,
    "november": 11, "nov": 11, "december": 12, "dec": 12
}

def clean_creator_name(val: str) -> str:
    """Cleans up creator name strings by removing notes, parentheses, and trailing characters."""
    c = re.sub(r"\s*\([^)]*\)", "", val)
    c = re.sub(r"\s*\([^)]*", "", c)
    c = c.strip().strip("?").strip()
    return c

def parse_gcd_soup(soup: BeautifulSoup, url: str = "") -> Comic:
    """Parses BeautifulSoup object from GCD HTML page into a Comic model."""
    c = Comic()
    c.provider_name = "GCP"
    c.web = url

    h1 = soup.find("h1")
    if h1:
        c.series = h1.get_text(" ", strip=True)
        c.title = c.series

    title_tag = soup.find("title")
    if title_tag:
        t_text = title_tag.get_text(" ", strip=True)
        m = re.search(r"GCD\s*::\s*Issue\s*::\s*(.+?)(?:\s*#\s*(.*))?$", t_text, re.I)
        if m:
            c.series = m.group(1).strip()
            c.number = m.group(2).strip() if m.group(2) else ""
            c.title = f"{c.series} #{c.number}" if c.number else c.series

    page_txt = soup.get_text(" ", strip=True)
    m_pub = re.search(r"([A-Za-z0-9\s]+),\s*(\d{4})\s+Series", page_txt)
    if m_pub:
        pub_raw = m_pub.group(1).strip()
        pub_parts = pub_raw.split()
        c.publisher = pub_parts[-1] if pub_parts else pub_raw
        c.year = int(m_pub.group(2))

    return c

def parse_gcp_text_refined(text: str, default_url: str = "") -> Comic:
    """Parses Grand Comics Database HTML or copied page text layout into a Comic object."""
    if "<html" in text.lower() or "<body" in text.lower() or "<title>" in text.lower():
        soup = BeautifulSoup(text, "html.parser")
        c_soup = parse_gcd_soup(soup, default_url)
        if c_soup.series and c_soup.series != "Grand Comics Database Issue":
            return c_soup

    c = Comic()
    c.provider_name = "GCP"
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    web_url = default_url
    clean_lines = []
    for l in lines:
        if l.startswith("http://") or l.startswith("https://"):
            if not web_url: web_url = l
        else:
            clean_lines.append(l)

    c.web = web_url

    if clean_lines:
        c.title = clean_lines[0]
        m_issue = re.search(r"(.+?)\s+#?(\d+[a-zA-Z]?|\d+\.\d+|\d+|\[[^\]]+\])", c.title)
        if m_issue:
            c.series = m_issue.group(1).strip()
            c.number = m_issue.group(2).strip().lstrip("#")
        else:
            c.series = c.title

    page_txt = "\n".join(clean_lines)

    m_pub = re.search(r"([A-Za-z0-9\s]+),\s+(\d{4})\s+Series", page_txt)
    if m_pub:
        raw_pub = m_pub.group(1).strip().split("\n")[-1].strip()
        c.publisher = raw_pub
        c.year = int(m_pub.group(2))

    m_date = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December|Summer|Winter|Spring|Fall)\s+(\d{4})\b", page_txt, re.I)
    if m_date:
        if not c.year: c.year = int(m_date.group(2))
        m_name = m_date.group(1).lower()
        if m_name in MONTH_MAP: c.month = MONTH_MAP[m_name]

    for line in clean_lines:
        if line.startswith("Script:") or line.startswith("Writer:"):
            for val in re.split(r"[,;]+", line.split(":", 1)[1]):
                clean = clean_creator_name(val)
                if clean and clean.lower() not in ("none", "") and clean not in c.writers:
                    c.writers.append(clean)

        elif line.startswith("Pencils:") or line.startswith("Penciller:"):
            for val in re.split(r"[,;]+", line.split(":", 1)[1]):
                clean = clean_creator_name(val)
                if clean and clean.lower() not in ("none", "") and clean not in c.pencillers:
                    c.pencillers.append(clean)

        elif line.startswith("Inks:") or line.startswith("Inker:"):
            for val in re.split(r"[,;]+", line.split(":", 1)[1]):
                clean = clean_creator_name(val)
                if clean and clean.lower() not in ("none", "") and clean not in c.inkers:
                    c.inkers.append(clean)

        elif line.startswith("Colors:") or line.startswith("Colorist:"):
            for val in re.split(r"[,;]+", line.split(":", 1)[1]):
                clean = clean_creator_name(val)
                if clean and clean.lower() not in ("none", "") and clean not in c.colorists:
                    c.colorists.append(clean)

        elif line.startswith("Letters:") or line.startswith("Letterer:"):
            for val in re.split(r"[,;]+", line.split(":", 1)[1]):
                clean = clean_creator_name(val)
                if clean and clean.lower() not in ("none", "") and clean not in c.letterers:
                    c.letterers.append(clean)

        elif line.startswith("Genre:"):
            c.genre = line.split(":", 1)[1].strip()

        elif line.startswith("Characters:"):
            for char in re.split(r"[;;\n]+", line.split(":", 1)[1]):
                clean = clean_creator_name(char)
                if clean and clean.lower() not in ("none", "") and len(clean) > 1 and clean not in c.characters:
                    c.characters.append(clean)

    if not c.title and c.series:
        c.title = f"{c.series} #{c.number}" if c.number else c.series

    return c
