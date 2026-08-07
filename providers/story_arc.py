import os
import re
import urllib.parse
import zipfile
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from config import load_config
from providers.kapowarr import KapowarrProvider
from writers.archive import embed_comicinfo_in_cbz

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

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
                        "story_arc_tag": "",
                        "story_arc_num": "",
                        "has_matching_arc": False,
                        "file_path": ""
                    })

        _cross_reference_issues(issues, story_arc_name=arc_title, watch_folder=watch_folder)

        found_count = sum(1 for i in issues if i["is_found"])
        tagged_count = sum(1 for i in issues if i["is_tagged"])
        arc_tagged_count = sum(1 for i in issues if i["has_matching_arc"])
        missing_count = len(issues) - found_count

        return {
            "title": arc_title,
            "deck": deck,
            "url": url_str,
            "image": img_url,
            "total_issues": len(issues),
            "found_count": found_count,
            "tagged_count": tagged_count,
            "arc_tagged_count": arc_tagged_count,
            "missing_count": missing_count,
            "issues": issues
        }
    except Exception as e:
        return {"error": f"Error loading story arc: {e}"}

def parse_custom_chronological_reading_order(text: str, arc_name: str = "Chronological Story Arc Crossover", watch_folder: str = "") -> dict:
    """Expands multi-series range lists into issue entries and checks disk and Kapowarr."""
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
                    "story_arc_tag": "",
                    "story_arc_num": "",
                    "has_matching_arc": False,
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
                    "story_arc_tag": "",
                    "story_arc_num": "",
                    "has_matching_arc": False,
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
                    "story_arc_tag": "",
                    "story_arc_num": "",
                    "has_matching_arc": False,
                    "file_path": ""
                })

    _cross_reference_issues(expanded, story_arc_name=arc_name, watch_folder=watch_folder)

    found_count = sum(1 for i in expanded if i["is_found"])
    tagged_count = sum(1 for i in expanded if i["is_tagged"])
    arc_tagged_count = sum(1 for i in expanded if i["has_matching_arc"])
    missing_count = len(expanded) - found_count

    return {
        "title": arc_name,
        "deck": f"Full Chronological Crossover Saga ({len(expanded)} total issues across tie-in series)",
        "url": "",
        "image": "",
        "total_issues": len(expanded),
        "found_count": found_count,
        "tagged_count": tagged_count,
        "arc_tagged_count": arc_tagged_count,
        "missing_count": missing_count,
        "issues": expanded
    }

def _cross_reference_issues(issues_list: list[dict], story_arc_name: str = "", watch_folder: str = "") -> None:
    """Indexes local watch_folder AND Kapowarr monitored volume directories for issue matching."""
    cfg = load_config()
    if not watch_folder:
        watch_folder = cfg.automation.watch_folder or "/mnt/disk1/Comics"

    # Query Kapowarr volume folder paths
    search_folders = set()
    if watch_folder and os.path.exists(watch_folder):
        search_folders.add(watch_folder)

    if cfg.kapowarr.url:
        try:
            kap = KapowarrProvider(url=cfg.kapowarr.url, api_key=cfg.kapowarr.api_key)
            vols = kap.search_series("")
            for v in vols:
                v_id = v.get("id")
                r = requests.get(f"{cfg.kapowarr.url.rstrip('/')}/api/volumes/{v_id}", headers=kap._get_headers(), params=kap._get_params(), timeout=3)
                if r.status_code == 200:
                    v_info = r.json()
                    if isinstance(v_info, dict):
                        v_data = v_info.get("result", v_info)
                        f_p = v_data.get("folder") or v_data.get("path")
                        if f_p and os.path.exists(f_p):
                            search_folders.add(f_p)
        except Exception:
            pass

    # Build file index
    file_index = []
    for s_dir in search_folders:
        for root, dirs, files in os.walk(s_dir):
            for f in files:
                if f.lower().endswith((".cbz", ".cbr")):
                    file_index.append((root, f, os.path.join(root, f)))

    for idx, item in enumerate(issues_list):
        ser = item.get("series", "")
        num = item.get("number", "")

        try:
            target_n = int(re.search(r"(\d+)", str(num)).group(1))
        except Exception:
            target_n = None

        item["is_found"] = False
        item["is_tagged"] = False
        item["story_arc_tag"] = ""
        item["story_arc_num"] = ""
        item["has_matching_arc"] = False
        item["file_path"] = ""

        for root, f, full_p in file_index:
            if _is_exact_series_match(ser, f, root) and target_n is not None:
                patterns = [
                    r"issue\s*0*(" + str(target_n) + r")\b",
                    r"#\s*0*(" + str(target_n) + r")\b",
                    r"\b0*(" + str(target_n) + r")\.(?:cbz|cbr)$",
                    r"vol(?:ume)?\s*\d+\s+issue\s+0*(" + str(target_n) + r")\b",
                    r"v\d+\s+0*(" + str(target_n) + r")\b",
                    r"[-_\s]0*(" + str(target_n) + r")[-_\s\.]"
                ]
                matched = False
                for pat in patterns:
                    if re.search(pat, f, re.IGNORECASE):
                        matched = True
                        break
                if matched:
                    item["is_found"] = True
                    item["file_path"] = full_p
                    if f.lower().endswith(".cbz"):
                        story_arc_tag, story_arc_num, is_xml_present = _read_story_arc_from_cbz(full_p)
                        item["is_tagged"] = is_xml_present
                        item["story_arc_tag"] = story_arc_tag
                        item["story_arc_num"] = story_arc_num
                        clean_arc_name = _clean_arc_name(story_arc_name)
                        item["has_matching_arc"] = bool(clean_arc_name and clean_arc_name in story_arc_tag.lower())
                    break

def _clean_arc_name(raw: str) -> str:
    if not raw:
        return ""
    m = re.search(r'"([^"]+)"', raw)
    if m:
        return m.group(1).lower().strip()
    clean = re.sub(r"\(.*?\)", "", raw).lower().strip()
    return clean

def _read_story_arc_from_cbz(file_path: str) -> tuple[str, str, bool]:
    """Reads <StoryArc> and <StoryArcNumber> from ComicInfo.xml inside a .cbz archive."""
    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            names = [n.lower() for n in zf.namelist()]
            if "comicinfo.xml" in names:
                for n in zf.namelist():
                    if n.lower() == "comicinfo.xml":
                        xml_bytes = zf.read(n)
                        root = ET.fromstring(xml_bytes)
                        arc = root.findtext("StoryArc") or root.findtext("Storyarc") or ""
                        num = root.findtext("StoryArcNumber") or ""
                        return arc.strip(), num.strip(), True
    except Exception:
        pass
    return "", "", False

def _parse_arc_list(text: str) -> list[str]:
    """Splits a comma/semicolon separated <StoryArc> value into a list."""
    if not text:
        return []
    return [s.strip() for s in re.split(r"[,;]", text) if s.strip()]

def _parse_num_list(text: str) -> list[str]:
    """Splits a comma/semicolon separated <StoryArcNumber> value into a list."""
    if not text:
        return []
    return [s.strip() for s in re.split(r"[,;]", text) if s.strip()]

def fix_story_arcs_on_device(issues_list: list[dict], story_arc_name: str) -> dict:
    """Additively writes <StoryArc> and <StoryArcNumber> into ComicInfo.xml for all found files.
    If the file already has other story arcs they are preserved; only this arc's entry is added/updated."""
    arc_name = story_arc_name.strip()
    updated_count = 0
    errors = []

    for idx, iss in enumerate(issues_list):
        full_p = iss.get("file_path", "")
        if not (iss.get("is_found") and full_p and os.path.exists(full_p) and full_p.lower().endswith(".cbz")):
            continue
        order_num = str(idx + 1)
        try:
            # Read existing XML or build minimal skeleton
            existing_xml_bytes = None
            with zipfile.ZipFile(full_p, "r") as zf:
                for n in zf.namelist():
                    if n.lower() == "comicinfo.xml":
                        existing_xml_bytes = zf.read(n)
                        break

            if existing_xml_bytes:
                root = ET.fromstring(existing_xml_bytes)
            else:
                root = ET.Element("ComicInfo")
                fname = os.path.basename(full_p)
                ET.SubElement(root, "Title").text = iss.get("title") or fname
                ET.SubElement(root, "Series").text = iss.get("series") or ""
                ET.SubElement(root, "Number").text = iss.get("number") or "1"

            # ── Additive StoryArc logic ──────────────────────────────────────
            arc_elem = root.find("StoryArc") or root.find("Storyarc")
            num_elem = root.find("StoryArcNumber")

            existing_arcs = _parse_arc_list(arc_elem.text if arc_elem is not None else "")
            existing_nums = _parse_num_list(num_elem.text if num_elem is not None else "")
            # Pad nums to same length as arcs
            while len(existing_nums) < len(existing_arcs):
                existing_nums.append("")

            # Normalise comparison (case-insensitive)
            norm_name = arc_name.lower()
            arc_positions = [a.lower() for a in existing_arcs]

            if norm_name in arc_positions:
                # Update existing entry's number
                pos = arc_positions.index(norm_name)
                existing_nums[pos] = order_num
            else:
                # Append new arc entry
                existing_arcs.append(arc_name)
                existing_nums.append(order_num)

            # Write back
            if arc_elem is None:
                arc_elem = ET.SubElement(root, "StoryArc")
            arc_elem.text = ", ".join(existing_arcs)

            if num_elem is None:
                num_elem = ET.SubElement(root, "StoryArcNumber")
            num_elem.text = ", ".join(existing_nums)

            new_xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            embed_comicinfo_in_cbz(full_p, new_xml_bytes)
            updated_count += 1
        except Exception as e:
            errors.append(f"{os.path.basename(full_p)}: {e}")

    return {
        "success": True,
        "updated_count": updated_count,
        "errors": errors,
        "message": f"Successfully added/updated <StoryArc> metadata in {updated_count} local comic file(s) on device!"
    }

def rename_story_arc_on_device(issues_list: list[dict], old_name: str, new_name: str) -> dict:
    """Renames an arc tag in ComicInfo.xml across all found files.
    Replaces old_name with new_name inside the comma-separated <StoryArc> list,
    keeping all other arcs untouched."""
    old_norm = old_name.strip().lower()
    new_name = new_name.strip()
    renamed_count = 0
    skipped_count = 0
    errors = []

    for iss in issues_list:
        full_p = iss.get("file_path", "")
        if not (iss.get("is_found") and full_p and os.path.exists(full_p) and full_p.lower().endswith(".cbz")):
            continue
        try:
            existing_xml_bytes = None
            with zipfile.ZipFile(full_p, "r") as zf:
                for n in zf.namelist():
                    if n.lower() == "comicinfo.xml":
                        existing_xml_bytes = zf.read(n)
                        break

            if not existing_xml_bytes:
                skipped_count += 1
                continue

            root = ET.fromstring(existing_xml_bytes)
            arc_elem = root.find("StoryArc") or root.find("Storyarc")
            if arc_elem is None or not arc_elem.text:
                skipped_count += 1
                continue

            existing_arcs = _parse_arc_list(arc_elem.text)
            arc_norms = [a.lower() for a in existing_arcs]

            if old_norm not in arc_norms:
                skipped_count += 1
                continue

            # Replace in place
            pos = arc_norms.index(old_norm)
            existing_arcs[pos] = new_name
            arc_elem.text = ", ".join(existing_arcs)

            new_xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            embed_comicinfo_in_cbz(full_p, new_xml_bytes)
            renamed_count += 1
        except Exception as e:
            errors.append(f"{os.path.basename(full_p)}: {e}")

    return {
        "success": True,
        "renamed_count": renamed_count,
        "skipped_count": skipped_count,
        "errors": errors,
        "message": f"Renamed '{old_name}' → '{new_name}' in {renamed_count} file(s). {skipped_count} file(s) did not contain the old arc tag."
    }

def _is_exact_series_match(target_series: str, file_name: str, folder_path: str) -> bool:
    clean_target = target_series.lower().replace("-", " ").replace(":", "").strip()
    clean_f = file_name.lower().replace("-", " ").replace(":", "").strip()
    clean_folder = folder_path.lower().replace("-", " ").replace(":", "").strip()
    full_path_clean = (clean_folder + " " + clean_f).strip()

    target_words = [w for w in clean_target.split() if len(w) > 0]
    if not target_words:
        return False

    main_words = [w for w in target_words if w not in ("the", "a", "an", "of", "and")]
    if not all(w in full_path_clean for w in main_words):
        return False

    m_digit = re.search(r"(\d+)$", clean_target)
    if m_digit:
        digit = m_digit.group(1)
        base = clean_target[:m_digit.start()].strip()
        base_words = [w for w in base.split() if w not in ("the", "a", "an", "of", "and")]
        if not all(w in full_path_clean for w in base_words):
            return False
        digit_match = (f" {digit} " in full_path_clean or f" 0{digit} " in full_path_clean or 
                       f"volume 0{digit}" in full_path_clean or f"volume {digit}" in full_path_clean or
                       f"v0{digit}" in full_path_clean or f"v{digit}" in full_path_clean or
                       f"{base} {digit}" in full_path_clean or f"{base} 0{digit}" in full_path_clean)
        return digit_match

    return True
