import os
import re
import urllib.parse
import zipfile
import requests
from bs4 import BeautifulSoup

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

def search_story_arcs(query: str, api_key: str = "") -> list[dict]:
    """Searches ComicVine for Story Arcs via API or Web Scraper."""
    results = []
    if not query.strip():
        return results

    clean_q = query.strip()

    # 1. API Search if API key exists
    if api_key:
        try:
            url = f"https://comicvine.gamespot.com/api/story_arcs/?api_key={api_key}&format=json&filter=name:{urllib.parse.quote(clean_q)}&limit=15"
            r = requests.get(url, headers={"User-Agent": "ComicInfoGenerator/2.0"}, timeout=6)
            if r.status_code == 200:
                data = r.json()
                for arc in data.get("results", []):
                    img = arc.get("image", {})
                    img_url = img.get("small_url") or img.get("medium_url") if isinstance(img, dict) else ""
                    results.append({
                        "id": str(arc.get("id", "")),
                        "name": arc.get("name", ""),
                        "deck": arc.get("deck") or arc.get("description", "") or "",
                        "publisher": arc.get("publisher", {}).get("name", "") if isinstance(arc.get("publisher"), dict) else "",
                        "url": arc.get("site_detail_url", ""),
                        "issue_count": arc.get("count_of_issue_appearances", 0),
                        "image": img_url
                    })
                if results:
                    return results
        except Exception:
            pass

    # 2. Web Scraper Search Fallback
    try:
        search_url = f"https://comicvine.gamespot.com/search/?q={urllib.parse.quote(clean_q)}"
        scraper = cloudscraper.create_scraper() if HAS_CLOUDSCRAPER else requests
        r = scraper.get(search_url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            seen = set()
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/4045-" in href:
                    if href not in seen:
                        seen.add(href)
                        full_url = f"https://comicvine.gamespot.com{href}" if href.startswith("/") else href
                        title = " ".join(a.get_text(" ", strip=True).split())
                        arc_id = re.search(r"4045-(\d+)", href).group(1) if re.search(r"4045-(\d+)", href) else ""
                        if title and len(title) > 2:
                            results.append({
                                "id": arc_id,
                                "name": title,
                                "deck": f"ComicVine Story Arc #{arc_id}",
                                "publisher": "",
                                "url": full_url,
                                "issue_count": 0,
                                "image": ""
                            })
    except Exception:
        pass

    return results

def get_story_arc_details(arc_url: str, watch_folder: str = "") -> dict:
    """Parses a Story Arc reading order and cross-references against local disk & Kapowarr."""
    if not arc_url.strip():
        return {"error": "Story Arc URL is required."}

    url_str = arc_url.strip()

    try:
        scraper = cloudscraper.create_scraper() if HAS_CLOUDSCRAPER else requests
        r = scraper.get(url_str, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return {"error": f"Failed to fetch story arc page: HTTP {r.status_code}"}

        soup = BeautifulSoup(r.text, "html.parser")
        h1 = soup.find("h1")
        arc_title = h1.get_text(strip=True) if h1 else "Story Arc"

        deck = ""
        deck_elem = soup.find(class_="deck") or soup.find("p")
        if deck_elem:
            deck = deck_elem.get_text(strip=True)

        img_elem = soup.find("img", src=True)
        img_url = img_elem["src"] if img_elem else ""

        issues = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/4000-" in href:
                title = " ".join(a.get_text(" ", strip=True).split())
                if href not in seen and title and not title.lower().startswith(("edit", "cover", "view", "add")):
                    seen.add(href)
                    full_url = f"https://comicvine.gamespot.com{href}" if href.startswith("/") else href

                    m_num = re.search(r"#(\d+[a-zA-Z]?|\d+\.\d+)", title)
                    issue_num = m_num.group(1) if m_num else ""
                    m_ser = re.match(r"(.+?)\s+#", title)
                    series_name = m_ser.group(1).strip() if m_ser else title
                    cv_issue_id = re.search(r"4000-(\d+)", href).group(1) if re.search(r"4000-(\d+)", href) else ""

                    issues.append({
                        "title": title,
                        "series": series_name,
                        "number": issue_num,
                        "url": full_url,
                        "cv_issue_id": cv_issue_id,
                        "is_found": False,
                        "is_tagged": False,
                        "file_path": ""
                    })

        # Cross-reference with disk library
        if not watch_folder:
            watch_folder = "/mnt/disk1/Comics"

        if watch_folder and os.path.exists(watch_folder):
            for iss in issues:
                res = _check_disk_for_issue(watch_folder, iss["series"], iss["number"])
                if res["found"]:
                    iss["is_found"] = True
                    iss["is_tagged"] = res["tagged"]
                    iss["file_path"] = res["path"]

        found_count = sum(1 for i in issues if i["is_found"])
        tagged_count = sum(1 for i in issues if i["is_tagged"])
        missing_count = len(issues) - found_count

        return {
            "title": arc_title,
            "deck": deck,
            "url": url_str,
            "image": img_url,
            "total_issues": len(issues),
            "found_count": found_count,
            "tagged_count": tagged_count,
            "missing_count": missing_count,
            "issues": issues
        }
    except Exception as e:
        return {"error": f"Error loading story arc: {e}"}

def _check_disk_for_issue(watch_folder: str, series: str, number: str) -> dict:
    if not series or not number:
        return {"found": False, "path": "", "tagged": False}

    clean_ser = series.lower().replace("-", " ").replace(":", "")
    for root, dirs, files in os.walk(watch_folder):
        for f in files:
            if f.lower().endswith((".cbz", ".cbr")):
                clean_f = f.lower().replace("-", " ").replace(":", "")
                if clean_ser in clean_f or series.lower() in root.lower():
                    m = re.search(r"(?:#|\b0*|v\d+[-_\s]*)(?: shadow| )?(?:" + re.escape(number) + r")\b", f, re.IGNORECASE)
                    if m or f"#{number}" in f or f"issue {number}" in f.lower() or f" {number}.cbz" in f.lower():
                        full_p = os.path.join(root, f)
                        is_tagged = False
                        if f.lower().endswith(".cbz"):
                            try:
                                with zipfile.ZipFile(full_p, 'r') as zf:
                                    is_tagged = "comicinfo.xml" in [n.lower() for n in zf.namelist()]
                            except Exception:
                                pass
                        return {"found": True, "path": full_p, "tagged": is_tagged}
    return {"found": False, "path": "", "tagged": False}
