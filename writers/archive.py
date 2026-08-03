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

    xml_data = generate_xml_bytes(comic)
    dir_name = os.path.dirname(os.path.abspath(archive_path))
    
    # Create temp zip file in the same directory for atomic replace
    with tempfile.NamedTemporaryFile(dir=dir_name, delete=False, suffix=".cbz") as temp_file:
        temp_path = temp_file.name

    try:
        with zipfile.ZipFile(archive_path, 'r') as src_zip:
            with zipfile.ZipFile(temp_path, 'w', compression=zipfile.ZIP_DEFLATED) as dst_zip:
                # Copy all files except existing ComicInfo.xml
                for item in src_zip.infolist():
                    if item.filename.lower() not in ("comicinfo.xml", "comicinfo.xml"):
                        data = src_zip.read(item.filename)
                        dst_zip.writestr(item, data)
                
                # Write the new ComicInfo.xml at root
                dst_zip.writestr("ComicInfo.xml", xml_data)

        # Atomically replace original archive
        shutil.move(temp_path, archive_path)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e

    return archive_path
