# Actual Archive Safety — ComicInfo Generator

## 1. Overview

Archive modification and file updates are handled in [`writers/archive.py`](file:///home/m3tal/apps/comicinfo-generator/writers/archive.py) and [`converters/cbr_to_cbz.py`](file:///home/m3tal/apps/comicinfo-generator/converters/cbr_to_cbz.py).

---

## 2. Current Implementation (`embed_comicinfo_in_cbz`)

The `embed_comicinfo_in_cbz(archive_path, comic)` function updates or embeds a `ComicInfo.xml` file inside a `.cbz` archive:

```text
Target Archive (.cbz)
        │
        ▼
Validation Checks:
  - Check file exists (FileNotFoundError)
  - Verify zipfile.is_zipfile(archive_path) (ValueError)
        │
        ▼
Generate XML Bytes (writers/comicinfo.py generate_xml_bytes)
        │
        ▼
Create Temporary File in System Temp Directory (/tmp):
  tempfile.NamedTemporaryFile(dir=tempfile.gettempdir(), suffix=".cbz")
        │
        ▼
Copy Archive Contents:
  - Open source ZIP ('r') and target temp ZIP ('w')
  - Copy all files EXCEPT existing 'comicinfo.xml'
  - Write new 'ComicInfo.xml' at ZIP root
        │
        ▼
Replace Original Archive:
  shutil.move(temp_path, archive_path)
```

---

## 3. Permission Fallback & Takeover Behavior (`_try_takeover_folder_permissions`)

If `shutil.move()` raises a `PermissionError` or `OSError` (e.g. when network shares mounted from NAS/Kapowarr create read-only directories), `writers/archive.py` calls `_try_takeover_folder_permissions()`:

```text
_try_takeover_folder_permissions(archive_path, temp_path)
        │
        ▼
1. Locate parent volume directory (vol_dir = os.path.dirname(archive_path))
2. Rename vol_dir to hidden backup folder:
   .{vol_name}_kapowarr_bak
3. Re-create fresh volume directory (os.makedirs(vol_dir)) owned by current user
4. Move newly embedded temp_path file into vol_dir
5. Copy all other files from .bak folder into new vol_dir
```

> **Warning / Security Note**:
> This folder takeover mechanism modifies parent directory structures and file ownership on disk. It is flagged in `plan.md` as unsafe for unattended library automation and must be disabled or replaced with explicit error handling.

---

## 4. CBR (RAR) to CBZ (ZIP) Conversion (`converters/cbr_to_cbz.py`)

When an input comic is in `.cbr` (RAR) format:
1. `convert_cbr_to_cbz(cbr_path, delete_original=True)` extracts RAR entries using `patool` or system archive utilities (`unrar` / `bsdtar`) into a temporary working folder.
2. Creates a clean `.cbz` ZIP archive containing all extracted page images.
3. If `delete_original` is True, removes the original `.cbr` file on success.
