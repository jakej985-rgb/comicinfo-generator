import os
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional, Set
from models.comic import Comic
from writers.comicinfo import generate_xml_bytes

# --- Explicit Archive Exceptions ---
class ArchiveError(Exception):
    """Base exception for archive operations."""
    def __init__(self, message: str, archive_path: str = "", operation: str = "", original_exception: Exception = None):
        super().__init__(message)
        self.archive_path = archive_path
        self.operation = operation
        self.original_exception = original_exception

class ArchiveReadError(ArchiveError):
    """Raised when reading or inspecting an archive fails."""

class ArchiveWriteError(ArchiveError):
    """Raised when writing or replacing an archive fails."""

class ArchiveValidationError(ArchiveError):
    """Raised when post-replacement verification fails."""


def verify_cbz_archive(archive_path: str, original_entries: Optional[Set[str]] = None):
    """
    Phase 18: Expands archive verification before and after replacement.
    Ensures valid ZIP format, no corrupted files, presence and parseability of ComicInfo.xml,
    valid image count, and zero unexpected entry deletions compared to original archive entries.
    """
    if not os.path.exists(archive_path) or os.path.getsize(archive_path) == 0:
        raise ArchiveValidationError(
            f"Archive file '{os.path.basename(archive_path)}' is missing or 0 bytes after modification.",
            archive_path=archive_path,
            operation="verify_archive"
        )

    try:
        with zipfile.ZipFile(archive_path, "r") as z:
            # 1. ZIP file integrity test
            bad_file = z.testzip()
            if bad_file:
                raise ArchiveValidationError(
                    f"Corrupted file '{bad_file}' detected inside archive '{os.path.basename(archive_path)}'.",
                    archive_path=archive_path,
                    operation="testzip"
                )

            namelist = [n.lower() for n in z.namelist()]

            # 2. Confirm ComicInfo.xml presence
            if "comicinfo.xml" not in namelist:
                raise ArchiveValidationError(
                    f"ComicInfo.xml was not found inside '{os.path.basename(archive_path)}'.",
                    archive_path=archive_path,
                    operation="verify_comicinfo"
                )

            # 3. Confirm ComicInfo.xml is parseable
            try:
                xml_data = z.read([n for n in z.namelist() if n.lower() == "comicinfo.xml"][0])
                ET.fromstring(xml_data)
            except Exception as xe:
                raise ArchiveValidationError(
                    f"Generated ComicInfo.xml in '{os.path.basename(archive_path)}' is invalid XML: {xe}",
                    archive_path=archive_path,
                    operation="parse_comicinfo",
                    original_exception=xe
                )

            # 4. Confirm original image files exist
            image_files = [n for n in namelist if n.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif'))]
            if not image_files and len(namelist) <= 1:
                raise ArchiveValidationError(
                    f"Archive '{os.path.basename(archive_path)}' contains no image files after update.",
                    archive_path=archive_path,
                    operation="verify_images"
                )

            # 5. Phase 18: Compare original archive entries vs new archive entries
            if original_entries is not None:
                orig_non_xml = {n.lower() for n in original_entries if n.lower() != "comicinfo.xml"}
                new_non_xml = {n for n in namelist if n != "comicinfo.xml"}
                missing = orig_non_xml - new_non_xml
                if missing:
                    raise ArchiveValidationError(
                        f"Unexpected file deletion detected in '{os.path.basename(archive_path)}': missing {missing}",
                        archive_path=archive_path,
                        operation="verify_entry_preservation"
                    )

    except Exception as e:
        if isinstance(e, ArchiveValidationError):
            raise e
        raise ArchiveValidationError(
            f"Failed to verify modified archive '{os.path.basename(archive_path)}': {e}",
            archive_path=archive_path,
            operation="verify_cbz",
            original_exception=e
        )


def preserve_file_metadata(src_path: str, dst_path: str):
    """
    Preserves file permissions (mode), modification timestamps (mtime/atime),
    and original file ownership (UID/GID) where permitted without forcing changes.
    """
    try:
        shutil.copystat(src_path, dst_path)
    except Exception:
        pass

    try:
        st = os.stat(src_path)
        if hasattr(os, "chown"):
            try:
                os.chown(dst_path, st.st_uid, st.st_gid)
            except (PermissionError, OSError):
                pass
    except Exception:
        pass


def fsync_file(file_path: str):
    """Fsyncs a file descriptor to ensure bytes are committed to persistent disk media."""
    try:
        fd = os.open(file_path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        pass


def embed_comicinfo_in_cbz(archive_path: str, comic: Comic) -> str:
    """
    Embeds or updates ComicInfo.xml inside a .cbz (ZIP) archive atomically.
    Returns the path to the updated archive.

    Guarantees strict same-filesystem atomic transactions:
    1. Record original archive entries (Phase 18)
    2. Create temporary archive in same target directory
    3. Write updated ZIP contents
    4. Preserve permissions & timestamps (Phase 17)
    5. Pre-replacement integrity verification & entry comparison (Phase 18)
    6. fsync temporary file to storage media (Phase 16)
    7. os.replace() atomic swap (Phase 16)
    8. Post-replacement verification
    """
    if not os.path.exists(archive_path):
        raise ArchiveReadError(
            f"Archive file not found: '{archive_path}'",
            archive_path=archive_path,
            operation="read_file"
        )

    if not zipfile.is_zipfile(archive_path):
        ext = os.path.splitext(archive_path)[1].lower()
        if ext == ".cbr":
            raise ArchiveReadError(
                f"'{archive_path}' is a RAR archive (.cbr). Direct embedding is only supported for .cbz (ZIP) files. Please convert to .cbz first.",
                archive_path=archive_path,
                operation="validate_zip"
            )
        raise ArchiveReadError(
            f"File '{archive_path}' is not a valid ZIP archive.",
            archive_path=archive_path,
            operation="validate_zip"
        )

    if isinstance(comic, bytes):
        xml_data = comic
    else:
        xml_data = generate_xml_bytes(comic)

    archive_dir = os.path.dirname(os.path.abspath(archive_path))
    file_name = os.path.basename(archive_path)

    # Phase 18: Record original archive entries
    original_entries = set()
    try:
        with zipfile.ZipFile(archive_path, 'r') as src_z:
            original_entries = set(src_z.namelist())
    except Exception:
        pass

    # Phase 16 Step 1: Create temporary archive strictly in same directory to guarantee atomic os.replace()
    try:
        temp_file = tempfile.NamedTemporaryFile(dir=archive_dir, delete=False, prefix=".tmp_", suffix=".cbz")
        temp_path = temp_file.name
        temp_file.close()
    except Exception as e:
        raise ArchiveWriteError(
            f"Unable to create temporary file in target directory '{archive_dir}': {e}. "
            f"Same-filesystem atomic replacement is required.",
            archive_path=archive_path,
            operation="create_temp_file",
            original_exception=e
        )

    try:
        # Phase 16 & 43: Write archive preserving entry compress_type (avoids re-compressing JPEGs/PNGs)
        with zipfile.ZipFile(archive_path, 'r') as src_zip:
            with zipfile.ZipFile(temp_path, 'w') as dst_zip:
                for item in src_zip.infolist():
                    if item.filename.lower() != "comicinfo.xml":
                        data = src_zip.read(item.filename)
                        dst_zip.writestr(item, data, compress_type=item.compress_type)

                dst_zip.writestr("ComicInfo.xml", xml_data, compress_type=zipfile.ZIP_DEFLATED)

        # Phase 17: Preserve file metadata (permissions, mtime, atime, UID/GID)
        preserve_file_metadata(archive_path, temp_path)

        # Phase 18: Pre-replacement integrity verification on temp file comparing original entries
        verify_cbz_archive(temp_path, original_entries=original_entries)

        # Phase 16 Step 4: fsync temporary file
        fsync_file(temp_path)

        # Phase 16 Step 5: Atomic replacement (no cross-filesystem downgrade)
        try:
            os.replace(temp_path, archive_path)
        except Exception as re_err:
            raise ArchiveWriteError(
                f"Atomic replacement failed for '{file_name}': {re_err}.",
                archive_path=archive_path,
                operation="os.replace",
                original_exception=re_err
            )

        # Phase 16 Step 6: Post-replacement verification on final file
        verify_cbz_archive(archive_path, original_entries=original_entries)

    except PermissionError as pe:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise ArchiveWriteError(
            f"Permission denied: Unable to overwrite '{file_name}'. "
            f"The application lacks write permissions for target file or folder '{archive_dir}'.",
            archive_path=archive_path,
            operation="atomic_replace",
            original_exception=pe
        ) from pe
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        if isinstance(e, ArchiveError):
            raise e
        raise ArchiveWriteError(
            f"Failed to update archive '{file_name}': {e}",
            archive_path=archive_path,
            operation="embed_comicinfo",
            original_exception=e
        ) from e

    return archive_path
