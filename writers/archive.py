import os
import shutil
import tempfile
import zipfile
from models.comic import Comic
from writers.comicinfo import generate_xml_bytes

def embed_comicinfo_in_cbz(archive_path: str, comic: Comic) -> str:
    """
    Embeds or updates ComicInfo.xml inside a .cbz (ZIP) archive atomically.
    Returns the path to the updated archive.

    The temp file is written to the system temp directory (/tmp) rather than
    the source directory, so network-mounted folders (NFS/Samba) that disallow
    creating new files don't cause Permission Denied errors.
    """
    if not os.path.exists(archive_path):
        raise FileNotFoundError(f"Archive file not found: {archive_path}")

    if not zipfile.is_zipfile(archive_path):
        ext = os.path.splitext(archive_path)[1].lower()
        if ext == ".cbr":
            raise ValueError(
                f"'{archive_path}' is a RAR archive (.cbr). Direct embedding is only supported for .cbz (ZIP) files. Please convert to .cbz first."
            )
        raise ValueError(f"File '{archive_path}' is not a valid ZIP archive.")

    if isinstance(comic, bytes):
        xml_data = comic
    else:
        xml_data = generate_xml_bytes(comic)

    # Always write temp file to /tmp — avoids permission issues on network mounts
    with tempfile.NamedTemporaryFile(dir=tempfile.gettempdir(), delete=False, suffix=".cbz") as temp_file:
        temp_path = temp_file.name

    try:
        with zipfile.ZipFile(archive_path, 'r') as src_zip:
            with zipfile.ZipFile(temp_path, 'w', compression=zipfile.ZIP_DEFLATED) as dst_zip:
                # Copy all files except existing ComicInfo.xml
                for item in src_zip.infolist():
                    if item.filename.lower() != "comicinfo.xml":
                        data = src_zip.read(item.filename)
                        dst_zip.writestr(item, data)

                # Write the new ComicInfo.xml at root
                dst_zip.writestr("ComicInfo.xml", xml_data)

        # Move finished file back to original path
        # shutil.move handles cross-filesystem (copy + delete) automatically
        try:
            shutil.move(temp_path, archive_path)
        except PermissionError as pe:
            raise PermissionError(
                f"Permission denied: Unable to overwrite '{os.path.basename(archive_path)}'. "
                f"The folder/file permissions on your NAS or storage target restrict write access for files created by Kapowarr/downloader. "
                f"Please update permissions on the NAS (e.g., chmod 777 -R on your Comics directory) or adjust Kapowarr/downloader umask/permission settings."
            ) from pe
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        if isinstance(e, PermissionError):
            raise e
        elif getattr(e, "errno", None) == 13:
            raise PermissionError(
                f"Permission denied: Unable to overwrite '{os.path.basename(archive_path)}'. "
                f"The folder/file permissions on your NAS or storage target restrict write access for files created by Kapowarr/downloader. "
                f"Please update permissions on the NAS (e.g., chmod 777 -R on your Comics directory) or adjust Kapowarr/downloader umask/permission settings."
            ) from e
        raise e

    return archive_path

