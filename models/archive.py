import os
import hashlib
from dataclasses import dataclass

@dataclass
class ArchiveRecord:
    """
    Represents an inspected comic archive file on disk separately from identity and metadata.
    """
    path: str = ""
    filename: str = ""
    extension: str = ""
    sha256: str = ""
    size: int = 0
    mtime: int = 0
    archive_type: str = "CBZ"
    comicinfo_present: bool = False

    @classmethod
    def from_file(cls, file_path: str) -> "ArchiveRecord":
        abs_path = os.path.abspath(file_path)
        filename = os.path.basename(abs_path)
        ext = os.path.splitext(filename)[1].lower()
        stat = os.stat(abs_path) if os.path.exists(abs_path) else None

        sha256 = ""
        if stat and stat.st_size > 0:
            h = hashlib.sha256()
            try:
                with open(abs_path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                sha256 = h.hexdigest()
            except Exception:
                pass

        # Check ComicInfo.xml presence
        comicinfo_present = False
        if ext == ".cbz" and os.path.exists(abs_path):
            try:
                import zipfile
                with zipfile.ZipFile(abs_path, "r") as z:
                    comicinfo_present = any(n.lower() == "comicinfo.xml" for n in z.namelist())
            except Exception:
                pass

        return cls(
            path=abs_path,
            filename=filename,
            extension=ext,
            sha256=sha256,
            size=stat.st_size if stat else 0,
            mtime=int(stat.st_mtime) if stat else 0,
            archive_type="CBR" if ext == ".cbr" else "CBZ",
            comicinfo_present=comicinfo_present
        )

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "filename": self.filename,
            "extension": self.extension,
            "sha256": self.sha256,
            "size": self.size,
            "mtime": self.mtime,
            "archive_type": self.archive_type,
            "comicinfo_present": self.comicinfo_present
        }
