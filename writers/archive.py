import os
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
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


def verify_cbz_archive(archive_path: str):
    """
    Verifies the integrity of a updated CBZ archive.
    Ensures valid ZIP format, no corrupted files, presence and parseability of ComicInfo.xml,
    and presence of original content files.
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
    except Exception as e:
        if isinstance(e, ArchiveValidationError):
            raise e
        raise ArchiveValidationError(
            f"Failed to verify modified archive '{os.path.basename(archive_path)}': {e}",
            archive_path=archive_path,
            operation="verify_cbz",
            original_exception=e
        )


def embed_comicinfo_in_cbz(archive_path: str, comic: Comic) -> str:
    """
    Embeds or updates ComicInfo.xml inside a .cbz (ZIP) archive atomically.
    Returns the path to the updated archive.

    Uses safe atomic temporary swapping and verifies archive integrity before replacing original.
    Does NOT rename or restructure user volume directories.
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

    # Attempt temp file creation in target directory to support atomic os.replace()
    try:
        temp_file = tempfile.NamedTemporaryFile(dir=archive_dir, delete=False, prefix=".tmp_", suffix=".cbz")
        temp_path = temp_file.name
        temp_file.close()
    except Exception:
        # Fallback to system temp directory if target directory is restricted
        temp_file = tempfile.NamedTemporaryFile(dir=tempfile.gettempdir(), delete=False, prefix=".tmp_", suffix=".cbz")
        temp_path = temp_file.name
        temp_file.close()

    try:
        # 1. Copy ZIP contents to temp archive, injecting new ComicInfo.xml
        with zipfile.ZipFile(archive_path, 'r') as src_zip:
            with zipfile.ZipFile(temp_path, 'w', compression=zipfile.ZIP_DEFLATED) as dst_zip:
                for item in src_zip.infolist():
                    if item.filename.lower() != "comicinfo.xml":
                        data = src_zip.read(item.filename)
                        dst_zip.writestr(item, data)

                dst_zip.writestr("ComicInfo.xml", xml_data)

        # 2. Preserve original filesystem stats (mtime, permissions)
        try:
            shutil.copystat(archive_path, temp_path)
        except Exception:
            pass

        # 3. Pre-replacement integrity verification on temp file
        verify_cbz_archive(temp_path)

        # 4. Atomic replacement
        try:
            os.replace(temp_path, archive_path)
        except OSError:
            # Fallback across filesystems
            shutil.move(temp_path, archive_path)

        # 5. Post-replacement verification on target file
        verify_cbz_archive(archive_path)

    except PermissionError as pe:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise ArchiveWriteError(
            f"Permission denied: Unable to overwrite '{file_name}'. "
            f"The application lacks write permissions for target file or folder '{archive_dir}'. "
            f"Please update directory permissions or umask settings.",
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
