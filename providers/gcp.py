import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
from models.comic import Comic

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

def fetch_gcp_html(url: str) -> str:
    """Helper to fetch HTML content from comics.org URL."""
    html_content = ""
    if HAS_CURL_CFFI:
        try:
            r = cffi_requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=30)
            if r.status_code == 200:
                html_content = r.text
        except Exception:
            pass

    if not html_content:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                html_content = r.text
        except Exception:
            pass

    return html_content

def fetch_gcp_api_json(url: str) -> dict:
    """Helper to fetch JSON content from comics.org REST API endpoint."""
    clean_url = url if "?format=json" in url else f"{url.rstrip('/')}/?format=json"
    headers = dict(HEADERS)
    headers["Accept"] = "application/json"
    
    if HAS_CURL_CFFI:
        try:
            r = cffi_requests.get(clean_url, headers=headers, impersonate="chrome", timeout=30)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass

    try:
        r = requests.get(clean_url, headers=headers, timeout=30)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass

    return {}

def scrape_gcp_issue(url: str) -> Comic:
    """Scrapes a Grand Comics Database (comics.org / GCP) issue page into a Comic object."""
    c = Comic()
    c.web = url
    
    m_issue = re.search(r"/issue/(\d+)", url)
    if not m_issue:
        raise ValueError(f"Invalid GCP Issue URL: '{url}'")

    issue_id = m_issue.group(1)
    
    # 1. Try API first
    api_data = fetch_gcp_api_json(f"https://www.comics.org/api/issue/{issue_id}/")
    if api_data and api_data.get("id"):
        c.number = str(api_data.get("number", "")).strip().lstrip("#")
        c.title = api_data.get("title", "") or ""

        # Publication date parsing
        pub_date = str(api_data.get("publication_date", "")).strip()
        m_year = re.search(r"\b(19\d\d|20\d\d)\b", pub_date)
        if m_year:
            c.year = int(m_year.group(1))

        c.summary = api_data.get("notes", "") or ""

        # Fetch Series
        series_api = api_data.get("series")
        if series_api:
            s_data = fetch_gcp_api_json(series_api)
            if s_data:
                c.series = s_data.get("name", "")
                pub_api = s_data.get("publisher")
                if pub_api:
                    p_data = fetch_gcp_api_json(pub_api)
                    if p_data:
                        c.publisher = p_data.get("name", "")

        # Extract Credits & Characters from story_set
        for story in api_data.get("story_set", []):
            writer = story.get("writer")
            if writer:
                for w in re.split(r"[,;]+", writer):
                    w_name = w.strip()
                    if w_name and w_name not in c.writers:
                        c.writers.append(w_name)

            penciler = story.get("penciler")
            if penciler:
                for p in re.split(r"[,;]+", penciler):
                    p_name = p.strip()
                    if p_name and p_name not in c.pencillers:
                        c.pencillers.append(p_name)

            inker = story.get("inker")
            if inker:
                for i in re.split(r"[,;]+", inker):
                    i_name = i.strip()
                    if i_name and i_name not in c.inkers:
                        c.inkers.append(i_name)

            colorist = story.get("colorist")
            if colorist:
                for col in re.split(r"[,;]+", colorist):
                    col_name = col.strip()
                    if col_name and col_name not in c.colorists:
                        c.colorists.append(col_name)

            chars = story.get("characters")
            if chars:
                for ch in re.split(r"[;]+", chars):
                    ch_name = ch.strip()
                    if ch_name and ch_name not in c.characters:
                        c.characters.append(ch_name)

        if not c.title and c.series:
            c.title = f"{c.series} #{c.number}" if c.number else c.series

        return c

    # 2. HTML Scraper Fallback
    html_text = fetch_gcp_html(url)
    if not html_text:
        raise RuntimeError(f"Could not fetch GCP issue page: {url}")

    soup = BeautifulSoup(html_text, "html.parser")
    h1 = soup.find("h1")
    if h1:
        h1_txt = h1.get_text(" ", strip=True)
        c.title = h1_txt
        m = re.search(r"(.+?)\s+#?(\d+[a-zA-Z]?|\d+\.\d+|\d+)", h1_txt)
        if m:
            c.series = m.group(1).strip()
            c.number = m.group(2).strip()

    return c

def scrape_gcp_volume(volume_url: str) -> tuple[str, dict[str, str], list[dict]]:
    """
    Scrapes a GCP Series/Volume page (https://www.comics.org/series/XXXXX/).
    Returns (series_name, issue_map, issues_list).
    """
    m_series = re.search(r"/series/(\d+)", volume_url)
    if not m_series:
        raise ValueError(f"Invalid GCP Series URL: '{volume_url}'")

    series_id = m_series.group(1)

    # 1. API Fetching
    s_data = fetch_gcp_api_json(f"https://www.comics.org/api/series/{series_id}/")
    if s_data and s_data.get("name"):
        series_name = s_data.get("name", "")
        issue_map = {}
        issues_list = []

        active_issues = s_data.get("active_issues", [])
        for iss_api_url in active_issues:
            m_iss = re.search(r"/issue/(\d+)", iss_api_url)
            if m_iss:
                iss_id = m_iss.group(1)
                web_url = f"https://www.comics.org/issue/{iss_id}/"
                i_data = fetch_gcp_api_json(iss_api_url)
                num = str(i_data.get("number", "")).strip().lstrip("#").lstrip("0") or "0"

                if num not in issue_map:
                    issue_map[num] = web_url
                    issues_list.append({
                        "number": num,
                        "label": f"Issue #{num}",
                        "url": web_url
                    })

        issues_list = sorted(
            issues_list,
            key=lambda x: int(re.sub(r"\D", "", x["number"])) if re.sub(r"\D", "", x["number"]) else 0
        )
        return series_name, issue_map, issues_list

    # 2. HTML Scraper Fallback
    html_text = fetch_gcp_html(volume_url)
    soup = BeautifulSoup(html_text, "html.parser")

    series_name = ""
    h1 = soup.find("h1")
    if h1:
        series_name = h1.get_text(" ", strip=True)

    issue_map = {}
    issues_list = []

    for a in soup.find_all("a", href=re.compile(r"/issue/\d+/")):
        href = a["href"]
        full_url = href if href.startswith("http") else "https://www.comics.org" + href
        txt = a.get_text(strip=True)
        m = re.search(r"#?(\d+[a-zA-Z]?|\d+\.\d+|\d+)", txt)
        if m:
            num = m.group(1).lstrip("0") or "0"
            if num not in issue_map:
                issue_map[num] = full_url
                issues_list.append({
                    "number": num,
                    "label": f"Issue #{num}",
                    "url": full_url
                })

    return series_name, issue_map, issues_list

def search_gcp(query: str, search_type: str = "all") -> list[dict]:
    """
    Searches Grand Comics Database (GCP / comics.org) for series or issues.
    Returns list of search result dicts.
    """
    results = []
    clean_query = query.strip()
    if not clean_query:
        return results

    encoded_query = urllib.parse.quote_plus(clean_query)
    
    # 1. Search Series
    if search_type in ("all", "gcp_volume"):
        search_url = f"https://www.comics.org/search/advanced/process/?target=series&method=contains&series_name={encoded_query}"
        html_text = fetch_gcp_html(search_url)
        if html_text:
            soup = BeautifulSoup(html_text, "html.parser")
            for tr in soup.find_all("tr"):
                a = tr.find("a", href=re.compile(r"/series/\d+/"))
                if not a:
                    continue
                href = a["href"]
                full_url = href if href.startswith("http") else "https://www.comics.org" + href
                s_name = a.get_text(" ", strip=True)
                txt = " ".join(tr.get_text(" ", strip=True).split())

                m_year = re.search(r"\b(19\d\d|20\d\d)\b", txt)
                year_str = m_year.group(1) if m_year else ""

                m_issues = re.search(r"(\d+)\s+issues", txt, re.I)
                count_str = f"{m_issues.group(1)} issues" if m_issues else ""

                if s_name and full_url and not any(r["url"] == full_url for r in results):
                    results.append({
                        "title": s_name,
                        "url": full_url,
                        "image": "",
                        "type": "gcp_volume",
                        "type_label": "GCP Series",
                        "provider": "GCP",
                        "year": year_str,
                        "count": count_str,
                        "description": txt[:160]
                    })

    # 2. Search Issues
    if search_type in ("all", "gcp_issue"):
        search_url = f"https://www.comics.org/search/advanced/process/?target=issue&method=contains&issue_name={encoded_query}"
        html_text = fetch_gcp_html(search_url)
        if html_text:
            soup = BeautifulSoup(html_text, "html.parser")
            for tr in soup.find_all("tr"):
                a = tr.find("a", href=re.compile(r"/issue/\d+/"))
                if not a:
                    continue
                href = a["href"]
                full_url = href if href.startswith("http") else "https://www.comics.org" + href
                i_name = a.get_text(" ", strip=True)
                txt = " ".join(tr.get_text(" ", strip=True).split())

                m_year = re.search(r"\b(19\d\d|20\d\d)\b", txt)
                year_str = m_year.group(1) if m_year else ""

                if i_name and full_url and not any(r["url"] == full_url for r in results):
                    results.append({
                        "title": i_name,
                        "url": full_url,
                        "image": "",
                        "type": "gcp_issue",
                        "type_label": "GCP Issue",
                        "provider": "GCP",
                        "year": year_str,
                        "count": "1 issue",
                        "description": txt[:160]
                    })

    return results
