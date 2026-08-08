import os
import shutil
import tempfile
import zipfile
from models.comic import Comic
from writers.comicinfo import generate_xml_bytes

def _try_takeover_folder_permissions(archive_path: str, temp_path: str) -> bool:

    """
    If Kapowarr or a downloader created a volume folder with restricted permissions on a network share,
    this automatically recreates the volume folder under the current user's ownership (via writable parent folder),
    transfers all files, and places the newly tagged file cleanly in place.
    """
    try:
        vol_dir = os.path.dirname(os.path.abspath(archive_path))
        parent_dir = os.path.dirname(vol_dir)
        vol_name = os.path.basename(vol_dir)
        file_name = os.path.basename(archive_path)

        if not (parent_dir and vol_name and os.path.exists(parent_dir)):
            return False

        bak_dir = os.path.join(parent_dir, f".{vol_name}_kapowarr_bak")

        # 1. Rename existing read-only volume folder to hidden backup
        if os.path.exists(bak_dir):
            import time
            bak_dir = os.path.join(parent_dir, f".{vol_name}_kapowarr_bak_{int(time.time())}")

        os.rename(vol_dir, bak_dir)

        # 2. Create fresh volume folder owned by current user
        os.makedirs(vol_dir, exist_ok=True)

        # 3. Transfer all files: place newly tagged temp_path for target file, copy others
        for f in os.listdir(bak_dir):
            src_f = os.path.join(bak_dir, f)
            dst_f = os.path.join(vol_dir, f)
            if f == file_name:
                shutil.move(temp_path, dst_f)
            else:
                if os.path.isfile(src_f):
                    shutil.copy2(src_f, dst_f)

        # Clean up temp file if still present
        if os.path.exists(temp_path):
            os.remove(temp_path)

        return True
    except Exception:
        return False

def embed_comicinfo_in_cbz(archive_path: str, comic: Comic) -> str:
    """
    Embeds or updates ComicInfo.xml inside a .cbz (ZIP) archive atomically.
    Returns the path to the updated archive.

    The temp file is written to the system temp directory (/tmp) rather than
    the source directory, so network-mounted folders (NFS/Samba) that disallow
    creating new files don't cause Permission Denied errors.
    Automatically handles folder permission takeover if Kapowarr created read-only dirs.
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
        try:
            shutil.move(temp_path, archive_path)
        except (PermissionError, OSError) as pe:
            # Automatic takeover of Kapowarr/downloader created folder permissions
            if _try_takeover_folder_permissions(archive_path, temp_path):
                return archive_path
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


