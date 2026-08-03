import os
import shutil
import subprocess
import tempfile
import zipfile

def find_extractor():
    """Finds the best available RAR/CBR extractor command."""
    # 1. Project bundled official RARLAB unrar binary
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_unrar = os.path.join(repo_dir, "bin", "unrar")
    if os.path.exists(local_unrar) and os.access(local_unrar, os.X_OK):
        return ("unrar", local_unrar)

    # 2. System unrar
    sys_unrar = shutil.which("unrar")
    if sys_unrar:
        return ("unrar", sys_unrar)

    # 3. System unar
    sys_unar = shutil.which("unar")
    if sys_unar:
        return ("unar", sys_unar)

    # 4. System bsdtar
    sys_bsdtar = shutil.which("bsdtar")
    if sys_bsdtar:
        return ("bsdtar", sys_bsdtar)

    # 5. System 7z
    sys_7z = shutil.which("7z") or shutil.which("7za")
    if sys_7z:
        return ("7z", sys_7z)

    return (None, None)

def convert_cbr_to_cbz(cbr_path: str, delete_original: bool = False) -> str:
    """
    Converts a .cbr (RAR/RAR5) archive to a .cbz (ZIP) archive.
    Uses -kb (Keep Broken/partial files) so minor checksum issues don't abort extraction.
    Only deletes original .cbr if extraction had ZERO errors and .cbz is verified.
    Returns the path to the created .cbz file.
    """
    if not os.path.exists(cbr_path):
        raise FileNotFoundError(f"File not found: '{cbr_path}'")

    base_name = os.path.splitext(cbr_path)[0]
    cbz_path = f"{base_name}.cbz"

    tool_type, tool_path = find_extractor()
    if not tool_path:
        raise RuntimeError("No RAR extractor utility found. Please install 'unrar' or 'unar'.")

    has_extraction_warning = False

    with tempfile.TemporaryDirectory() as temp_dir:
        # Extract CBR archive depending on tool type (adding -kb for unrar to keep files despite CRC warning)
        if tool_type == "unrar":
            cmd = [tool_path, "x", "-kb", "-o+", "-y", cbr_path, f"{temp_dir}/"]
        elif tool_type == "unar":
            cmd = [tool_path, "-o", temp_dir, "-f", cbr_path]
        elif tool_type == "bsdtar":
            cmd = [tool_path, "-xf", cbr_path, "-C", temp_dir]
        else: # 7z
            cmd = [tool_path, "x", "-y", f"-o{temp_dir}", cbr_path]

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if res.returncode != 0:
            has_extraction_warning = True

        # Check extracted files
        extracted_files = []
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                extracted_files.append(os.path.join(root, file))

        # If zero files were extracted, try 7z fallback
        if not extracted_files and tool_type != "7z":
            sys_7z = shutil.which("7z") or shutil.which("7za")
            if sys_7z:
                cmd_fallback = [sys_7z, "x", "-y", f"-o{temp_dir}", cbr_path]
                res_fallback = subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        extracted_files.append(os.path.join(root, file))

        if not extracted_files:
            raise RuntimeError(f"Failed to extract CBR file '{cbr_path}': {res.stderr or res.stdout or 'No files extracted'}")

        # Create CBZ archive
        dir_name = os.path.dirname(os.path.abspath(cbz_path))
        with tempfile.NamedTemporaryFile(dir=dir_name, delete=False, suffix=".cbz") as temp_file:
            temp_cbz_path = temp_file.name

        try:
            with zipfile.ZipFile(temp_cbz_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in sorted(files):
                        file_full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_full_path, temp_dir)
                        zf.write(file_full_path, rel_path)

            # Move temporary CBZ file to final path
            shutil.move(temp_cbz_path, cbz_path)
        except Exception as e:
            if os.path.exists(temp_cbz_path):
                os.remove(temp_cbz_path)
            raise e

    # CRITICAL SAFETY RULE:
    # Only delete original .cbr if extraction had ZERO errors and target .cbz exists & is non-empty
    if delete_original and not has_extraction_warning:
        if os.path.exists(cbz_path) and os.path.getsize(cbz_path) > 0 and os.path.exists(cbr_path):
            os.remove(cbr_path)

    return cbz_path
