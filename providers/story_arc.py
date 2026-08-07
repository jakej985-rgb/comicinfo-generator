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

MARVEL_ZOMBIES_PRESET_TEXT = """Marvel Zombies: Dead Days #1
Marvel Zombies vs. Army of Darkness #1-5
Marvel Zombies: Evil Evolution #1
Marvel Apes #1-4
Ultimate Fantastic Four #21-23
Marvel Zombies #1-5
Ultimate Fantastic Four #30-32
Black Panther #28-30
Marvel Zombies 2 #1-5
Marvel Zombies Return #1-5
Marvel Zombies 3 #1-4
Marvel Zombies 4 #1-4
Deadpool: Merc with a Mouth #1-13
Marvel Zombies 5 #1-5
Marvel Zombies Supreme #1-5
Marvel Zombies Destroy #1-5"""

def parse_custom_chronological_reading_order(text: str, arc_name: str = "Chronological Story Arc Crossover", watch_folder: str = "") -> dict:
    """Expands multi-series range lists (e.g. Ultimate Fantastic Four #21-23) into issue entries and checks disk."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    expanded = []

    for l in lines:
        m_range = re.search(r"(.+?)\s*(?: issues?|,)?\s*#?(\d+)\s*[-–—]\s*(\d+)", l, re.IGNORECASE)
        if m_range:
            ser = m_range.group(1).strip()
            start_n = int(m_range.group(2))
            end_n = int(m_range.group(3))
            for num in range(start_n, end_n + 1):
                expanded.append({
                    "title": f"{ser} #{num}",
                    "series": ser,
                    "number": str(num),
                    "url": f"https://comicvine.gamespot.com/search/?q={urllib.parse.quote(ser + ' ' + str(num))}",
                    "cv_issue_id": "",
                    "is_found": False,
                    "is_tagged": False,
                    "file_path": ""
                })
        else:
            m_single = re.search(r"(.+?)\s*(?: issue| )?#?(\d+[a-zA-Z]?)", l, re.IGNORECASE)
            if m_single:
                ser = m_single.group(1).strip()
                num = m_single.group(2).strip()
                expanded.append({
                    "title": f"{ser} #{num}",
                    "series": ser,
                    "number": num,
                    "url": f"https://comicvine.gamespot.com/search/?q={urllib.parse.quote(ser + ' ' + num)}",
                    "cv_issue_id": "",
                    "is_found": False,
                    "is_tagged": False,
                    "file_path": ""
                })
            else:
                expanded.append({
                    "title": l,
                    "series": l,
                    "number": "1",
                    "url": f"https://comicvine.gamespot.com/search/?q={urllib.parse.quote(l)}",
                    "cv_issue_id": "",
                    "is_found": False,
                    "is_tagged": False,
                    "file_path": ""
                })

    if not watch_folder:
        watch_folder = "/mnt/disk1/Comics"

    file_cache = []
    if watch_folder and os.path.exists(watch_folder):
        for root, dirs, files in os.walk(watch_folder):
            for f in files:
                if f.lower().endswith((".cbz", ".cbr")):
                    file_cache.append((root, f, os.path.join(root, f)))

    found_count = 0
    tagged_count = 0

    for item in expanded:
        ser = item["series"]
        num = item["number"]
        clean_ser = ser.lower().replace("-", " ").replace(":", "")

        for root, f, full_p in file_cache:
            clean_f = f.lower().replace("-", " ").replace(":", "")
            if clean_ser in clean_f or ser.lower() in root.lower():
                if f"#{num}" in f or f"issue {num}" in f.lower() or f" {num}.cbz" in f.lower() or f"0{num}.cbz" in f.lower() or f"{num}." in f:
                    item["is_found"] = True
                    item["file_path"] = full_p
                    if f.lower().endswith(".cbz"):
                        try:
                            with zipfile.ZipFile(full_p, 'r') as zf:
                                item["is_tagged"] = "comicinfo.xml" in [n.lower() for n in zf.namelist()]
                        except Exception:
                            pass
                    break
        if item["is_found"]: found_count += 1
        if item["is_tagged"]: tagged_count += 1

    return {
        "title": arc_name,
        "deck": f"Full Chronological Crossover Saga ({len(expanded)} total issues across tie-in series)",
        "url": "",
        "image": "",
        "total_issues": len(expanded),
        "found_count": found_count,
        "tagged_count": tagged_count,
        "missing_count": len(expanded) - found_count,
        "issues": expanded
    }
