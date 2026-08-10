import re
import urllib.parse
import requests
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from models.comic import Comic
from providers.base import BaseProvider

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1"
}

MONTH_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10,
    "november": 11, "nov": 11, "december": 12, "dec": 12
}

def parse_date(date_str: str):
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

def parse_html(html_text: str, url: str = "") -> Comic:
    """Parses Comic Vine issue HTML content into a Comic object."""
    soup = BeautifulSoup(html_text, "html.parser")
    
    for edit in soup.find_all(class_="wiki-item-edit"):
        edit.decompose()

    c = Comic()
    c.provider_name = "CV"
    c.web = url
    
    # 1. Series Name & Issue Number from H1 links
    h1 = soup.find("h1")
    if h1:
        s_link = h1.find("a", class_="wiki-title")
        if s_link:
            c.series = s_link.get_text(strip=True)
        i_link = h1.find("a", class_="wiki-issue-number")
        if i_link:
            c.number = i_link.get_text(strip=True).lstrip("#").strip()

    # Fallback Series/Number regex from H1 text
    if not c.series or not c.number:
        if h1:
            h1_txt = " ".join(h1.get_text(" ", strip=True).split())
            m = re.match(r"(.+?)\s+#?(\d+[a-zA-Z]?|\d+\.\d+|\d+)", h1_txt)
            if m:
                if not c.series: c.series = m.group(1).strip()
                if not c.number: c.number = m.group(2).strip()

    # 2. Issue Name / Title
    page_text = " ".join(soup.get_text(" ", strip=True).split())

    m_name = re.search(r"Issue details\s+Name\s+(.+?)\s+Name\s+Name of this issue", page_text)
    if m_name:
        val = m_name.group(1).strip()
        if val and val.lower() not in ("none", "name"):
            c.title = val

    if not c.title:
        og_title = soup.find("meta", attrs={"property": "og:title"}) or soup.find("meta", attrs={"name": "twitter:title"})
        if og_title:
            og_txt = og_title.get("content", "")
            m = re.search(r"#\d+[a-zA-Z]?\s*[:-]\s*(.+?)(?:\s*\(Issue\)|$)", og_txt)
            if m:
                c.title = m.group(1).strip()

    if not c.title and h1:
        h1_txt = " ".join(h1.get_text(" ", strip=True).split())
        m = re.search(r"#\d+[a-zA-Z]?\s*[:-]\s*(.+)", h1_txt)
        if m:
            c.title = m.group(1).strip()

    if not c.title and c.series:
        c.title = f"{c.series} #{c.number}" if c.number else c.series

    # 3. Publisher
    desc_elem = soup.find(class_="wiki-descriptor")
    if desc_elem:
        txt = desc_elem.get_text(" ", strip=True)
        m = re.search(r"released by\s+(.+?)(?:\s+on|\.|$)", txt, re.I)
        if m:
            c.publisher = m.group(1).strip()

    if not c.publisher:
        ad_meta = soup.find("meta", attrs={"name": "adtags"})
        if ad_meta:
            m = re.search(r"publisher=([^&]+)", ad_meta.get("content", ""))
            if m:
                c.publisher = m.group(1).replace("-", " ").title()

    # 4. Release / Cover Date
    y, m, d = 0, 0, 0
    m_store = re.search(r"In Store Date\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", page_text, re.I)
    if m_store:
        y, m, d = parse_date(m_store.group(1))

    if not y:
        m_cover = re.search(r"Cover Date\s+([A-Za-z]+\s+(?:\d{1,2},?\s+)?\d{4})", page_text, re.I)
        if m_cover:
            y, m, d = parse_date(m_cover.group(1))

    if y:
        c.year, c.month, c.day = y, m, d

    # 5. Volume (Leave empty by default to avoid writing wrong/dummy <Volume> tags to ComicInfo.xml)
    c.volume = ""


    # 6. Summary / Description
    summary_elem = soup.find(class_="js-toc-content") or soup.find(class_="content-body")
    if summary_elem:
        txt = " ".join(summary_elem.get_text(" ", strip=True).split())
        txt = re.sub(r"^Part \d+ last edited by [^\s]+ on [^\s]+ [^\s]+ View full history", "", txt).strip()
        c.summary = txt
    else:
        desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        if desc:
            c.summary = desc.get("content", "").strip()

    # 7. Creator Credits, Characters, Teams, Story Arcs
    for block in soup.find_all(class_="wiki-details-object"):
        header_txt = block.get_text(" ", strip=True)

        if "Creators" in header_txt:
            for a in block.find_all("a"):
                name = a.get_text(strip=True)
                if not name or len(name) < 2:
                    continue
                parent_txt = a.parent.get_text(" ", strip=True).lower() if a.parent else ""
                if "writer" in parent_txt and name not in c.writers:
                    c.writers.append(name)
                elif ("penciler" in parent_txt or "penciller" in parent_txt or "artist" in parent_txt) and name not in c.pencillers:
                    c.pencillers.append(name)
                elif "inker" in parent_txt and name not in c.inkers:
                    c.inkers.append(name)
                elif "colorist" in parent_txt and name not in c.colorists:
                    c.colorists.append(name)
                elif "letterer" in parent_txt and name not in c.letterers:
                    c.letterers.append(name)
                elif "cover" in parent_txt and name not in c.cover_artists:
                    c.cover_artists.append(name)

        elif "Characters" in header_txt:
            for a in block.find_all("a"):
                name = a.get_text(strip=True)
                if name and name.lower() not in ("none", "add", "this issue") and len(name) > 1 and name not in c.characters:
                    c.characters.append(name)

        elif "Teams" in header_txt:
            for a in block.find_all("a"):
                name = a.get_text(strip=True)
                if name and name.lower() not in ("none", "add", "this issue") and len(name) > 1 and name not in c.teams:
                    c.teams.append(name)

        elif "Story Arcs" in header_txt or "Story Arc" in header_txt:
            for a in block.find_all("a"):
                name = a.get_text(strip=True).strip('"\'')
                if name and name.lower() not in ("none", "add", "this issue") and len(name) > 1 and name not in c.story_arcs:
                    c.story_arcs.append(name)

    return c

def fetch_html(url: str) -> str:
    """Helper to fetch HTML from URL using curl_cffi, cloudscraper, or requests."""
    html_content = ""

    if HAS_CURL_CFFI:
        try:
            r = cffi_requests.get(url, impersonate="chrome", timeout=30)
            if r.status_code == 200 and "Just a moment..." not in r.text:
                html_content = r.text
        except Exception:
            pass

    if not html_content and HAS_CLOUDSCRAPER:
        try:
            scraper = cloudscraper.create_scraper()
            r = scraper.get(url, timeout=30)
            if r.status_code == 200 and "Just a moment..." not in r.text:
                html_content = r.text
        except Exception:
            pass

    if not html_content:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        html_content = r.text

    if "Just a moment..." in html_content and "<title>Just a moment..." in html_content:
        raise RuntimeError("Comic Vine returned a Cloudflare verification challenge.")

    return html_content

def scrape_issue(url: str) -> Comic:
    """Fetches HTML from URL and parses Comic metadata."""
    html_content = fetch_html(url)
    return parse_html(html_content, url)

def _volume_slug_from_url(volume_url: str) -> str:
    """Extracts the series name slug from a ComicVine volume URL.
    e.g. 'https://comicvine.gamespot.com/the-darkness/4050-5868/' -> 'the-darkness'
    If URL is in Kapowarr format ('/volume/4050-5868/'), returns empty string to allow fallback."""
    m = re.search(r"comicvine\.gamespot\.com/([^/]+)/4050-", volume_url)
    if not m:
        return ""
    slug = m.group(1).lower().strip()
    if slug == "volume":
        return ""
    return slug

def _slug_matches_series(issue_url: str, series_slug: str) -> bool:
    """Returns True if the issue URL slug is consistent with the parent series slug.
    Rejects collected editions, TPBs, hardcovers, and crossovers from other series."""
    if not series_slug:
        return True

    m = re.search(r"comicvine\.gamespot\.com/([^/]+)/4000-", issue_url)
    if not m:
        return True
    issue_slug = m.group(1).lower()

    # Reject URLs containing collected edition / TPB / volume indicators anywhere in slug
    COLLECTED_KEYWORDS = (
        "-tpb", "-hc", "-gn", "-graphic-novel", "-trade-paperback",
        "-hardcover", "-softcover", "-collection", "-collected",
        "-omnibus", "-compendium", "-deluxe", "-edition", "-masterworks",
        "-box-set", "-slipcase", "-treasury", "-digest", "-epic-collection",
        "-ultimate-collection", "-must-haves", "-volume-", "-vol-"
    )
    if any(kw in issue_slug for kw in COLLECTED_KEYWORDS):
        return False

    def strip_articles(slug: str) -> str:
        for prefix in ("the-", "a-", "an-"):
            if slug.startswith(prefix):
                slug = slug[len(prefix):]
        return slug

    norm_series = strip_articles(series_slug)   # e.g. "ultimate-spider-man"
    norm_issue  = strip_articles(issue_slug)     # e.g. "ultimate-spider-man-1-..." or "ultimate-spider-man-ultimate-collection-1-..."

    if not norm_issue.startswith(norm_series):
        return False

    suffix = norm_issue[len(norm_series):]  # e.g. "-1-power-and-responsibility" or "-ultimate-collection-1"

    if not suffix:
        return True

    if not suffix.startswith("-"):
        return False

    after_dash = suffix[1:]  # e.g. "1-power-and-responsibility" or "ultimate-collection-1"

    if not after_dash:
        return True

    if after_dash[0].isdigit():
        return True

    ALLOWED_SPECIAL_PREFIXES = {
        "annual", "special", "super", "giant", "fcbd", "free", "ashcan", "preview", "oneshot", "one", "zero", "issue", "crossover", "tie-in", "vs"
    }
    first_word = after_dash.split("-")[0]
    if first_word in ALLOWED_SPECIAL_PREFIXES:
        return True

    return False


def scrape_volume(volume_url: str, max_pages_limit: int = 50) -> tuple[str, dict[str, str], list[dict]]:
    """Scrapes a Comic Vine Volume/Series page (/4050-XXXXX/).
    Uses slug-based filtering to avoid collected editions from other series stealing issue numbers."""
    clean_url = re.sub(r"\?page=\d+.*$", "", volume_url).rstrip("/") + "/"
    html_content = fetch_html(clean_url)
    soup = BeautifulSoup(html_content, "html.parser")

    series_name = ""
    h1 = soup.find("h1")
    if h1:
        series_name = h1.get_text(" ", strip=True).split("»")[0].strip()

    # Derive volume slug for filtering
    series_slug = _volume_slug_from_url(volume_url)
    if not series_slug and series_name:
        clean_name = re.sub(r"[^a-zA-Z0-9\s-]", "", series_name).lower().strip()
        series_slug = re.sub(r"[\s_]+", "-", clean_name)

    max_page = 1

    for a in soup.find_all("a", href=re.compile(r"page=\d+")):
        m = re.search(r"page=(\d+)", a["href"])
        if m:
            pnum = int(m.group(1))
            if pnum > max_page:
                max_page = pnum

    matched_map = {}     # num_str -> url  (correct series single issues)
    matched_list = []

    def extract_issues_from_soup(s):
        for a in s.find_all("a", href=re.compile(r"/4000-\d+")):
            href = a["href"]
            full_url = href if href.startswith("http") else "https://comicvine.gamespot.com" + href

            parent = a.find_parent(["li", "div", "tr", "td"]) or a
            txt = parent.get_text(" ", strip=True)

            m = re.search(r"#(?:Issue\s*)?(\d+½|\d+/\d+|\d+\.\d+|\d+[a-zA-Z]?|½|1/2|0\.5)", txt, re.I)
            if not m:
                m = re.search(r"Issue\s*#?\s*(\d+½|\d+/\d+|\d+\.\d+|\d+[a-zA-Z]?|½|1/2|0\.5)", txt, re.I)
            if not m:
                m = re.search(r"#(0+|\d+½|\d+/\d+|\d+\.\d+|\d+|½)", a.get_text(strip=True))

            if m:
                raw_num = m.group(1).strip()
                if raw_num in ("½", "1/2", "0½", "0.5"):
                    num_str = "0.5"
                    label_str = "Issue #1/2"
                elif raw_num in ("0", "00", "000"):
                    num_str = "0"
                    label_str = f"Issue #{raw_num}"
                else:
                    num_str = raw_num.lstrip("0") or "0"
                    label_str = f"Issue #{num_str}"

                is_match = _slug_matches_series(full_url, series_slug)
                if is_match:
                    if num_str not in matched_map:
                        matched_map[num_str] = full_url
                        matched_list.append({"number": num_str, "label": label_str, "url": full_url})

    extract_issues_from_soup(soup)

    pages_to_fetch = min(max_page, max_pages_limit)
    for page_idx in range(2, pages_to_fetch + 1):
        p_url = f"{clean_url}?page={page_idx}"
        try:
            p_html = fetch_html(p_url)
            p_soup = BeautifulSoup(p_html, "html.parser")
            extract_issues_from_soup(p_soup)
        except Exception:
            pass

    # Strictly use matched single issues for volume map and list
    issue_map = dict(matched_map)
    issues_list = sorted(
        matched_list,
        key=lambda x: int(re.sub(r"\D", "", x["number"])) if re.sub(r"\D", "", x["number"]) else 0
    )

    return series_name, issue_map, issues_list


def search_comicvine(query: str, search_type: str = "all") -> list[dict]:
    """Searches Comic Vine for series volumes or single issues."""
    clean_query = query.strip()
    if not clean_query:
        return []

    encoded_query = urllib.parse.quote_plus(clean_query)
    search_url = f"https://comicvine.gamespot.com/search/?q={encoded_query}"
    if search_type == "volume":
        search_url += "&indices%5B0%5D=volume"
    elif search_type == "issue":
        search_url += "&indices%5B0%5D=issue"

    html_content = fetch_html(search_url)
    soup = BeautifulSoup(html_content, "html.parser")

    results = []
    for li in soup.find_all(["li", "div"], class_=re.compile(r"search-result|media|wiki-block", re.I)):
        a = li.find("a", href=re.compile(r"/(?:4000|4050)-\d+"))
        if not a:
            continue

        href = a["href"]
        full_url = href if href.startswith("http") else "https://comicvine.gamespot.com" + href
        raw_title = a.get_text(" ", strip=True)

        img = li.find("img")
        img_src = img.get("src", "") if img else ""

        text_block = li.get_text(" ", strip=True)
        is_volume = "/4050-" in full_url

        m_year = re.search(r"\b(19\d\d|20\d\d)\b", text_block)
        year_str = m_year.group(1) if m_year else ""

        m_count = re.search(r"\((\d+)\s+issues\)", text_block, re.I)
        count_str = f"{m_count.group(1)} issues" if m_count else ""

        clean_title = re.sub(r"\s+", " ", raw_title).strip()

        if clean_title and full_url and not any(r["url"] == full_url for r in results):
            results.append({
                "title": clean_title,
                "url": full_url,
                "image": img_src,
                "type": "volume" if is_volume else "issue",
                "type_label": "Volume / Series" if is_volume else "Single Issue",
                "year": year_str,
                "count": count_str,
                "description": text_block[:160]
            })

    return results

class ComicVineProvider(BaseProvider):
    """ComicVine Provider implementing BaseProvider interface."""
    
    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def get_name(self) -> str:
        return "CV"

    def search_series(self, query: str) -> list[dict]:
        return search_comicvine(query, search_type="volume")

    def search_issue(self, query: str) -> list[dict]:
        return search_comicvine(query, search_type="issue")

    def lookup_volume(self, volume_id: str) -> tuple[str, dict[str, str], list[dict]]:
        url = volume_id if volume_id.startswith("http") else f"https://comicvine.gamespot.com/volume/4050-{volume_id}/"
        return scrape_volume(url)

    def lookup_issue(self, issue_id_or_url: str) -> Optional[Comic]:
        url = issue_id_or_url if issue_id_or_url.startswith("http") else f"https://comicvine.gamespot.com/issue/4000-{issue_id_or_url}/"
        try:
            return scrape_issue(url)
        except Exception:
            return None
