"""
services/processing.py — Phase 32

Archive processing service: file discovery, CBR conversion, embedding,
and native OS file-picker dialogs.
No HTTP concerns.
"""
import os
import shutil
import subprocess

from models.comic import Comic
from config import load_config
from cache.db import CacheManager
from cache.tracker import mark_file_processed
from converters.cbr_to_cbz import convert_cbr_to_cbz
from writers.archive import embed_comicinfo_in_cbz


def find_file_path(path_str: str) -> str:
    """Searches common directories to resolve a file path that may not be absolute."""
    if os.path.exists(path_str):
        return path_str

    filename = os.path.basename(path_str)
    search_dirs = [
        os.getcwd(),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Comics"),
        os.path.expanduser("~"),
        "/media/m3tal",
        "/mnt"
    ]

    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        candidate = os.path.join(sdir, filename)
        if os.path.exists(candidate):
            return candidate

    return ""


def open_native_file_picker() -> str:
    """Opens zenity or kdialog file picker dialog and returns chosen path."""
    try:
        zenity_path = shutil.which("zenity")
        if zenity_path:
            res = subprocess.run(
                [zenity_path, "--file-selection",
                 "--title=Select Comic Archive (.cbz or .cbr)",
                 "--file-filter=Comic Archives (*.cbz *.cbr) | *.cbz *.cbr"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()

        kdialog_path = shutil.which("kdialog")
        if kdialog_path:
            res = subprocess.run(
                [kdialog_path, "--getopenfilename", os.path.expanduser("~"),
                 "*.cbz *.cbr|Comic Archives (*.cbz *.cbr)"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
    except Exception:
        pass
    return ""


def open_native_folder_picker() -> str:
    """Opens zenity or kdialog folder picker dialog and returns chosen path."""
    try:
        zenity_path = shutil.which("zenity")
        if zenity_path:
            res = subprocess.run(
                [zenity_path, "--file-selection", "--directory",
                 "--title=Select Comics Folder Directory"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()

        kdialog_path = shutil.which("kdialog")
        if kdialog_path:
            res = subprocess.run(
                [kdialog_path, "--getexistingdirectory", os.path.expanduser("~")],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
    except Exception:
        pass
    return ""


def embed_and_track(
    archive_path: str,
    comic: Comic,
    provider: str = "Manual",
    cache_mgr: CacheManager = None
) -> str:
    """
    Embeds ComicInfo.xml into archive and records the result in the tracker.
    Returns the target archive path (which may differ from input if CBR was converted).
    """
    cfg = load_config()

    target_archive = archive_path
    if archive_path.lower().endswith(".cbr"):
        target_archive = convert_cbr_to_cbz(
            archive_path,
            delete_original=cfg.output.delete_cbr
        )

    embed_comicinfo_in_cbz(target_archive, comic)

    try:
        mgr = cache_mgr or CacheManager(cfg.cache.db_path)
        mark_file_processed(target_archive, mgr, provider_used=provider)
        mgr.save_cached_issue(
            provider,
            comic.provider_id or comic.number or os.path.basename(target_archive),
            comic
        )
    except Exception:
        pass

    return target_archive
