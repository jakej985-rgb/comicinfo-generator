# Actual Metadata Resolution — ComicInfo Generator

## 1. Overview

Metadata resolution in `comicinfo-generator` is coordinated primarily by `MetadataResolver` in [`pipeline/resolver.py`](file:///home/m3tal/apps/comicinfo-generator/pipeline/resolver.py). It takes input filenames, directories, or explicit URLs and returns a normalized `Comic` dataclass object.

---

## 2. Priority Hierarchy

When `MetadataResolver.resolve_file_metadata(file_path, url_override, force_overwrite)` is called, providers are evaluated in the following order:

```text
1. Existing embedded ComicInfo.xml
   └─ Check if .cbz contains a valid ComicInfo.xml.
   └─ Bypassed only if force_overwrite is True or config.output.overwrite is True.

2. Explicit URL or Copied Text Override (url_override)
   ├─ Contains "comics.org" or "Pencils:": GCP Provider
   ├─ Contains "comicvine": ComicVine Provider
   └─ Contains "kapowarr" or numeric ID: Kapowarr Provider

3. Kapowarr Lookup (Preferred Provider)
   └─ Searches Kapowarr API by basename(file_path).

4. ComicVine Lookup
   └─ Searches Comic Vine search index by basename(file_path) and scrapes matched issue URL.

5. Grand Comics Database (GCP) Fallback
   └─ Searches GCP search index by basename(file_path) and scrapes matched issue URL.

6. Unresolved (None)
   └─ Returns (None, "None") if no provider matches.
```

---

## 3. Existing XML Parsing (`read_existing_comicinfo`)

`read_existing_comicinfo(cbz_path)` in `pipeline/resolver.py` reads `ComicInfo.xml` from a `.cbz` archive using Python's standard `xml.etree.ElementTree`.

Fields parsed:
- `Title`, `Series`, `Number`, `Volume`, `Summary`, `Notes`, `Publisher`, `Genre`, `Web`
- `Year`, `Month`, `Day`
- `Writer`, `Penciller`, `Inker`, `Colorist`, `Letterer` (split by `,`)
- `Characters` (split by `,`)
- `StoryArc` / `Storyarc` (findall, split by `,` and normalized)
- `StoryArcNumber` (findall, split by `,`)

---

## 4. Multi-Issue & Collected Edition Merging (`merge_comics`)

When a single file represents a collected edition, trade paperback (TPB), or omnibus containing multiple single issues, `merge_comics(comics)` in [`models/comic.py`](file:///home/m3tal/apps/comicinfo-generator/models/comic.py) combines an ordered list of single-issue `Comic` objects into one merged `Comic`:

- **Series, Publisher, Genre, Language**: Inherited from the first comic (`comics[0]`).
- **Format**: Set to `"Trade Paperback"`.
- **Count**: Set to `len(comics)`.
- **Number**: Calculated issue range (e.g. `1-6` if integers, or comma-separated list).
- **Title**: Formatted as `{series} #{number}`.
- **Year/Month/Day**: Set to the earliest release date among all issues.
- **Summary**: Formatted with per-issue headers:
  ```text
  --- Issue #1 ---
  [Issue 1 Summary]

  --- Issue #2 ---
  [Issue 2 Summary]
  ```
- **Creators, Characters, Teams, Story Arcs**: Merged and deduplicated while preserving order.

---

## 5. Story Arc Tracking (`providers/story_arc.py`)

`providers/story_arc.py` manages chronological reading order crossovers and story arc tagging (such as *Marvel Zombies*):
- Parses custom chronological reading lists (`parse_custom_chronological_reading_order`).
- Performs regex fuzzy matching against file names (`#001`, `Volume 01 Issue 001`).
- Assigns `<StoryArc>` and `<StoryArcNumber>` tags.
