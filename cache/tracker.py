import os
import hashlib
from typing import Optional, Tuple
from cache.db import CacheManager

def calculate_sha256(file_path: str, chunk_size: int = 65536) -> str:
    """Calculates SHA256 hash of a file efficiently."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()

def get_file_metadata_info(file_path: str) -> Tuple[str, int, int]:
    """Returns (sha256, file_size, mtime) for a given file."""
    abs_path = os.path.abspath(file_path)
    stat = os.stat(abs_path)
    file_size = stat.st_size
    mtime = int(stat.st_mtime)
    sha256 = calculate_sha256(abs_path)
    return sha256, file_size, mtime

def is_file_unchanged(file_path: str, cache_mgr: CacheManager) -> bool:
    """
    Checks if a file's size, mtime, or SHA256 has changed since it was last processed.
    Returns True if file is unchanged (and can be safely skipped).
    """
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        return False

    rec = cache_mgr.get_file_record(abs_path)
    if not rec:
        return False

    stat = os.stat(abs_path)
    # Quick mtime & size check first before computing SHA256
    if stat.st_size != rec["file_size"] or int(stat.st_mtime) != rec["mtime"]:
        return False

    current_sha256 = calculate_sha256(abs_path)
    return current_sha256 == rec["sha256"]

def mark_file_processed(file_path: str, cache_mgr: CacheManager, provider_used: str = ""):
    """Calculates file stats and saves record to SQLite cache tracker."""
    abs_path = os.path.abspath(file_path)
    if os.path.exists(abs_path):
        sha256, file_size, mtime = get_file_metadata_info(abs_path)
        cache_mgr.save_file_record(abs_path, sha256, file_size, mtime, provider_used=provider_used)
